import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.core.config import settings
from app.core.db import create_db_and_tables
from app.core.middleware import AuthMiddleware
from app.routers import (
    ai,
    auth,
    github,
    health,
    llm_configs,
    pulls,
    reviews,
    users,
    webhooks,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create tables on local/docker boot; skip on Lambda.

    Mangum runs with ``lifespan="off"`` so this never executes on
    Lambda. The env guard covers Lambda Web Adapter style hosts that
    _do_ run lifespan: deployed envs own schema via Alembic, never
    ``create_all`` at boot.
    """
    import os

    if not os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        await create_db_and_tables()
    try:
        yield
    finally:
        pass


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
    app.include_router(pulls.router, prefix=settings.api_prefix)
    app.include_router(llm_configs.router, prefix=settings.api_prefix)
    app.include_router(webhooks.router, prefix=settings.api_prefix)

    return app


app = create_app()

# AWS Lambda entry point (API Gateway → Mangum → ASGI).
handler = Mangum(app, lifespan="off")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
    )
