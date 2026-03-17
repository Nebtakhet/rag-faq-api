from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.db.models import DocumentRecord, IngestionRun

DEFAULT_DB_URL = "sqlite:///./app.db"

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_database_url() -> str:
    return settings.sqlalchemy_database_uri or DEFAULT_DB_URL


def configure_database(database_url: str | None = None) -> None:
    global _engine, _SessionLocal
    _engine = create_engine(database_url or get_database_url(), future=True)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    if _engine is None:
        configure_database()
    assert _engine is not None
    Base.metadata.create_all(bind=_engine)


def _get_session() -> Session:
    if _SessionLocal is None:
        configure_database()
    assert _SessionLocal is not None
    return _SessionLocal()


def sync_documents_from_disk(
    data_dir: Path,
    allowed_extensions: set[str],
    indexed_chunks_by_source: dict[str, int],
) -> None:
    files = [
        path
        for path in data_dir.iterdir()
        if path.is_file() and path.suffix.lower() in allowed_extensions
    ]
    records: list[dict[str, str | int]] = [
        {
            "filename": path.name,
            "extension": path.suffix.lower(),
            "size_bytes": path.stat().st_size,
            "indexed_chunks": indexed_chunks_by_source.get(path.name, 0),
        }
        for path in files
    ]
    record_documents(records)


def record_documents(records: list[dict[str, str | int]]) -> None:
    with _get_session() as session:
        existing = {
            row.filename: row
            for row in session.scalars(
                select(DocumentRecord).order_by(DocumentRecord.filename)
            ).all()
        }
        current_names = {str(record["filename"]) for record in records}

        for filename, existing_row in existing.items():
            if filename not in current_names:
                session.delete(existing_row)

        for record in records:
            filename = str(record["filename"])
            row = existing.get(filename)
            if row is None:
                row = DocumentRecord(
                    filename=filename,
                    extension=str(record["extension"]),
                    size_bytes=int(record["size_bytes"]),
                    indexed_chunks=int(record.get("indexed_chunks", 0)),
                )
                session.add(row)
                continue

            row.extension = str(record["extension"])
            row.size_bytes = int(record["size_bytes"])
            row.indexed_chunks = int(record.get("indexed_chunks", 0))

        session.commit()


def record_ingestion_run(
    files_count: int,
    chunks_count: int,
    status: str,
    error_message: str | None = None,
) -> None:
    with _get_session() as session:
        session.add(
            IngestionRun(
                files_count=files_count,
                chunks_count=chunks_count,
                status=status,
                error_message=error_message,
            )
        )
        session.commit()


def list_persisted_documents() -> list[dict[str, int | str]]:
    with _get_session() as session:
        rows = session.scalars(select(DocumentRecord).order_by(DocumentRecord.filename)).all()
        return [
            {
                "filename": row.filename,
                "extension": row.extension,
                "size_bytes": row.size_bytes,
                "indexed_chunks": row.indexed_chunks,
            }
            for row in rows
        ]


def list_ingestion_runs(limit: int = 50) -> list[dict[str, int | str | None]]:
    with _get_session() as session:
        rows = session.scalars(
            select(IngestionRun).order_by(IngestionRun.id.desc()).limit(limit)
        ).all()
        return [
            {
                "id": row.id,
                "files_count": row.files_count,
                "chunks_count": row.chunks_count,
                "status": row.status,
                "error_message": row.error_message,
            }
            for row in rows
        ]
