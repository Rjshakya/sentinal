from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    # Lambda + Neon (PgBouncer): no client-side pooling. Each invocation
    # opens short sessions and closes them; Neon pools centrally. This
    # avoids connection exhaustion under burst concurrency (default
    # QueuePool 5+10 × N envs) and is also safe for local/docker.
    poolclass=NullPool,
    connect_args={"statement_cache_size": 0},
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_db_and_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
