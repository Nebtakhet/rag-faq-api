from pathlib import Path

import pytest

from app.db import persistence


@pytest.mark.anyio
async def test_sync_documents_and_list(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    (data_dir / "a.txt").write_text("hello", encoding="utf-8")
    (data_dir / "b.md").write_text("world", encoding="utf-8")
    (data_dir / "ignore.json").write_text("x", encoding="utf-8")

    persistence.configure_database(f"sqlite:///{db_path}")
    await persistence.init_db()

    await persistence.sync_documents_from_disk(
        data_dir=data_dir,
        allowed_extensions={".txt", ".md", ".pdf"},
        indexed_chunks_by_source={"a.txt": 2, "b.md": 1},
    )

    rows = await persistence.list_persisted_documents()

    assert [row["filename"] for row in rows] == ["a.txt", "b.md"]
    assert sum(int(row["indexed_chunks"]) for row in rows) == 3


@pytest.mark.anyio
async def test_record_ingestion_run_and_prune_removed_docs(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    (data_dir / "keep.txt").write_text("keep", encoding="utf-8")
    (data_dir / "remove.txt").write_text("remove", encoding="utf-8")

    persistence.configure_database(f"sqlite:///{db_path}")
    await persistence.init_db()

    await persistence.sync_documents_from_disk(
        data_dir=data_dir,
        allowed_extensions={".txt"},
        indexed_chunks_by_source={"keep.txt": 1, "remove.txt": 2},
    )

    (data_dir / "remove.txt").unlink()
    await persistence.sync_documents_from_disk(
        data_dir=data_dir,
        allowed_extensions={".txt"},
        indexed_chunks_by_source={"keep.txt": 3},
    )

    await persistence.record_ingestion_run(files_count=1, chunks_count=3, status="success")
    await persistence.record_ingestion_run(
        files_count=0,
        chunks_count=0,
        status="failed",
        error_message="boom",
    )

    rows = await persistence.list_persisted_documents()
    runs = await persistence.list_ingestion_runs(limit=2)

    assert rows == [
        {
            "filename": "keep.txt",
            "extension": ".txt",
            "size_bytes": 4,
            "indexed_chunks": 3,
        }
    ]
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_message"] == "boom"
    assert runs[1]["status"] == "success"
