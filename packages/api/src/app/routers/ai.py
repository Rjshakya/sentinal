"""AI routes: code indexing kickoff and code search.

Indexing runs in a background task; the handler acknowledges the
request immediately and returns a small payload so the UI can show a
toast. Search is a synchronous call: the user is actively waiting on
the result, and we want to surface the parsed chunk list in one
round-trip.

Both handlers are provider-agnostic: they build a :class:`SandboxSpec`
from current settings (via :func:`build_default_spec`) and hand it to
the underlying service. The service never sees a concrete provider.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.sandbox import build_default_spec
from app.schemas.indexing import IndexingAck, IndexingRequest
from app.schemas.search import CodeSearchRequest
from app.services.indexing import indexing_pipeline
from app.services.retrieval import retrieve_code_chunks

log = logging.getLogger(__name__)

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
    spec = build_default_spec("e2b")

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


@router.post("/code/search")
async def code_search(
    payload: CodeSearchRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    user_id = request.state.user_id

    if not settings.embeddings_configured:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured on the server.",
        )

    spec = build_default_spec("e2b")

    raw = await retrieve_code_chunks(
        query=payload.query,
        repo_name=payload.repo_name,
        repo_id=payload.repo_id,
        user_id=user_id,
        limit=payload.limit,
        spec=spec,
        session=session,
    )

    if raw is None:
        raise HTTPException(
            status_code=502,
            detail="Code search failed (no output from sandbox)",
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("search.py emitted non-JSON stdout: %r", raw[:200])
        raise HTTPException(
            status_code=502,
            detail=f"Code search returned invalid JSON: {exc!s}",
        ) from exc

    return JSONResponse(content=parsed)
