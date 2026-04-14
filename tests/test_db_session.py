from typing import Any

from app.db import session as db_session


def test_sqlite_uri_converts_to_aiosqlite() -> None:
    assert db_session.to_async_database_uri("sqlite:///./app.db") == "sqlite+aiosqlite:///./app.db"


def test_sqlite_async_uri_is_unchanged() -> None:
    uri = "sqlite+aiosqlite:///./app.db"
    assert db_session.to_async_database_uri(uri) == uri


def test_postgres_short_scheme_converts_to_asyncpg() -> None:
    uri = "postgres://user:pass@localhost:5432/db"
    assert (
        db_session.to_async_database_uri(uri) == "postgresql+asyncpg://user:pass@localhost:5432/db"
    )


def test_postgresql_plain_scheme_converts_to_asyncpg() -> None:
    uri = "postgresql://user:pass@localhost:5432/db"
    assert (
        db_session.to_async_database_uri(uri) == "postgresql+asyncpg://user:pass@localhost:5432/db"
    )


def test_postgresql_psycopg2_scheme_converts_to_asyncpg() -> None:
    uri = "postgresql+psycopg2://user:pass@localhost:5432/db"
    assert (
        db_session.to_async_database_uri(uri) == "postgresql+asyncpg://user:pass@localhost:5432/db"
    )


def test_postgresql_asyncpg_scheme_is_unchanged() -> None:
    uri = "postgresql+asyncpg://user:pass@localhost:5432/db"
    assert db_session.to_async_database_uri(uri) == uri


def test_other_uris_are_unchanged() -> None:
    uri = "mysql://user:pass@localhost:3306/db"
    assert db_session.to_async_database_uri(uri) == uri


def test_get_engine_initializes_lazily(monkeypatch) -> None:
    sentinel: Any = object()

    monkeypatch.setattr(db_session, "_engine", None)

    def configure_database() -> None:
        db_session._engine = sentinel

    monkeypatch.setattr(db_session, "configure_database", configure_database)

    assert db_session.get_engine() is sentinel


def test_get_session_factory_initializes_lazily(monkeypatch) -> None:
    sentinel: Any = object()

    monkeypatch.setattr(db_session, "_SessionLocal", None)

    def configure_database() -> None:
        db_session._SessionLocal = sentinel

    monkeypatch.setattr(db_session, "configure_database", configure_database)

    assert db_session.get_session_factory() is sentinel
