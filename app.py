"""FileMind AI: document upload, summary, and grounded Q&A MVP."""
import csv
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytesseract
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from PIL import Image
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pypdf import PdfReader
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()
ALLOWED = {"pdf", "txt", "csv", "png", "jpg", "jpeg"}


def now():
    return datetime.now(timezone.utc)


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me"), JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY", "dev-jwt-change-me"), MONGODB_URI=os.getenv("MONGODB_URI", "mongodb://localhost:27017/"), MONGODB_DATABASE=os.getenv("MONGODB_DATABASE", "FileMindAI"), UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", "uploads"), MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024)
    if config:
        app.config.update(config)
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    client = MongoClient(app.config["MONGODB_URI"], serverSelectionTimeoutMS=2500)
    db = client[app.config["MONGODB_DATABASE"]]
    app.extensions["db"] = db
    users, files, chats = db.users, db.files, db.chats
    try:
        users.create_index("email", unique=True)
        files.create_index([("user_id", 1), ("uploaded_at", -1)])
        chats.create_index([("user_id", 1), ("file_id", 1), ("created_at", 1)])
    except PyMongoError:
        app.logger.warning("MongoDB indexes unavailable; check database connectivity.")

    def error(message, code=400):
        return jsonify({"error": message}), code

    def user_id():
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        try:
            return jwt.decode(header[7:], app.config["JWT_SECRET_KEY"], algorithms=["HS256"])["sub"]
        except jwt.PyJWTError:
            return None

    def auth(fn):
        from functools import wraps
        @wraps(fn)
        def wrapped(*args, **kwargs):
            uid = user_id()
            if not uid:
                return error("Please log in to continue.", 401)
            request.uid = uid
            return fn(*args, **kwargs)
        return wrapped

    def token(uid):
        return jwt.encode({"sub": uid, "exp": now() + timedelta(hours=24)}, app.config["JWT_SECRET_KEY"], algorithm="HS256")

    def extract(path, ext):
        if ext == "pdf":
            return "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages).strip()
        if ext == "txt":
            return path.read_text(encoding="utf-8", errors="replace").strip()
        if ext == "csv":
            with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
                return "\n".join(" | ".join(row) for row in csv.reader(f)).strip()
        if ext in {"png", "jpg", "jpeg"}:
            if os.getenv("TESSERACT_CMD"):
                pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD")
            return pytesseract.image_to_string(Image.open(path)).strip()
        raise ValueError("Unsupported file type.")

    def split_words(text, size=900, overlap=120):
        words, step = text.split(), max(1, size - overlap)
        return [" ".join(words[i:i + size]) for i in range(0, len(words), step)]

    def provider(prompt, limit=700):
        base, key, model = (os.getenv(x, "").rstrip("/") for x in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))
        if not (base and key and model):
            return None
        try:
            r = requests.post(base + "/chat/completions", headers={"Authorization": "Bearer " + key}, json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": limit}, timeout=90)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except (requests.RequestException, KeyError, IndexError, TypeError) as exc:
            app.logger.exception("AI provider failed")
            raise RuntimeError("AI provider request failed. Check settings and try again.") from exc

    def summarize(text):
        parts = split_words(text)
        if not parts:
            raise ValueError("No readable text was found in this file.")
        if all(os.getenv(x) for x in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")):
            notes = [provider("Summarize this document section using factual bullet points. Do not invent details.\n\n" + p, 400) for p in parts]
            return provider("Combine these into one concise summary with key points and conclusions.\n\n" + "\n\n".join(notes), 800) or "\n".join(notes), "ai"
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chosen = sorted(enumerate(sentences), key=lambda x: (-len(x[1].split()), x[0]))[:min(8, max(3, len(sentences) // 8))]
        return " ".join(s for _, s in sorted(chosen)).strip(), "extractive"

    def retrieve(text, question, limit=4):
        terms = set(re.findall(r"[a-z0-9]{2,}", question.lower()))
        parts = split_words(text, 220, 35)
        ranked = sorted(((sum(p.lower().count(t) for t in terms), i, p) for i, p in enumerate(parts)), key=lambda x: (-x[0], x[1]))
        matches = [p for score, _, p in ranked[:limit] if score]
        return matches or parts[:limit]

    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        return jsonify(ok=True, ai_configured=all(os.getenv(x) for x in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")))

    @app.get("/api/test-db")
    def test_db():
        try:
            db.command("ping")
            return jsonify(ok=True, database=app.config["MONGODB_DATABASE"])
        except PyMongoError:
            return error("MongoDB unavailable. Start it and check MONGODB_URI.", 503)

    @app.post("/api/register")
    def register():
        b = request.get_json(silent=True) or {}
        name, email, password = str(b.get("name", "")).strip(), str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
        if not name or len(name) > 100 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            return error("Enter a name and valid email address.")
        if len(password) < 8:
            return error("Password must be at least 8 characters.")
        uid = secrets.token_urlsafe(18)
        try:
            users.insert_one({"_id": uid, "name": name, "email": email, "password_hash": generate_password_hash(password), "created_at": now()})
        except PyMongoError as exc:
            return error("An account with that email exists." if "duplicate" in str(exc).lower() else "Could not create account; check MongoDB.", 409 if "duplicate" in str(exc).lower() else 503)
        return jsonify(token=token(uid), user={"id": uid, "name": name, "email": email}), 201

    @app.post("/api/login")
    def login():
        b = request.get_json(silent=True) or {}
        try:
            u = users.find_one({"email": str(b.get("email", "")).strip().lower()})
        except PyMongoError:
            return error("Database unavailable.", 503)
        if not u or not check_password_hash(u["password_hash"], str(b.get("password", ""))):
            return error("Email or password is incorrect.", 401)
        return jsonify(token=token(u["_id"]), user={"id": u["_id"], "name": u["name"], "email": u["email"]})

    @app.post("/api/upload")
    @auth
    def upload():
        f = request.files.get("file")
        if not f or not f.filename:
            return error("Choose a file to upload.")
        name = secure_filename(f.filename)
        if "." not in name or name.rsplit(".", 1)[1].lower() not in ALLOWED:
            return error("Supported formats: PDF, TXT, CSV, PNG, JPG, JPEG.")
        ext, fid = name.rsplit(".", 1)[1].lower(), secrets.token_urlsafe(18)
        stored, path = fid + "." + name.rsplit(".", 1)[1].lower(), upload_dir / (fid + "." + name.rsplit(".", 1)[1].lower())
        try:
            f.save(path)
            text = extract(path, ext)
            if not text:
                raise ValueError("No readable text found. Scanned PDFs need OCR.")
            record = {"_id": fid, "user_id": request.uid, "original_name": name, "stored_name": stored, "extension": ext, "size": path.stat().st_size, "text": text, "uploaded_at": now(), "summary": None, "summary_mode": None}
            files.insert_one(record)
            return jsonify(id=fid, name=name, size=record["size"], characters=len(text), uploaded_at=record["uploaded_at"].isoformat()), 201
        except ValueError as exc:
            path.unlink(missing_ok=True)
            return error(str(exc))
        except Exception:
            path.unlink(missing_ok=True)
            app.logger.exception("Upload processing error")
            return error("Could not process this file. Check its format and try again.", 422)

    @app.get("/api/files")
    @auth
    def list_files():
        try:
            rows = [{"id": d["_id"], "name": d["original_name"], "size": d["size"], "uploaded_at": d["uploaded_at"].isoformat(), "has_summary": bool(d.get("summary"))} for d in files.find({"user_id": request.uid}, {"text": 0}).sort("uploaded_at", -1)]
            return jsonify(files=rows)
        except PyMongoError:
            return error("Could not load file history.", 503)

    @app.get("/api/files/<fid>")
    @auth
    def detail(fid):
        d = files.find_one({"_id": fid, "user_id": request.uid}, {"text": 0})
        if not d:
            return error("File not found.", 404)
        return jsonify(id=fid, name=d["original_name"], summary=d.get("summary"), summary_mode=d.get("summary_mode"), uploaded_at=d["uploaded_at"].isoformat())

    @app.post("/api/files/<fid>/summarize")
    @auth
    def do_summary(fid):
        d = files.find_one({"_id": fid, "user_id": request.uid})
        if not d:
            return error("File not found.", 404)
        try:
            result, mode = summarize(d["text"])
            files.update_one({"_id": fid, "user_id": request.uid}, {"$set": {"summary": result, "summary_mode": mode}})
            return jsonify(summary=result, mode=mode)
        except (ValueError, RuntimeError) as exc:
            return error(str(exc), 502 if isinstance(exc, RuntimeError) else 422)

    @app.post("/api/files/<fid>/ask")
    @auth
    def ask(fid):
        q = str((request.get_json(silent=True) or {}).get("question", "")).strip()
        if not q or len(q) > 2000:
            return error("Enter a question up to 2,000 characters.")
        d = files.find_one({"_id": fid, "user_id": request.uid})
        if not d:
            return error("File not found.", 404)
        passages = retrieve(d["text"], q)
        prompt = "Answer using only these source passages. If unsupported, say you could not find the answer. Cite passage numbers.\nQuestion: " + q + "\n" + "\n".join(f"[{i+1}] {p}" for i, p in enumerate(passages))
        try:
            answer = provider(prompt, 650)
            mode = "ai" if answer else "retrieval"
            if not answer:
                answer = "Relevant passages (configure an AI provider for a synthesized answer):\n\n" + "\n\n".join(f"[{i+1}] {p}" for i, p in enumerate(passages))
            chats.insert_one({"_id": secrets.token_urlsafe(18), "user_id": request.uid, "file_id": fid, "question": q, "answer": answer, "created_at": now(), "mode": mode})
            return jsonify(answer=answer, mode=mode)
        except (RuntimeError, PyMongoError) as exc:
            return error(str(exc) if isinstance(exc, RuntimeError) else "Could not save conversation.", 502)

    @app.get("/api/files/<fid>/chats")
    @auth
    def history(fid):
        if not files.find_one({"_id": fid, "user_id": request.uid}, {"_id": 1}):
            return error("File not found.", 404)
        rows = [{"question": x["question"], "answer": x["answer"], "mode": x.get("mode", "retrieval"), "created_at": x["created_at"].isoformat()} for x in chats.find({"user_id": request.uid, "file_id": fid}).sort("created_at", 1)]
        return jsonify(chats=rows)

    @app.delete("/api/files/<fid>")
    @auth
    def delete(fid):
        d = files.find_one_and_delete({"_id": fid, "user_id": request.uid})
        if not d:
            return error("File not found.", 404)
        (upload_dir / d["stored_name"]).unlink(missing_ok=True)
        chats.delete_many({"user_id": request.uid, "file_id": fid})
        return jsonify(deleted=True)

    @app.errorhandler(413)
    def too_large(_):
        return error("File exceeds the configured upload limit.", 413)

    return app


app = create_app()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
