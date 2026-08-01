import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk

# psycopg async mode does not work with Windows' default ProactorEventLoop.
# Force the SelectorEventLoop before any DBOS/SQLAlchemy async imports run.
# if sys.platform == "win32":
#     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
#
from dbos import DBOS, DBOSConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.logging import LoggingIntegration

from app.core.config import settings
from app.core.db import create_db_and_tables
from app.core.logging import configure_structured_logging
from app.core.middleware import AuthMiddleware
from app.core.sandbox.e2b import build_e2b_template
from app.routers import ai, auth, github, health, llm_configs, users, webhooks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

configure_structured_logging()
if settings.sentry_configured:
    _sentry_log_level = getattr(
        logging, settings.sentry_log_level.upper(), logging.INFO
    )
    if not isinstance(_sentry_log_level, int):
        _sentry_log_level = logging.INFO
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        send_default_pii=settings.sentry_send_default_pii,
        enable_logs=settings.sentry_enable_logs,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Set profile_session_sample_rate to 1.0 to profile 100%
        # of profile sessions.
        profile_session_sample_rate=settings.sentry_profiles_sample_rate,
        # Set profile_lifecycle to "trace" to automatically
        # run the profiler on when there is an active transaction
        profile_lifecycle="trace",
        integrations=[
            LoggingIntegration(
                level=_sentry_log_level,
                event_level=logging.ERROR,
            ),
        ],
    )
    logging.getLogger(__name__).info(
        "sentry initialised: env=%s log_level=%s",
        settings.sentry_environment,
        settings.sentry_log_level,
    )
else:
    logging.getLogger(__name__).info(
        "sentry not configured (SENTRY_DSN empty); skipping init"
    )


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
    build_e2b_template()
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
    app.include_router(llm_configs.router, prefix=settings.api_prefix)
    app.include_router(webhooks.router, prefix=settings.api_prefix)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    import uvicorn.loops.asyncio as uvicorn_asyncio_loop

    if sys.platform == "win32":

        def _selector_loop_factory(
            use_subprocess: bool = False,
        ) -> type[asyncio.AbstractEventLoop]:
            return asyncio.SelectorEventLoop

        uvicorn_asyncio_loop.asyncio_loop_factory = _selector_loop_factory

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
    )
