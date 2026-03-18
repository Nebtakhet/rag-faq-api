from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from openai import OpenAIError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.db import init_db, list_persisted_documents, record_ingestion_run, sync_documents_from_disk
from app.core.config import settings
from app.services.chunking import prepare_chunks
from app.services.embeddings import embed_text
from app.services.rag import generate_answer
from app.storage.vector_store import VectorStore

app = FastAPI()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INDEX_PATH = DATA_DIR / "faiss.index"
METADATA_PATH = DATA_DIR / "faiss_metadata.json"
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}
MAX_UPLOAD_BYTES = settings.max_upload_bytes
ADMIN_API_KEY = settings.admin_api_key

vector_store = None


def _indexed_chunks_by_source() -> dict[str, int]:
    if vector_store is None:
        return {}
    counts: dict[str, int] = {}
    for item in vector_store.metadata:
        source = item.get("source")
        if not isinstance(source, str):
            continue
        counts[source] = counts.get(source, 0) + 1
    return counts


def _persist_index_state(summary: dict, status: str, error_message: str | None = None) -> None:
    sync_documents_from_disk(DATA_DIR, ALLOWED_EXTENSIONS, _indexed_chunks_by_source())
    record_ingestion_run(
        files_count=int(summary.get("files", 0)),
        chunks_count=int(summary.get("chunks", 0)),
        status=status,
        error_message=error_message,
    )


def _raise_processing_http_error(exc: Exception) -> None:
    if isinstance(exc, PdfReadError):
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}") from exc
    if isinstance(exc, RuntimeError) and str(exc) == "OPENAI_API_KEY is not set":
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured") from exc
    if isinstance(exc, OpenAIError):
        raise HTTPException(
            status_code=502,
            detail="Document indexing failed while calling OpenAI. Check OPENAI_API_KEY.",
        ) from exc
    raise exc


def require_admin(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    admin_api_key = settings.admin_api_key
    if not admin_api_key:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY is not configured")
    if x_admin_key != admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


def _load_existing_index() -> None:
    global vector_store
    if INDEX_PATH.exists() and METADATA_PATH.exists():
        vector_store = VectorStore.load(INDEX_PATH, METADATA_PATH)


def _read_text_file(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf_file(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if not page_text:
            continue
        pages.append(f"[Page {page_number}]\n{page_text}")
    return "\n\n".join(pages)


def _read_document(file_path: Path) -> str:
    if file_path.suffix.lower() == ".pdf":
        return _read_pdf_file(file_path)
    return _read_text_file(file_path)


def _rebuild_index_from_data() -> dict:
    global vector_store
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [
            path
            for path in DATA_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
        ]
    )

    if not files:
        vector_store = None
        if INDEX_PATH.exists():
            INDEX_PATH.unlink()
        if METADATA_PATH.exists():
            METADATA_PATH.unlink()
        return {"files": 0, "chunks": 0}

    total_chunks = 0
    store = None

    for source_file in files:
        text = _read_document(source_file)
        if not text.strip():
            continue

        chunks = prepare_chunks(
            text,
            chunk_size=settings.ingestion_chunk_size,
            overlap=settings.ingestion_chunk_overlap,
            min_alpha_ratio=settings.ingestion_min_alpha_ratio,
        )
        if not chunks:
            continue

        embeddings = embed_text(chunks)
        if not embeddings:
            continue

        if store is None:
            store = VectorStore(dimension=len(embeddings[0]))

        for chunk_id, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            store.add_vector(
                embedding,
                {
                    "source": source_file.name,
                    "chunk_id": chunk_id,
                    "text": chunk,
                },
            )
            total_chunks += 1

    if store is None:
        vector_store = None
        return {"files": len(files), "chunks": 0}

    store.save(INDEX_PATH, METADATA_PATH)
    vector_store = store
    return {"files": len(files), "chunks": total_chunks}


@app.on_event("startup")
def on_startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    _load_existing_index()


@app.get("/ask")
def ask(question: str):
    if vector_store is None:
        raise HTTPException(status_code=400, detail="No indexed documents. Upload documents first.")
    try:
        answer = generate_answer(question, vector_store)
    except Exception as exc:
        _raise_processing_http_error(exc)
    return {"answer": answer}


@app.post("/admin/documents")
async def upload_documents(
    files: list[UploadFile] = File(...),
    _: None = Depends(require_admin),
):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    uploaded = []

    for upload in files:
        filename = Path(upload.filename or "").name
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")

        payload = await upload.read()
        if len(payload) > settings.max_upload_bytes:
            raise HTTPException(status_code=400, detail=f"File too large: {filename}")

        target = DATA_DIR / filename
        target.write_bytes(payload)
        uploaded.append(filename)

    try:
        summary = _rebuild_index_from_data()
        _persist_index_state(summary, status="success")
    except Exception as exc:
        _persist_index_state({"files": 0, "chunks": 0}, status="failed", error_message=str(exc))
        _raise_processing_http_error(exc)
    return {
        "uploaded": uploaded,
        "reindexed": summary,
    }


@app.post("/admin/reindex")
def reindex_documents(_: None = Depends(require_admin)):
    try:
        summary = _rebuild_index_from_data()
        _persist_index_state(summary, status="success")
    except Exception as exc:
        _persist_index_state({"files": 0, "chunks": 0}, status="failed", error_message=str(exc))
        _raise_processing_http_error(exc)
    return {"reindexed": summary}


@app.get("/admin/documents")
def list_documents(_: None = Depends(require_admin)):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    persisted = list_persisted_documents()
    if persisted:
        files = [str(row["filename"]) for row in persisted]
        indexed_chunks = sum(int(row["indexed_chunks"]) for row in persisted)
        return {
            "documents": files,
            "indexed_chunks": indexed_chunks,
        }

    files = sorted(
        [
            path.name
            for path in DATA_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
        ]
    )

    indexed_chunks = 0
    if vector_store is not None:
        indexed_chunks = len(vector_store.metadata)

    return {
        "documents": files,
        "indexed_chunks": indexed_chunks,
    }
