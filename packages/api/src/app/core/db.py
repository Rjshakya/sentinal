import asyncio
import selectors

from dbos import AsyncSQLAlchemyDatasource
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# DBOS datasource for durable, exactly-once transactions inside DBOS workflows.
# Created at module import time so the @dbos_datasource.transaction() decorator
# is available when workflow modules are imported.
# DBOS uses psycopg, so we strip the +asyncpg driver suffix from the URL.
_DBOS_DATABASE_URL = settings.database_url.replace("+asyncpg", "")


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


dbos_datasource: AsyncSQLAlchemyDatasource = asyncio.run(
    AsyncSQLAlchemyDatasource.create(
        _DBOS_DATABASE_URL, engine_kwargs={"poolclass": NullPool}
    ),
    loop_factory=_selector_loop_factory,
)


async def get_session():
    async with async_session_maker() as session:
        yield session


async def create_db_and_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
