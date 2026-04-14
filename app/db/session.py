from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


_engine = None
_SessionLocal = None


def to_async_database_uri(uri: str) -> str:
    if uri.startswith("sqlite://") and not uri.startswith("sqlite+aiosqlite://"):
        return uri.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if uri.startswith("postgres://"):
        return uri.replace("postgres://", "postgresql+asyncpg://", 1)
    if uri.startswith("postgresql+asyncpg://"):
        return uri
    if uri.startswith("postgresql+"):
        scheme = uri.split("://", 1)[0]
        return uri.replace(f"{scheme}://", "postgresql+asyncpg://", 1)
    if uri.startswith("postgresql://"):
        return uri.replace("postgresql://", "postgresql+asyncpg://", 1)
    return uri


def configure_database(database_url: str | None = None) -> None:
    global _engine, _SessionLocal
    _engine = create_async_engine(
        to_async_database_uri(database_url or settings.effective_sqlalchemy_database_uri)
    )
    _SessionLocal = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
    )


def get_engine():
    if _engine is None:
        configure_database()
    assert _engine is not None
    return _engine


def get_session_factory():
    if _SessionLocal is None:
        configure_database()
    assert _SessionLocal is not None
    return _SessionLocal


configure_database()
