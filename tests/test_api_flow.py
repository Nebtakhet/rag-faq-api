from pathlib import Path

from fastapi.testclient import TestClient

from app import main


def test_upload_reindex_and_ask_flow(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    index_path = tmp_path / "faiss.index"
    metadata_path = tmp_path / "faiss_metadata.json"
    database_path = tmp_path / "app.db"

    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "INDEX_PATH", index_path)
    monkeypatch.setattr(main, "METADATA_PATH", metadata_path)
    monkeypatch.setattr(main, "vector_store", None)
    monkeypatch.setattr(main.settings, "sqlalchemy_database_uri", f"sqlite:///{database_path}")
    monkeypatch.setattr(main.settings, "admin_api_key", "secret")

    def fake_prepare_chunks(text: str, **_kwargs) -> list[str]:
        return [line for line in text.splitlines() if line]

    def fake_embed_text(chunks: list[str]) -> list[list[float]]:
        return [[float(index + 1), 0.0] for index, _ in enumerate(chunks)]

    def fake_generate_answer(question: str, store) -> str:
        return f"{question} | chunks={len(store.metadata)} | first={store.metadata[0]['text']}"

    monkeypatch.setattr(main, "prepare_chunks", fake_prepare_chunks)
    monkeypatch.setattr(main, "embed_text", fake_embed_text)
    monkeypatch.setattr(main, "generate_answer", fake_generate_answer)

    with TestClient(main.app) as client:
        upload_response = client.post(
            "/admin/documents",
            headers={"X-Admin-Key": "secret"},
            files=[("files", ("faq.txt", b"alpha\nbeta\n", "text/plain"))],
        )
        assert upload_response.status_code == 200
        assert upload_response.json() == {
            "uploaded": ["faq.txt"],
            "reindexed": {"files": 1, "chunks": 2},
        }

        reindex_response = client.post("/admin/reindex", headers={"X-Admin-Key": "secret"})
        assert reindex_response.status_code == 200
        assert reindex_response.json() == {"reindexed": {"files": 1, "chunks": 2}}

        documents_response = client.get("/admin/documents", headers={"X-Admin-Key": "secret"})
        assert documents_response.status_code == 200
        assert documents_response.json() == {
            "documents": ["faq.txt"],
            "indexed_chunks": 2,
        }

        ask_response = client.get("/ask", params={"question": "What is inside?"})
        assert ask_response.status_code == 200
        assert ask_response.json() == {"answer": "What is inside? | chunks=2 | first=alpha"}

    assert (data_dir / "faq.txt").read_text(encoding="utf-8") == "alpha\nbeta\n"
    assert index_path.exists()
    assert metadata_path.exists()
