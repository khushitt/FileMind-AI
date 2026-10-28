# FileMind AI — Project Report

## Abstract

FileMind AI is a web-based document assistant that helps a user understand digital documents. A user uploads a supported file, the system extracts its text, produces a concise summary, and accepts natural-language questions. Question answering first retrieves passages that match the question and, when configured, asks a language model to answer from those passages. User accounts, document metadata, summaries, and conversation records are stored in MongoDB; original files are kept in local file storage.

## Problem statement

Reading long reports, study materials, and notes to find a small piece of information takes time. Ordinary file storage can keep documents but does not explain their contents or help locate relevant passages. FileMind AI provides document-centered summarization and question answering through one simple workspace.

## Objectives

1. Provide account registration and login with hashed passwords.
2. Accept and validate supported document uploads.
3. Extract readable text from PDFs, text files, CSV files, and OCR-capable images.
4. Summarize document content and retain the result.
5. Retrieve relevant passages and answer questions using document context.
6. Maintain user-specific file and chat history with access controls.
7. Provide clear error feedback and a responsive web interface.

## Scope

The implemented MVP supports PDF, TXT, CSV, PNG, JPG, and JPEG up to a configurable default of 10 MB. PDF text extraction works for text-based PDFs. Image OCR requires the separately installed Tesseract engine. Scanned PDF OCR, Office formats, audio, multi-tenant cloud storage, and production deployment automation are outside this MVP.

## Technology stack

| Layer | Technology | Role |
|---|---|---|
| Frontend | HTML, CSS, JavaScript | Login, upload, history, summary, Q&A |
| Backend | Python, Flask | REST API, validation, authentication, processing |
| Database | MongoDB | Accounts, document text/metadata, summaries, chats |
| File storage | Local uploads directory | Original file binaries |
| Document processing | pypdf, Python CSV, pytesseract/Pillow | Text and image extraction |
| AI integration | Configurable OpenAI-compatible API | Summary generation and grounded answers |
| Version control | Git | Source history and collaboration |

## Architecture and data flow

```text
Browser
  ├── register/login ──> Flask API ──> MongoDB users
  ├── upload file ─────> validation ─> local file + extracted text in MongoDB
  ├── summarize ───────> chunking ───> AI provider or extractive fallback
  └── ask question ────> retrieval ──> AI provider or source-passage fallback
                                      └──> MongoDB chat history
```

The backend signs a short-lived JWT after registration/login. Protected routes identify the account from the bearer token and scope document queries by `user_id`. Uploaded content is extracted before a document record is created. Q&A retrieves relevant chunks before sending context to the language model, which reduces irrelevant context and helps ground the response.

## Database collections

### Users

`_id`, `name`, `email`, `password_hash`, `created_at`. Email has a unique index; the password itself is never stored.

### Files

`_id`, `user_id`, `original_name`, `stored_name`, `extension`, `size`, `text`, `uploaded_at`, `summary`, `summary_mode`. The text field supports later summary and Q&A requests without reparsing the original binary.

### Chats

`_id`, `user_id`, `file_id`, `question`, `answer`, `created_at`, `mode`. Each record is scoped to both its owner and document.

## Main algorithms

### Summarization

Extracted content is split into overlapping word windows. If an AI provider is configured, each window receives a short factual summary; those summaries are combined. If not, the fallback selects longer sentences from the source text to create an extractive overview. The response identifies which mode was used.

### Question answering

The question is normalized into terms. The document is split into passages and passages are ranked by term frequency. The strongest passages are supplied to the configured AI provider with an instruction to answer only from those sources and state when evidence is absent. Without an AI provider, the app returns the passages themselves so it does not present a retrieval result as a generated answer.

## Security considerations

Passwords are hashed; bearer tokens expire; upload names are sanitized and replaced with server-generated names; uploads have a size limit and extension allowlist; protected routes query records by the authenticated owner. Production deployment should add HTTPS, content-signature checks, malware scanning, rate limiting, secret management, storage quotas, backups, retention controls, and a production-grade session/XSS strategy. Confidential document text is sent to the configured external model when that integration is enabled.

## Limitations

- Lexical passage matching can miss paraphrases and semantic relationships.
- Extractive fallback summaries select sentences and may lack coherence.
- Text extraction cannot read scanned PDF pages without an OCR pipeline.
- Provider output can still be incomplete or wrong; important information should be verified in the source.
- Synchronous processing can be slow for large files; a production system should use background workers.

## Future enhancements

- Vector embeddings or BM25 retrieval and page-number citations.
- OCR for scanned PDF files and improved extraction diagnostics.
- DOCX, XLSX, and PPTX support.
- Background processing with progress indicators and retry handling.
- Summary export, multilingual responses, and accessibility improvements.
- Cloud object storage, admin monitoring, usage quotas, retention controls, and deployment pipeline.

## Conclusion

FileMind AI combines document storage with content understanding. The MVP establishes the complete flow from account creation through upload, extraction, summary, grounded question answering, and persistent history. Its modular Flask routes and provider adapter make it possible to improve retrieval, extraction, and deployment without replacing the user-facing workflow.

## Viva questions

**What is FileMind AI?** A web-based assistant that summarizes uploaded documents and answers questions using relevant document passages.

**Why use retrieval before generation?** Retrieval selects the most relevant sections and gives the model evidence, reducing irrelevant context and unsupported answers.

**Why store the extracted text?** It avoids repeating extraction for summaries and follow-up questions and makes document search faster.

**How are user files protected?** API routes require a signed token and query file/chat records using both the record ID and the authenticated owner's ID.

**What happens if no AI key is configured?** The app uses an extractive sentence summary and displays matched passages rather than claiming to generate an AI answer.

**What is a key limitation?** The MVP uses lexical matching and basic extraction; semantic retrieval, scanned-PDF OCR, and production-grade deployment are future work.
