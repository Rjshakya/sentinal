"""AI routes: code indexing kickoff.

The actual indexing work runs in a background task. The handler
acknowledges the request immediately and returns a small payload so
the UI can show a toast.

The handler is provider-agnostic: it builds a :class:`SandboxSpec`
from current settings (via :func:`build_default_spec`) and hands it to
the pipeline. The pipeline never sees a concrete provider.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.core.sandbox import build_default_spec
from app.schemas.indexing import IndexingAck, IndexingRequest
from app.services.indexing import indexing_pipeline

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/code/indexing", response_model=IndexingAck)
async def start_code_indexing(
    payload: IndexingRequest,
    request: Request,
) -> IndexingAck:
    if not payload.repos:
        raise HTTPException(
            status_code=400, detail="`repos` must contain at least one item"
        )

    user_id = request.state.user_id
    spec = build_default_spec()

    asyncio.create_task(
        indexing_pipeline(
            user_id=user_id,
            repos=payload.repos,
            spec=spec,
        )
    )

    return IndexingAck(
        accepted=len(payload.repos),
        repos=payload.repos,
        message="Indexing started in background",
    )
