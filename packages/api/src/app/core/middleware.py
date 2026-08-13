"""Auth middleware: validates the session on protected routes and attaches the
user info to ``request.state`` for downstream handlers.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.auth import get_current_session


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates the session on routes whose path starts with a protected prefix.

    On success, attaches the full session and a few flat fields to ``request.state``.
    On failure, returns 401.

    ``BYPASS_PREFIXES`` is the explicit denylist for paths inside a
    protected family that must remain anonymous. The GitHub install
    setup callback sits under ``/api/github`` but is called by GitHub
    via a browser redirect, with no session cookie.
    """

    PROTECTED_PREFIXES: tuple[str, ...] = (
        "/api/github",
        "/api/ai",
        "/api/users",
        "/api/llm_config",
        "/api/indexing",
        "/api/search",
    )

    BYPASS_PREFIXES: tuple[str, ...] = ("/api/github/setup",)

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):

        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in self.BYPASS_PREFIXES):
            return await call_next(request)

        if not any(path.startswith(p) for p in self.PROTECTED_PREFIXES):
            return await call_next(request)

        try:
            session = await get_current_session(request)

            request.state.session = session
            request.state.user_id = session.user_id
            request.state.session_id = session.session_id
            request.state.email = session.email
            request.state.user_name = session.user_name
            request.state.profile_picture = session.profile_picture

        except HTTPException:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return await call_next(request)
