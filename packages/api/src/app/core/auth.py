"""FastAPI dependencies for authenticated routes."""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.workos import load_session


class Session(BaseModel):
    user_id: str
    user_name: str | None
    email: str
    profile_picture: str | None
    session_id: str
    external_id: str | None
    created_at: str | None
    updated_at: str | None


async def get_current_session(request: Request) -> Session:

    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        print("auth: missing session cookie")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    session = load_session(cookie)
    if session is None:
        print("auth: load_sealed_session returned None")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    result = session.authenticate()

    if not result.authenticated:
        print("auth: result.authenticated is False:", getattr(result, "reason", None))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    user = getattr(result, "user", None) or {}
    user_id = user.get("id")
    user_name = user.get("first_name")
    email = user.get("email")
    profile_picture = user.get("profile_picture_url")
    external_id = user.get("external_id")
    session_id = getattr(result, "session_id", None)
    created_at = user.get("created_at")
    updated_at = user.get("updated_at")

    if not user_id or not email:
        print("auth: missing user_id or email in session payload", user)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if session_id is None:
        print("auth: missing session_id in JWT claims")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return Session(
        user_id=user_id,
        user_name=user_name,
        email=email,
        profile_picture=profile_picture,
        session_id=session_id,
        external_id=external_id,
        created_at=created_at,
        updated_at=updated_at,
    )
