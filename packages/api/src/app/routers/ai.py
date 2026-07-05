"""AI routes: code indexing kickoff.

The actual indexing work runs in a background task. The handler
acknowledges the request immediately and returns a small payload so
the UI can show a toast.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.core.daytona import get_daytona
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
    sandbox_provider = get_daytona()

    asyncio.create_task(
        indexing_pipeline(
            user_id=user_id,
            repos=payload.repos,
            sandbox_provider=sandbox_provider,
        )
    )

    return IndexingAck(
        accepted=len(payload.repos),
        repos=payload.repos,
        message="Indexing started in background",
    )
