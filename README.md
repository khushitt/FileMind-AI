# FileMind AI

An AI-assisted document workspace built with Flask, MongoDB, and vanilla HTML/CSS/JavaScript. Users can register, upload documents, generate summaries, and ask questions grounded in retrieved passages.

## What works in this project

- Email and password registration/login; passwords are stored as Werkzeug password hashes and API access uses signed, expiring JWTs.
- Per-user file ownership checks for reading, summarizing, asking questions, history, and deletion.
- Uploads for PDF, TXT, CSV, PNG, JPG, and JPEG, with a default 10 MB request limit.
- PDF text extraction, UTF-8 text/CSV reading, and optional OCR for images.
- Persistent summaries and conversation history in MongoDB; uploaded file bytes stored on disk.
- Long-document chunking, passage retrieval, and a configurable OpenAI-compatible chat-completions provider.
- Fallback behavior when no AI provider is configured: extractive summaries and retrieved source passages. These are useful fallbacks, not generative AI answers.
- Responsive dashboard with upload, document list, summary, Q&A, and delete actions.

## Requirements

- Python 3.10 or newer.
- MongoDB Community Server or a MongoDB-compatible hosted database.
- For image OCR, the Tesseract executable installed separately. The Python wrapper alone is not the OCR engine.
- Optional AI provider credentials for generated summaries and synthesized answers. Configure a provider that implements the OpenAI-compatible `POST /chat/completions` interface.

## Run locally (Windows PowerShell)

1. Open PowerShell in this `FileMindAI` folder.
2. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install packages and create local configuration:

   ```powershell
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

4. Edit `.env`. Set unique random values for both secret keys. Set `MONGODB_URI` if MongoDB is not using its local default. To enable generated summaries and answers, set `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` for your chosen compatible service. Do not commit `.env`.
5. Start MongoDB, then run:

   ```powershell
   python app.py
   ```

6. Open [http://127.0.0.1:5000](http://127.0.0.1:5000). Use `/api/status` to inspect service configuration and `/api/test-db` to check database connectivity.

Linux/macOS users can use `python3 -m venv .venv`, `source .venv/bin/activate`, and `cp .env.example .env` for the equivalent setup.

## Project structure

```text
FileMindAI/
├── app.py                 Flask app, API routes, extraction, retrieval, AI adapter
├── requirements.txt       Python dependencies
├── .env.example           Configuration template
├── templates/index.html   Login and document workspace
├── static/styles.css      Responsive visual design
├── static/app.js          Frontend interactions and API client
└── uploads/               Original uploaded files (ignored by Git)
```

## API overview

All routes except status, database check, register, and login require `Authorization: Bearer <token>`.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/status` | Service and AI-configuration status |
| GET | `/api/test-db` | Ping MongoDB |
| POST | `/api/register` | Register `{ "name", "email", "password" }` |
| POST | `/api/login` | Log in with `{ "email", "password" }` |
| POST | `/api/upload` | Multipart form upload; field name `file` |
| GET | `/api/files` | Current user's document history |
| GET | `/api/files/<id>` | Document metadata and saved summary |
| POST | `/api/files/<id>/summarize` | Generate and save a summary |
| POST | `/api/files/<id>/ask` | Ask `{ "question": "..." }` about a document |
| GET | `/api/files/<id>/chats` | Conversation history for a document |
| DELETE | `/api/files/<id>` | Delete owned document, original file, and chats |

Responses use JSON. Errors use an `error` property and an appropriate HTTP status code.

## Data model

- `users`: `_id`, `name`, `email` (unique index), `password_hash`, `created_at`.
- `files`: `_id`, `user_id`, `original_name`, `stored_name`, `extension`, `size`, `text`, `uploaded_at`, `summary`, `summary_mode`.
- `chats`: `_id`, `user_id`, `file_id`, `question`, `answer`, `created_at`, `mode`.

File content is extracted and stored in MongoDB to support processing after upload. The original binary is stored in the configured upload directory. Keep both stores backed up and remove both when deleting a document.

## How Q&A works

1. Extract text when the document is uploaded.
2. Split extracted text into overlapping word windows.
3. Score windows by occurrences of terms from the user's question and select the strongest passages.
4. If an AI provider is configured, send only those passages and the question to the provider. The prompt requires a source-grounded answer and an uncertainty response when unsupported.
5. If no provider is configured, display the retrieved passages directly. This fallback does not claim to synthesize an answer.

The included lexical retrieval is deliberately lightweight. For larger deployments, replace it with BM25 or vector embeddings, add page/section metadata, and return source citations linked to original pages.

## Security and deployment notes

- Change both development secrets before use. Protect `.env` and never commit keys.
- Use HTTPS, a production WSGI server, secure cookie/session strategy if switching from bearer tokens, rate limits, CSRF protections for cookie-based auth, and request logging with secret/document redaction before deployment.
- Add MIME/content-signature checks, malware scanning, quotas, retention settings, and storage outside the web root for untrusted public uploads.
- Limit document retention and disclose that document passages are sent to the configured external AI provider when enabled.
- Do not enable Flask debug mode in production. The included server is for local development.
- Scanned PDFs are not OCR processed in this MVP; image uploads can use OCR if Tesseract is installed. Add PDF OCR for scanned-document support.
- The UI stores the bearer token in browser local storage for this educational MVP. A production app should evaluate a stronger session design and its XSS threat model.

## Suggested next milestones

1. Add validation and automated coverage for authentication, upload edge cases, ownership boundaries, and extraction.
2. Add background jobs and processing states for large files.
3. Add vector/BM25 retrieval, page-aware citations, and evaluation against a question-answer dataset.
4. Add DOCX/XLSX/PPTX support, OCR for scanned PDFs, exports, and multilingual controls.
5. Deploy behind HTTPS with managed secrets, object storage, backups, monitoring, and documented retention policy.

## Resume description

**FileMind AI — AI-powered document assistant:** Built a Flask and MongoDB web application with secure account registration, document upload and text extraction, saved file/chat history, chunk-based passage retrieval, and configurable AI-powered summaries and document Q&A. Included a responsive JavaScript dashboard and extractive/retrieval fallbacks when an AI provider is not configured.
