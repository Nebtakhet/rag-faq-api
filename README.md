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
- Supported file types: `.txt`, `.md`, `.pdf`

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

Optional keys in `.env.example` are also available for migration/docker setups (`SQLALCHEMY_DATABASE_URI`, `REDIS_URL`, etc.).

4. Run the API:

```bash
make run
```

5. Open docs UI:

```text
http://127.0.0.1:8000/docs
```

## API Endpoints

- `GET /ask?question=...`
- `POST /admin/documents`
- `POST /admin/reindex`
- `GET /admin/documents`

Admin endpoints require header `X-Admin-Key: <ADMIN_API_KEY>`.

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

## Common Errors

- `{"detail":"OPENAI_API_KEY is not configured"}`:
	- `.env` is missing or invalid.
- `{"detail":"Document indexing failed while calling OpenAI. Check OPENAI_API_KEY."}`:
	- OpenAI key is invalid, expired, or has no billing access.
- `{"detail":"Unsupported file type: ..."}`:
	- Only `.txt`, `.md`, `.pdf` are accepted.