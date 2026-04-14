from pathlib import Path

from sqlalchemy import select
from app.db import session as db_session
from app.db.base import Base
from app.db.models import DocumentRecord, IngestionRun

configure_database = db_session.configure_database


async def init_db() -> None:
    async with db_session.get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def sync_documents_from_disk(
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
    await record_documents(records)


async def record_documents(records: list[dict[str, str | int]]) -> None:
    async with db_session.get_session_factory()() as session:
        result = await session.execute(select(DocumentRecord).order_by(DocumentRecord.filename))
        existing = {row.filename: row for row in result.scalars().all()}
        current_names = {str(record["filename"]) for record in records}

        for filename, existing_row in existing.items():
            if filename not in current_names:
                await session.delete(existing_row)

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

        await session.commit()


async def record_ingestion_run(
    files_count: int,
    chunks_count: int,
    status: str,
    error_message: str | None = None,
) -> None:
    async with db_session.get_session_factory()() as session:
        session.add(
            IngestionRun(
                files_count=files_count,
                chunks_count=chunks_count,
                status=status,
                error_message=error_message,
            )
        )
        await session.commit()


async def list_persisted_documents() -> list[dict[str, int | str]]:
    async with db_session.get_session_factory()() as session:
        result = await session.execute(select(DocumentRecord).order_by(DocumentRecord.filename))
        rows = result.scalars().all()
        return [
            {
                "filename": row.filename,
                "extension": row.extension,
                "size_bytes": row.size_bytes,
                "indexed_chunks": row.indexed_chunks,
            }
            for row in rows
        ]


async def list_ingestion_runs(limit: int = 50) -> list[dict[str, int | str | None]]:
    async with db_session.get_session_factory()() as session:
        result = await session.execute(
            select(IngestionRun).order_by(IngestionRun.id.desc()).limit(limit)
        )
        rows = result.scalars().all()
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
