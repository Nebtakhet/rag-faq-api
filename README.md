# rag-faq-api

Minimal RAG FAQ API built with FastAPI, OpenAI embeddings, and FAISS.

## Overview

This project indexes local documents and answers questions from retrieved context.

Core flow:

1. Load documents from `data/`
2. Split text into chunks
3. Create embeddings with OpenAI
4. Store vectors in FAISS
5. Retrieve top matches for a question
6. Generate a grounded answer

## Features

- Admin-only document ingestion
- Public read-only question endpoint
- Persistent FAISS index on disk
- Persistent metadata in SQL database (`documents`, `ingestion_runs`)
- Supported file types: `.txt`, `.md`, `.pdf`
- Request observability headers: `X-Request-ID`, `X-Process-Time-Ms`
- Structured JSON request logging with per-request correlation ID
- Prometheus metrics endpoint at `GET /metrics`
- Liveness endpoint at `GET /health/live`
- Standardized error payloads for validation, HTTP, and DB errors
- Redis-backed rate limiting (with in-memory fallback)

## Ingestion Behavior

- Uploaded files are written to `data/`.
- Upload and reindex both trigger a full index rebuild from all supported files in `data/`.
- Files that extract to empty text are skipped during indexing.
- Text is normalized before chunking (line-ending cleanup, PDF hyphen-wrap fixes, whitespace cleanup).
- Chunks are quality-filtered and deduplicated before embedding.
- PDF chunks include page markers (for example, `[Page 3]`) to improve answer traceability.
- After each run, document metadata and run status are saved in the SQL database.

## Requirements

- Python 3.11+
- A valid OpenAI API key

## Quick Start

1. Create and activate a virtual environment:

```bash
make venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
make install
```

3. Create `.env` in repo root:

```bash
cp .env.example .env
```

Then edit `.env` and set at least:

```bash
OPENAI_API_KEY=sk-your-real-key
ADMIN_API_KEY=my-admin-secret
MAX_UPLOAD_BYTES=5242880
```

Optional ingestion quality tuning:

```bash
INGESTION_CHUNK_SIZE=1000
INGESTION_CHUNK_OVERLAP=200
INGESTION_MIN_ALPHA_RATIO=0.15
```

- `INGESTION_CHUNK_SIZE`: chunk length target (minimum allowed by config validation: 100).
- `INGESTION_CHUNK_OVERLAP`: overlap between adjacent chunks.
- `INGESTION_MIN_ALPHA_RATIO`: filters low-signal chunks (too many symbols/numbers).

Optional rate limiting controls:

```bash
ASK_RATE_LIMIT=300/minute
ADMIN_RATE_LIMIT=120/minute
RATE_LIMIT_TRUST_PROXY_HEADERS=false
RATE_LIMIT_TRUSTED_PROXY_IPS=127.0.0.1
```

- `ASK_RATE_LIMIT`: limit for `GET /ask`.
- `ADMIN_RATE_LIMIT`: shared limit for admin endpoints (`/admin/*`).
- `RATE_LIMIT_TRUST_PROXY_HEADERS`: trust proxy headers for client IP extraction.
- `RATE_LIMIT_TRUSTED_PROXY_IPS`: proxy IP allowlist used when trusting `X-Forwarded-For`.

Optional keys in `.env.example` are also available for migration/docker setups (`SQLALCHEMY_DATABASE_URI`, `REDIS_URL`, etc.).

Database behavior:

- If `SQLALCHEMY_DATABASE_URI` is set, that database is used.
- Otherwise, the app defaults to local SQLite at `app.db`.

4. Run the API:

```bash
make run
```

5. Open docs UI:

```text
http://127.0.0.1:8000/docs
```

## Development Commands

```bash
make test        # run tests
make quality     # lint + format-check + mypy
make ci          # full local CI pipeline
```

## API Endpoints

- `GET /ask?question=...`
- `POST /admin/documents`
- `POST /admin/reindex`
- `GET /admin/documents`
- `GET /metrics`
- `GET /health/live`

Admin endpoints require header `X-Admin-Key: <ADMIN_API_KEY>`.

All responses include:

- `X-Request-ID`: request correlation ID (client-provided or generated)
- `X-Process-Time-Ms`: server-side request latency in milliseconds

Rate limiting:

- `GET /ask` is limited by `ASK_RATE_LIMIT`
- `/admin/*` endpoints are limited by `ADMIN_RATE_LIMIT`
- Exceeded limits return `HTTP 429`

## Example Usage

Upload documents:

```bash
curl -X POST "http://127.0.0.1:8000/admin/documents" \
  -H "X-Admin-Key: my-admin-secret" \
  -F "files=@data/faq.txt" \
  -F "files=@data/policies.md" \
  -F "files=@data/reference.pdf"
```

List indexed docs:

```bash
curl -X GET "http://127.0.0.1:8000/admin/documents" \
  -H "X-Admin-Key: my-admin-secret"
```

Ask a question:

```bash
curl "http://127.0.0.1:8000/ask?question=What%20does%20this%20project%20do%3F"
```

Reindex all files in `data/`:

```bash
curl -X POST "http://127.0.0.1:8000/admin/reindex" \
  -H "X-Admin-Key: my-admin-secret"
```

## Data and Persistence

- Uploaded source files are stored in `data/`
- FAISS index is persisted to:
  - `data/faiss.index`
  - `data/faiss_metadata.json`
- SQL persistence is stored in the configured DB URL (`SQLALCHEMY_DATABASE_URI`) or fallback `app.db`.

### Data Model

- `documents`
  - one row per supported file currently present in `data/`
  - stores `filename`, `extension`, `size_bytes`, `indexed_chunks`, `updated_at`
- `ingestion_runs`
  - one row per upload/reindex execution
  - stores `files_count`, `chunks_count`, `status`, `error_message`, `created_at`

### Runtime Persistence Flow

1. App startup initializes DB tables.
2. Upload or reindex rebuilds FAISS index.
3. On success/failure, ingestion run is recorded.
4. Document metadata is synchronized from disk into `documents`.
5. `GET /admin/documents` reads persisted rows first, then falls back to disk scan if DB is empty.

### Quality Pipeline Details

1. Read document (`.txt`, `.md`, `.pdf`).
2. Normalize extracted text.
3. Build chunks using configured size/overlap.
4. Remove empty, duplicated, and low-signal chunks.
5. Generate embeddings for remaining chunks.
6. Persist FAISS index and metadata.

## Architecture Layout

```text
app/
  core/
    config.py         # typed settings from .env
  db/
    base.py           # SQLAlchemy base
    models.py         # documents + ingestion_runs
    persistence.py    # DB init/read/write helpers
  services/
    chunking.py
    embeddings.py
    rag.py
  storage/
    vector_store.py   # FAISS wrapper
  main.py             # FastAPI routes and orchestration
```

## Common Errors

- `{"detail":"OPENAI_API_KEY is not configured","code":"http_error"}`:
  - `.env` is missing or invalid.
- `{"detail":"Document indexing failed while calling OpenAI. Check OPENAI_API_KEY.","code":"http_error"}`:
  - OpenAI key is invalid, expired, or has no billing access.
- `{"detail":"Unsupported file type: ...","code":"http_error"}`:
  - Only `.txt`, `.md`, `.pdf` are accepted.

Validation and auth errors are standardized:

- Validation failure: `{"detail":"Validation error","code":"validation_error","errors":[...]}`
- Auth/admin failures (`401`/`403`): `{"detail":"...","code":"auth_error"}`