from contextlib import asynccontextmanager
from collections.abc import Sequence
from collections.abc import Awaitable
from collections.abc import Callable
import logging
from pathlib import Path
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from openai import OpenAIError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.dependencies import require_admin as _require_admin
from app.db import init_db, list_persisted_documents, record_ingestion_run, sync_documents_from_disk
from app.core.config import settings
from app.core.logging import configure_logging, reset_request_id, set_request_id
from app.core.metrics import IN_PROGRESS, metrics_payload, record_request
from app.core.rate_limit import limiter
from app.services.chunking import prepare_chunks
from app.services.embeddings import embed_text
from app.services.rag import generate_answer
from app.storage.vector_store import VectorStore

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INDEX_PATH = DATA_DIR / "faiss.index"
METADATA_PATH = DATA_DIR / "faiss_metadata.json"
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}
MAX_UPLOAD_BYTES = settings.max_upload_bytes
ADMIN_API_KEY = settings.admin_api_key

vector_store = None

configure_logging()
logger = logging.getLogger("app.request")


def on_startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    _load_existing_index()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    on_startup()
    yield


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def add_observability_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    token = set_request_id(request_id)
    start = perf_counter()
    IN_PROGRESS.inc()
    route_path = request.url.path
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        duration_ms = (perf_counter() - start) * 1000
        record_request(
            method=request.method,
            path=route_path,
            status_code=status_code,
            duration_seconds=duration_ms / 1000,
        )
        logger.exception(
            "request.failed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(duration_ms, 2),
            },
        )
        reset_request_id(token)
        IN_PROGRESS.dec()
        raise

    duration_ms = (perf_counter() - start) * 1000
    route = request.scope.get("route")
    if route is not None and hasattr(route, "path"):
        route_path = route.path
    record_request(
        method=request.method,
        path=route_path,
        status_code=status_code,
        duration_seconds=duration_ms / 1000,
    )
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request.completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    reset_request_id(token)
    IN_PROGRESS.dec()
    return response


def error_payload(
    detail: str,
    code: str,
    errors: Sequence[object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"detail": detail, "code": code}
    if errors is not None:
        payload["errors"] = errors
    return payload


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422,
        content=error_payload(
            detail="Validation error",
            code="validation_error",
            errors=errors,
        ),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = "auth_error" if exc.status_code in (401, 403) else "http_error"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(detail=str(exc.detail), code=code),
    )


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=error_payload(detail="Database integrity error", code="db_integrity_error"),
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_payload(detail="Database error", code="db_error"),
    )


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
    _require_admin(x_admin_key)


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


@limiter.limit(settings.ask_rate_limit)
def ask(request: Request, question: str):
    if vector_store is None:
        raise HTTPException(status_code=400, detail="No indexed documents. Upload documents first.")
    try:
        answer = generate_answer(question, vector_store)
    except Exception as exc:
        _raise_processing_http_error(exc)
    return {"answer": answer}


async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    _: None = Depends(_require_admin),
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


@limiter.limit(settings.admin_rate_limit)
def reindex_documents(request: Request, _: None = Depends(_require_admin)):
    try:
        summary = _rebuild_index_from_data()
        _persist_index_state(summary, status="success")
    except Exception as exc:
        _persist_index_state({"files": 0, "chunks": 0}, status="failed", error_message=str(exc))
        _raise_processing_http_error(exc)
    return {"reindexed": summary}


@limiter.limit(settings.admin_rate_limit)
def list_documents(request: Request, _: None = Depends(_require_admin)):
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


upload_documents = limiter.limit(settings.admin_rate_limit)(upload_documents)


def _register_routers() -> None:
    from app.api.admin import router as admin_router
    from app.api.public import router as public_router

    app.include_router(public_router)
    app.include_router(admin_router)


_register_routers()


@app.get("/metrics")
async def metrics() -> Response:
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}
