# rag-faq-api
Minimal RAG based FAQ API, built with FastAPI, OpenAI embeddings and FAISS

# GenAI FAQ Chat (RAG Prototype)

A clean, minimal Retrieval-Augmented Generation (RAG) system for question answering over custom documents.

This project builds a production-style RAG pipeline from scratch using:

- OpenAI embeddings
- FAISS vector store
- FastAPI backend
- Prompt-controlled LLM generation

No frameworks. No LangChain.

The system:

1. Loads local documents
2. Chunks text with overlap
3. Generates embeddings
4. Stores vectors in FAISS
5. Retrieves relevant chunks via similarity search
6. Injects context into a controled prompt
7. Returns grounded answers

This repository will focus on architecture clarity and cost awareness.

## Admin-managed document ingestion (MVP)

The API supports a master/admin flow where only authorized users can upload source documents.

### Required environment variables

- `OPENAI_API_KEY`: OpenAI key for embeddings and answer generation.
- `ADMIN_API_KEY`: secret key required for all `/admin/*` endpoints.
- `MAX_UPLOAD_BYTES` (optional): max file size in bytes per upload (default `5242880`).

### Supported document types

- `.txt`
- `.md`

Uploaded files are stored under `data/`.
The FAISS index and metadata are persisted in `data/faiss.index` and `data/faiss_metadata.json`.

### Endpoints

- `GET /ask?question=...` (public, read-only)
- `POST /admin/documents` (admin-only, multipart upload)
- `POST /admin/reindex` (admin-only, full rebuild from `data/`)
- `GET /admin/documents` (admin-only, list known documents and indexed chunk count)

### Example usage

Upload docs:

```bash
curl -X POST "http://localhost:8000/admin/documents" \
	-H "X-Admin-Key: $ADMIN_API_KEY" \
	-F "files=@data/faq.txt" \
	-F "files=@data/policies.md"
```

Reindex all docs:

```bash
curl -X POST "http://localhost:8000/admin/reindex" \
	-H "X-Admin-Key: $ADMIN_API_KEY"
```

List loaded docs:

```bash
curl -X GET "http://localhost:8000/admin/documents" \
	-H "X-Admin-Key: $ADMIN_API_KEY"
```