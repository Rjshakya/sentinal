import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# psycopg async mode does not work with Windows' default ProactorEventLoop.
# Force the SelectorEventLoop before any DBOS/SQLAlchemy async imports run.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dbos import DBOS, DBOSConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import create_db_and_tables
from app.core.logging import configure_structured_logging
from app.core.middleware import AuthMiddleware
from app.routers import ai, auth, github, health, users, webhooks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

configure_structured_logging()


def _dbos_config() -> DBOSConfig:
    """Build DBOS config from application settings.

    DBOS shares the same Postgres database as the application. The URL
    is stripped of the asyncpg driver suffix because DBOS creates its
    own SQLAlchemy engine.
    """
    db_url = settings.database_url.replace("+asyncpg", "")
    return {
        "name": "sentinel",
        "system_database_url": db_url,
        # "application_database_url": db_url,
        # "executor_id": settings.dbos_executor_id,
        # "run_admin_server": True,
        # "admin_port": 3001,
    }


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await create_db_and_tables()
    DBOS(config=_dbos_config())
    DBOS.launch()
    try:
        yield
    finally:
        DBOS.destroy()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ai-code-review API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(AuthMiddleware)

    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(github.router, prefix=settings.api_prefix)
    app.include_router(ai.router, prefix=settings.api_prefix)
    app.include_router(users.router, prefix=settings.api_prefix)
    app.include_router(webhooks.router, prefix=settings.api_prefix)

    return app


app = create_app()
