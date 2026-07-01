"""AI routes: code indexing stub."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/ai", tags=["ai"])


class IndexingRepo(BaseModel):
    id: int
    full_name: str
    html_url: str


class IndexingRequest(BaseModel):
    repos: list[IndexingRepo]


class IndexingResponse(BaseModel):
    accepted: int


@router.post("/code/indexing", response_model=IndexingResponse)
async def start_code_indexing(payload: IndexingRequest, request: Request) -> IndexingResponse:
    print(
        f"indexing request from {request.state.user_id}: "
        f"{[r.full_name for r in payload.repos]}"
    )
    return IndexingResponse(accepted=len(payload.repos))
