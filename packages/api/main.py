import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# psycopg async mode does not work with Windows' default ProactorEventLoop.
# Force the SelectorEventLoop before any DBOS/SQLAlchemy async imports run.
# if sys.platform == "win32":
#     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
#
from dbos import DBOS, DBOSConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import create_db_and_tables, get_dbos_datasource
from app.core.middleware import AuthMiddleware
from app.core.sandbox.e2b import build_e2b_index_template, build_e2b_template
from app.core.telemetry import init_telemetry, instrument_fastapi
from app.routers import (
    ai,
    auth,
    github,
    health,
    indexing,
    llm_configs,
    reviews,
    search,
    users,
    webhooks,
)

# DBOS workflow registration. The webhook receiver now dispatches
# through the github webhook sub-service, whose delegation handlers
# import their adapters lazily (cycle avoidance) — so the workflows
# must be imported here to register their @DBOS.workflow decorated
# entry points before DBOS.launch(). The review workflow (and its
# triggers) live in app.workflows.review; the setup and indexing
# pipelines register through their routers' imports.


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# OpenLLMetry telemetry: the single observability entry point, gated
# on TRACELOOP_BASE_URL / TRACELOOP_API_KEY. It wires traces (via
# Traceloop) and logs (OTLP) through the same endpoint. OpenTelemetry
# instrumentors patch already-imported modules, so this is safe after
# the routers above have imported LangChain / provider packages. The
# FastAPI ASGI instrumentation is attached in create_app() via
# instrument_fastapi.
init_telemetry()


def _dbos_config() -> DBOSConfig:
    """Build DBOS config from application settings.

    DBOS shares the same Postgres database as the application. The URL
    is stripped of the asyncpg driver suffix because DBOS creates its
    own SQLAlchemy engine.
    """
    db_url = settings.dbos_database_url
    return {
        "name": "sentinel",
        "system_database_url": db_url,
        "application_database_url": db_url,
        "executor_id": settings.dbos_executor_id,
        # "run_admin_server": True,
        # "admin_port": 3001,
    }


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await create_db_and_tables()
    DBOS(config=_dbos_config())
    DBOS.launch()
    # await get_dbos_datasource()
    # build_e2b_template()
    # build_e2b_index_template()
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
    app.include_router(reviews.router, prefix=settings.api_prefix)
    app.include_router(llm_configs.router, prefix=settings.api_prefix)
    app.include_router(indexing.router, prefix=settings.api_prefix)
    app.include_router(search.router, prefix=settings.api_prefix)
    app.include_router(webhooks.router, prefix=settings.api_prefix)

    # One OTLP HTTP span per request (skipped when telemetry is
    # unconfigured or TELEMETRY_FASTAPI=false).
    instrument_fastapi(app)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # import uvicorn.loops.asyncio as uvicorn_asyncio_loop
    #
    # if sys.platform == "win32":
    #
    #     def _selector_loop_factory(
    #         use_subprocess: bool = False,
    #     ) -> type[asyncio.AbstractEventLoop]:
    #         return asyncio.SelectorEventLoop
    #
    #     uvicorn_asyncio_loop.asyncio_loop_factory = _selector_loop_factory
    #
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
    )
