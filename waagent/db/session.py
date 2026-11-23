from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    if database_url.startswith("sqlite") and ":memory:" in database_url:
        # Tests: one shared in-memory database across connections.
        from sqlalchemy.pool import StaticPool

        _engine = create_async_engine(
            database_url, poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    else:
        _engine = create_async_engine(database_url, pool_pre_ping=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Database engine not initialised")
    async with _sessionmaker() as session:
        yield session
