"""WorkOS-backed auth routes: login → callback → me → logout."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.auth import Session, get_current_session
from app.core.config import settings
from app.core.workos import (
    Provider,
    authenticate_code,
    get_authorization_url,
    seal_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])

PROVIDERS: dict[str, str] = {
    "google": "GoogleOAuth",
    "github": "GitHubOAuth",
}


@router.get("/login")
def login(provider: Annotated[Provider, Query()]) -> RedirectResponse:

    workos_provider = PROVIDERS.get(provider.lower())

    if workos_provider is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Use one of: {sorted(PROVIDERS)}",
        )

    try:
        url, _ = get_authorization_url(cast(Provider, workos_provider))
        return RedirectResponse(url=url, status_code=302)

    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/callback")
async def callback(
    code: Annotated[str, Query()],
) -> RedirectResponse:

    try:
        auth_response = await authenticate_code(code)

        sealed = seal_session(auth_response)
        if sealed is None:
            raise RuntimeError("Expected sealed_session on AuthenticateResponse")
        # store the session in a cookie
        response = RedirectResponse(url=f"{settings.frontend_url}/dashboard")
        response.set_cookie(
            settings.session_cookie_name,
            sealed,
            secure=True,
            httponly=True,
            samesite="lax",
        )
        return response

    except Exception:
        raise HTTPException(
            detail="Failed to authenticate with code",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout() -> Response:
    """Clear the sealed session cookie."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
    )
    return response


@router.get("/session", response_model=Session)
async def session(req: Request) -> Session:
    return await get_current_session(req)
