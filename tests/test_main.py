import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from openai import OpenAIError
from pypdf.errors import PdfReadError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.requests import Request

from app import main


def make_request(path: str = "/") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


def test_error_payload_includes_optional_errors() -> None:
    assert main.error_payload("detail", "code") == {"detail": "detail", "code": "code"}
    assert main.error_payload("detail", "code", errors=[{"loc": ["q"], "msg": "bad"}]) == {
        "detail": "detail",
        "code": "code",
        "errors": [{"loc": ["q"], "msg": "bad"}],
    }


def test_normalize_path_uses_unknown_for_empty_path() -> None:
    from app.core.metrics import normalize_path

    assert normalize_path("") == "unknown"


def test_indexed_chunks_by_source_handles_missing_store(monkeypatch) -> None:
    monkeypatch.setattr(main, "vector_store", None)

    assert main._indexed_chunks_by_source() == {}


def test_raise_processing_http_error_maps_known_failures() -> None:
    with pytest.raises(HTTPException, match="Could not read PDF"):
        main._raise_processing_http_error(PdfReadError("bad pdf"))

    with pytest.raises(HTTPException, match="OPENAI_API_KEY is not configured"):
        main._raise_processing_http_error(RuntimeError("OPENAI_API_KEY is not set"))

    with pytest.raises(HTTPException, match="Document indexing failed while calling OpenAI"):
        main._raise_processing_http_error(OpenAIError("boom"))

    with pytest.raises(RuntimeError, match="other failure"):
        main._raise_processing_http_error(RuntimeError("other failure"))


@pytest.mark.anyio
async def test_exception_handlers_return_structured_payloads() -> None:
    request = make_request("/error")

    validation_response = await main.validation_exception_handler(
        request,
        RequestValidationError([{"loc": ("question",), "msg": "required", "type": "missing"}]),
    )
    assert validation_response.status_code == 422
    assert json.loads(validation_response.body)["code"] == "validation_error"

    auth_response = await main.http_exception_handler(
        request,
        HTTPException(status_code=401, detail="nope"),
    )
    assert auth_response.status_code == 401
    assert json.loads(auth_response.body)["code"] == "auth_error"

    http_response = await main.http_exception_handler(
        request,
        HTTPException(status_code=404, detail="missing"),
    )
    assert http_response.status_code == 404
    assert json.loads(http_response.body)["code"] == "http_error"

    integrity_response = await main.integrity_exception_handler(
        request,
        IntegrityError("stmt", {}, Exception("orig")),
    )
    assert integrity_response.status_code == 409

    sqlalchemy_response = await main.sqlalchemy_exception_handler(request, SQLAlchemyError("boom"))
    assert sqlalchemy_response.status_code == 500


def test_rebuild_index_skips_blank_documents(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "blank.txt").write_text("   \n", encoding="utf-8")
    (tmp_path / "doc.txt").write_text("hello", encoding="utf-8")

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "INDEX_PATH", tmp_path / "faiss.index")
    monkeypatch.setattr(main, "METADATA_PATH", tmp_path / "faiss_metadata.json")
    monkeypatch.setattr(main, "prepare_chunks", lambda text, **_kwargs: [text])
    monkeypatch.setattr(main, "embed_text", lambda chunks: [[0.1, 0.2] for _ in chunks])

    summary = main._rebuild_index_from_data()

    assert summary == {"files": 2, "chunks": 1}


def test_request_middleware_records_failure(monkeypatch) -> None:
    @main.app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500


@pytest.mark.anyio
async def test_health_endpoints_report_degraded_database(monkeypatch) -> None:
    async def database_down() -> bool:
        return False

    monkeypatch.setattr(main, "_database_connected", database_down)

    ready_response = await main.health_ready()
    assert ready_response.status_code == 503
    assert json.loads(ready_response.body)["status"] == "degraded"

    health_response = await main.health_check()
    assert health_response["status"] == "degraded"


def reset_rate_limits() -> None:
    main.limiter._storage.reset()


async def async_empty_list_persisted_documents() -> list[dict[str, int | str]]:
    return []


async def async_noop(*_args, **_kwargs) -> None:
    return None


def test_require_admin_missing_config(monkeypatch) -> None:
    monkeypatch.setattr(main, "ADMIN_API_KEY", "")
    monkeypatch.setattr(main.settings, "admin_api_key", "")

    with pytest.raises(HTTPException, match="ADMIN_API_KEY is not configured"):
        main.require_admin("anything")


def test_require_admin_invalid_key(monkeypatch) -> None:
    monkeypatch.setattr(main, "ADMIN_API_KEY", "secret")
    monkeypatch.setattr(main.settings, "admin_api_key", "secret")

    with pytest.raises(HTTPException, match="Invalid admin key"):
        main.require_admin("wrong")


def test_require_admin_valid_key(monkeypatch) -> None:
    monkeypatch.setattr(main, "ADMIN_API_KEY", "secret")
    monkeypatch.setattr(main.settings, "admin_api_key", "secret")
    main.require_admin("secret")


def test_ask_requires_vector_store(monkeypatch) -> None:
    monkeypatch.setattr(main, "vector_store", None)

    with pytest.raises(HTTPException, match="No indexed documents"):
        main.ask(make_request("/ask"), "hello")


def test_ask_returns_generated_answer(monkeypatch) -> None:
    monkeypatch.setattr(main, "vector_store", object())
    monkeypatch.setattr(main, "generate_answer", lambda _q, _s: "ok")

    assert main.ask(make_request("/ask"), "hello") == {"answer": "ok"}


def test_ask_maps_processing_errors(monkeypatch) -> None:
    monkeypatch.setattr(main, "vector_store", object())

    def fail_generate_answer(_question: str, _store: object) -> str:
        raise PdfReadError("bad pdf")

    monkeypatch.setattr(main, "generate_answer", fail_generate_answer)

    with pytest.raises(HTTPException, match="Could not read PDF"):
        main.ask(make_request("/ask"), "hello")


def test_ask_endpoint_returns_429_after_limit(monkeypatch) -> None:
    reset_rate_limits()
    monkeypatch.setattr(main, "vector_store", object())
    monkeypatch.setattr(main, "generate_answer", lambda _q, _s: "ok")

    with TestClient(main.app) as client:
        for _ in range(300):
            response = client.get("/ask", params={"question": "hello"})
            assert response.status_code == 200

        response = client.get("/ask", params={"question": "hello"})
        assert response.status_code == 429
        assert response.json()["error"] == "Rate limit exceeded: 300 per 1 minute"


def test_rebuild_index_from_data_empty_dir_cleans_files(monkeypatch, tmp_path: Path) -> None:
    index_path = tmp_path / "faiss.index"
    metadata_path = tmp_path / "faiss_metadata.json"
    index_path.write_text("old", encoding="utf-8")
    metadata_path.write_text("old", encoding="utf-8")

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "INDEX_PATH", index_path)
    monkeypatch.setattr(main, "METADATA_PATH", metadata_path)

    summary = main._rebuild_index_from_data()

    assert summary == {"files": 0, "chunks": 0}
    assert main.vector_store is None
    assert not index_path.exists()
    assert not metadata_path.exists()


def test_rebuild_index_from_data_indexes_supported_files(monkeypatch, tmp_path: Path) -> None:
    index_path = tmp_path / "faiss.index"
    metadata_path = tmp_path / "faiss_metadata.json"

    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "ignore.json").write_text("x", encoding="utf-8")

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "INDEX_PATH", index_path)
    monkeypatch.setattr(main, "METADATA_PATH", metadata_path)
    monkeypatch.setattr(main, "prepare_chunks", lambda text, **_kwargs: [text, "extra"])
    monkeypatch.setattr(main, "embed_text", lambda chunks: [[0.1, 0.2] for _ in chunks])

    summary = main._rebuild_index_from_data()

    assert summary == {"files": 1, "chunks": 2}
    assert main.vector_store is not None
    assert index_path.exists()
    assert metadata_path.exists()


@pytest.mark.anyio
async def test_list_documents_reports_files_and_chunk_count(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "guide.pdf").write_text("pdf", encoding="utf-8")
    (tmp_path / "c.json").write_text("c", encoding="utf-8")

    class DummyStore:
        metadata = [{"id": 1}, {"id": 2}, {"id": 3}]

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "vector_store", DummyStore())
    monkeypatch.setattr(main, "list_persisted_documents", async_empty_list_persisted_documents)

    payload = await main.list_documents(make_request("/admin/documents"))

    assert payload["documents"] == ["a.txt", "b.md", "guide.pdf"]
    assert payload["indexed_chunks"] == 3


@pytest.mark.anyio
async def test_list_documents_with_no_vector_store(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "vector_store", None)
    monkeypatch.setattr(main, "list_persisted_documents", async_empty_list_persisted_documents)

    payload = await main.list_documents(make_request("/admin/documents"))

    assert payload["documents"] == ["a.txt"]
    assert payload["indexed_chunks"] == 0


def test_admin_endpoint_returns_429_after_limit(monkeypatch, tmp_path: Path) -> None:
    reset_rate_limits()
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main.settings, "admin_api_key", "secret")
    monkeypatch.setattr(main, "ADMIN_API_KEY", "secret")
    monkeypatch.setattr(main, "list_persisted_documents", async_empty_list_persisted_documents)

    with TestClient(main.app) as client:
        headers = {"X-Admin-Key": "secret"}
        for _ in range(120):
            response = client.get("/admin/documents", headers=headers)
            assert response.status_code == 200

        response = client.get("/admin/documents", headers=headers)
        assert response.status_code == 429
        assert response.json()["error"] == "Rate limit exceeded: 120 per 1 minute"


def test_load_existing_index_sets_vector_store(monkeypatch, tmp_path: Path) -> None:
    index_path = tmp_path / "faiss.index"
    metadata_path = tmp_path / "faiss_metadata.json"
    index_path.write_text("x", encoding="utf-8")
    metadata_path.write_text("y", encoding="utf-8")

    sentinel = object()
    monkeypatch.setattr(main, "INDEX_PATH", index_path)
    monkeypatch.setattr(main, "METADATA_PATH", metadata_path)
    monkeypatch.setattr(main.VectorStore, "load", lambda *_args: sentinel)

    main._load_existing_index()

    assert main.vector_store is sentinel


@pytest.mark.anyio
async def test_on_startup_creates_data_dir_and_loads_index(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    called = {"load": False}

    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "_load_existing_index", lambda: called.__setitem__("load", True))

    await main.on_startup()

    assert data_dir.exists()
    assert called["load"] is True


def test_rebuild_index_returns_zero_chunks_when_chunking_returns_none(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "notes.txt").write_text("content", encoding="utf-8")

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "INDEX_PATH", tmp_path / "faiss.index")
    monkeypatch.setattr(main, "METADATA_PATH", tmp_path / "faiss_metadata.json")
    monkeypatch.setattr(main, "prepare_chunks", lambda _text, **_kwargs: [])

    summary = main._rebuild_index_from_data()

    assert summary == {"files": 1, "chunks": 0}
    assert main.vector_store is None


def test_rebuild_index_returns_zero_chunks_when_embeddings_empty(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "notes.txt").write_text("content", encoding="utf-8")

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "INDEX_PATH", tmp_path / "faiss.index")
    monkeypatch.setattr(main, "METADATA_PATH", tmp_path / "faiss_metadata.json")
    monkeypatch.setattr(main, "prepare_chunks", lambda _text, **_kwargs: ["chunk"])
    monkeypatch.setattr(main, "embed_text", lambda _chunks: [])

    summary = main._rebuild_index_from_data()

    assert summary == {"files": 1, "chunks": 0}
    assert main.vector_store is None


def make_upload(filename: str, payload: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(payload))


@pytest.mark.anyio
async def test_upload_documents_rejects_unsupported_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "_persist_index_state", async_noop)

    with pytest.raises(HTTPException, match="Unsupported file type"):
        await main.upload_documents(
            request=make_request("/admin/documents"),
            files=[make_upload("bad.docx", b"x")],
            _=None,
        )


def test_read_document_uses_pdf_reader(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF")

    monkeypatch.setattr(main, "_read_pdf_file", lambda path: f"pdf:{path.name}")

    assert main._read_document(pdf_path) == "pdf:doc.pdf"


@pytest.mark.anyio
async def test_upload_documents_accepts_pdf(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    monkeypatch.setattr(main.settings, "max_upload_bytes", 100)
    monkeypatch.setattr(main, "_rebuild_index_from_data", lambda: {"files": 1, "chunks": 1})
    monkeypatch.setattr(main, "_persist_index_state", async_noop)

    payload = await main.upload_documents(
        request=make_request("/admin/documents"),
        files=[make_upload("doc.pdf", b"%PDF-1.4")],
        _=None,
    )

    assert payload == {"uploaded": ["doc.pdf"], "reindexed": {"files": 1, "chunks": 1}}
    assert (tmp_path / "doc.pdf").read_bytes() == b"%PDF-1.4"


@pytest.mark.anyio
async def test_upload_documents_rejects_large_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 3)
    monkeypatch.setattr(main.settings, "max_upload_bytes", 3)
    monkeypatch.setattr(main, "_persist_index_state", async_noop)

    with pytest.raises(HTTPException, match="File too large"):
        await main.upload_documents(
            request=make_request("/admin/documents"),
            files=[make_upload("ok.txt", b"1234")],
            _=None,
        )


@pytest.mark.anyio
async def test_upload_documents_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    monkeypatch.setattr(main.settings, "max_upload_bytes", 100)
    monkeypatch.setattr(main, "_rebuild_index_from_data", lambda: {"files": 1, "chunks": 1})
    monkeypatch.setattr(main, "_persist_index_state", async_noop)

    payload = await main.upload_documents(
        request=make_request("/admin/documents"),
        files=[make_upload("ok.txt", b"hello")],
        _=None,
    )

    assert payload == {"uploaded": ["ok.txt"], "reindexed": {"files": 1, "chunks": 1}}
    assert (tmp_path / "ok.txt").read_bytes() == b"hello"


@pytest.mark.anyio
async def test_upload_documents_reports_missing_openai_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    monkeypatch.setattr(main.settings, "max_upload_bytes", 100)
    monkeypatch.setattr(main, "_persist_index_state", async_noop)

    def fail_rebuild() -> dict:
        raise RuntimeError("OPENAI_API_KEY is not set")

    monkeypatch.setattr(main, "_rebuild_index_from_data", fail_rebuild)

    with pytest.raises(HTTPException, match="OPENAI_API_KEY is not configured"):
        await main.upload_documents(
            request=make_request("/admin/documents"),
            files=[make_upload("ok.txt", b"hello")],
            _=None,
        )


@pytest.mark.anyio
async def test_upload_documents_reports_openai_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    monkeypatch.setattr(main.settings, "max_upload_bytes", 100)
    monkeypatch.setattr(main, "_persist_index_state", async_noop)

    def fail_rebuild() -> dict:
        raise OpenAIError("boom")

    monkeypatch.setattr(main, "_rebuild_index_from_data", fail_rebuild)

    with pytest.raises(HTTPException, match="Document indexing failed while calling OpenAI"):
        await main.upload_documents(
            request=make_request("/admin/documents"),
            files=[make_upload("ok.txt", b"hello")],
            _=None,
        )


@pytest.mark.anyio
async def test_list_documents_uses_persisted_rows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)

    async def async_persisted_documents() -> list[dict[str, int | str]]:
        return [
            {
                "filename": "faq.txt",
                "extension": ".txt",
                "size_bytes": 42,
                "indexed_chunks": 3,
            },
            {
                "filename": "guide.pdf",
                "extension": ".pdf",
                "size_bytes": 100,
                "indexed_chunks": 5,
            },
        ]

    monkeypatch.setattr(main, "list_persisted_documents", async_persisted_documents)

    payload = await main.list_documents(make_request("/admin/documents"))

    assert payload == {
        "documents": ["faq.txt", "guide.pdf"],
        "indexed_chunks": 8,
    }


def test_indexed_chunks_by_source_counts_only_string_sources(monkeypatch) -> None:
    class DummyStore:
        metadata = [
            {"source": "a.txt"},
            {"source": "a.txt"},
            {"source": "b.txt"},
            {"source": 123},
            {},
        ]

    monkeypatch.setattr(main, "vector_store", DummyStore())

    assert main._indexed_chunks_by_source() == {"a.txt": 2, "b.txt": 1}


@pytest.mark.anyio
async def test_persist_index_state_writes_documents_and_run(monkeypatch, tmp_path: Path) -> None:
    class DummyStore:
        metadata = [{"source": "a.txt"}, {"source": "a.txt"}, {"source": "b.md"}]

    captured: dict[str, object] = {}
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "vector_store", DummyStore())

    async def capture_sync_documents(data_dir, allowed_extensions, indexed_chunks_by_source):
        captured.update(
            {
                "data_dir": data_dir,
                "allowed": allowed_extensions,
                "counts": indexed_chunks_by_source,
            }
        )

    async def capture_record_ingestion_run(**kwargs):
        captured.update({"run": kwargs})

    monkeypatch.setattr(main, "sync_documents_from_disk", capture_sync_documents)
    monkeypatch.setattr(main, "record_ingestion_run", capture_record_ingestion_run)

    await main._persist_index_state({"files": 2, "chunks": 3}, status="success")

    assert captured["data_dir"] == tmp_path
    assert captured["counts"] == {"a.txt": 2, "b.md": 1}
    assert captured["run"] == {
        "files_count": 2,
        "chunks_count": 3,
        "status": "success",
        "error_message": None,
    }


def test_read_pdf_file_adds_page_markers(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF")

    class DummyPage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class DummyReader:
        def __init__(self, _path: str):
            self.pages = [DummyPage("Page one"), DummyPage(""), DummyPage("Page three")]

    monkeypatch.setattr(main, "PdfReader", DummyReader)

    text = main._read_pdf_file(pdf_path)

    assert text == "[Page 1]\nPage one\n\n[Page 3]\nPage three"


@pytest.mark.anyio
async def test_reindex_documents_persists_failure_then_raises(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fail_rebuild() -> dict:
        raise RuntimeError("x")

    async def capture_persist_index_state(summary, status, error_message=None):
        captured.update({"summary": summary, "status": status, "error": error_message})

    monkeypatch.setattr(main, "_rebuild_index_from_data", fail_rebuild)
    monkeypatch.setattr(main, "_persist_index_state", capture_persist_index_state)

    with pytest.raises(RuntimeError):
        await main.reindex_documents(make_request("/admin/reindex"))

    assert captured["status"] == "failed"
    assert captured["summary"] == {"files": 0, "chunks": 0}
