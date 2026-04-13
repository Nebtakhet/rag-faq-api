from pathlib import Path
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from openai import OpenAIError
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


def reset_rate_limits() -> None:
    main.limiter._storage.reset()


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


def test_list_documents_reports_files_and_chunk_count(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "guide.pdf").write_text("pdf", encoding="utf-8")
    (tmp_path / "c.json").write_text("c", encoding="utf-8")

    class DummyStore:
        metadata = [{"id": 1}, {"id": 2}, {"id": 3}]

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "vector_store", DummyStore())
    monkeypatch.setattr(main, "list_persisted_documents", lambda: [])

    payload = main.list_documents(make_request("/admin/documents"))

    assert payload["documents"] == ["a.txt", "b.md", "guide.pdf"]
    assert payload["indexed_chunks"] == 3


def test_list_documents_with_no_vector_store(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "vector_store", None)
    monkeypatch.setattr(main, "list_persisted_documents", lambda: [])

    payload = main.list_documents(make_request("/admin/documents"))

    assert payload["documents"] == ["a.txt"]
    assert payload["indexed_chunks"] == 0


def test_admin_endpoint_returns_429_after_limit(monkeypatch, tmp_path: Path) -> None:
    reset_rate_limits()
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main.settings, "admin_api_key", "secret")
    monkeypatch.setattr(main, "ADMIN_API_KEY", "secret")
    monkeypatch.setattr(main, "list_persisted_documents", lambda: [])

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


def test_on_startup_creates_data_dir_and_loads_index(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    called = {"load": False}

    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main, "_load_existing_index", lambda: called.__setitem__("load", True))

    main.on_startup()

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
    monkeypatch.setattr(main, "_persist_index_state", lambda *_args, **_kwargs: None)

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
    monkeypatch.setattr(main, "_persist_index_state", lambda *_args, **_kwargs: None)

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
    monkeypatch.setattr(main, "_persist_index_state", lambda *_args, **_kwargs: None)

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
    monkeypatch.setattr(main, "_persist_index_state", lambda *_args, **_kwargs: None)

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
    monkeypatch.setattr(main, "_persist_index_state", lambda *_args, **_kwargs: None)

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
    monkeypatch.setattr(main, "_persist_index_state", lambda *_args, **_kwargs: None)

    def fail_rebuild() -> dict:
        raise OpenAIError("boom")

    monkeypatch.setattr(main, "_rebuild_index_from_data", fail_rebuild)

    with pytest.raises(HTTPException, match="Document indexing failed while calling OpenAI"):
        await main.upload_documents(
            request=make_request("/admin/documents"),
            files=[make_upload("ok.txt", b"hello")],
            _=None,
        )


def test_list_documents_uses_persisted_rows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        main,
        "list_persisted_documents",
        lambda: [
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
        ],
    )

    payload = main.list_documents(make_request("/admin/documents"))

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


def test_persist_index_state_writes_documents_and_run(monkeypatch, tmp_path: Path) -> None:
    class DummyStore:
        metadata = [{"source": "a.txt"}, {"source": "a.txt"}, {"source": "b.md"}]

    captured: dict[str, object] = {}
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "vector_store", DummyStore())
    monkeypatch.setattr(
        main,
        "sync_documents_from_disk",
        lambda data_dir, allowed_extensions, indexed_chunks_by_source: captured.update(
            {
                "data_dir": data_dir,
                "allowed": allowed_extensions,
                "counts": indexed_chunks_by_source,
            }
        ),
    )
    monkeypatch.setattr(
        main,
        "record_ingestion_run",
        lambda **kwargs: captured.update({"run": kwargs}),
    )

    main._persist_index_state({"files": 2, "chunks": 3}, status="success")

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


def test_reindex_documents_persists_failure_then_raises(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        main, "_rebuild_index_from_data", lambda: (_ for _ in ()).throw(RuntimeError("x"))
    )
    monkeypatch.setattr(
        main,
        "_persist_index_state",
        lambda summary, status, error_message=None: captured.update(
            {"summary": summary, "status": status, "error": error_message}
        ),
    )

    with pytest.raises(RuntimeError):
        main.reindex_documents(make_request("/admin/reindex"))

    assert captured["status"] == "failed"
    assert captured["summary"] == {"files": 0, "chunks": 0}
