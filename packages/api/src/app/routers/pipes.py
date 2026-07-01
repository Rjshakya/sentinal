"""WorkOS Pipes routes: list connections, initiate OAuth connect (302)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.workos import (
    authorize_data_integration,
    list_user_data_providers,
)

router = APIRouter(prefix="/pipes", tags=["pipes"])


class ConnectionOut(BaseModel):
    slug: str
    name: str
    connected: bool
    connected_at: str | None


@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(request: Request) -> list[ConnectionOut]:
    providers = await list_user_data_providers(request.state.user_id)
    return [
        ConnectionOut(
            slug=p.slug,
            name=p.name,
            connected=(
                p.connected_account is not None
                and p.connected_account.state == "connected"
            ),
            connected_at=(
                p.connected_account.created_at
                if p.connected_account is not None
                and p.connected_account.state == "connected"
                else None
            ),
        )
        for p in providers
    ]


@router.get("/connections/{slug}/authorize")
async def authorize_connection(request: Request, slug: str) -> RedirectResponse:
    return_to = settings.frontend_url.rstrip("/") + "/dashboard"
    authorize_url = await authorize_data_integration(
        slug=slug,
        user_id=request.state.user_id,
        return_to=return_to,
    )
    return RedirectResponse(url=authorize_url, status_code=302)
