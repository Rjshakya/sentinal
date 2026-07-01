"""WorkOS User Management wrapper.

One ``AsyncWorkOSClient`` per process. Sealed session validation is
synchronous (local Fernet decrypt + JWT verify) — no network IO.
Only ``authenticate_with_code`` is async (network call to WorkOS).
"""

from __future__ import annotations

import secrets
from typing import Literal

from workos import AsyncWorkOSClient
from workos.session import AsyncSession, seal_session_from_auth_response
from workos.user_management import AuthenticateResponse

from app.core.config import settings

Provider = Literal["github", "google"]

_client: AsyncWorkOSClient | None = None


def _get_client() -> AsyncWorkOSClient:
    global _client
    if _client is None:
        if not settings.workos_configured:
            raise RuntimeError(
                "WorkOS is not configured. Set WORKOS_API_KEY, "
                "WORKOS_CLIENT_ID, and WORKOS_COOKIE_PASSWORD in .env"
            )
        _client = AsyncWorkOSClient(
            api_key=settings.workos_api_key,
            client_id=settings.workos_client_id,
        )
    return _client


def get_authorization_url(provider: Provider) -> tuple[str, str]:
    """Return ``(url, state)``. Caller 302s the browser to ``url``.

    State is opaque to WorkOS but round-tripped back to the callback so the
    caller can verify the request originated from us.
    """
    state = secrets.token_urlsafe(24)
    url = _get_client().user_management.get_authorization_url(
        provider=provider,
        redirect_uri=settings.workos_redirect_uri,
    )
    return url, state


async def authenticate_code(code: str) -> AuthenticateResponse:
    """Trade the OAuth code for a user + tokens. Async (HTTP call)."""

    return await _get_client().user_management.authenticate_with_code(code=code)


def seal_session(auth_response: AuthenticateResponse):

    sealed_session = seal_session_from_auth_response(
        access_token=auth_response.access_token,
        refresh_token=auth_response.refresh_token,
        user=auth_response.user.to_dict(),
        cookie_password=settings.workos_cookie_password,
    )

    return sealed_session


def load_session(cookie_value: str) -> AsyncSession | None:
    """Load a sealed session from a cookie. Sync (local decrypt).

    Returns ``None`` if the cookie is missing or unreadable.
    """
    if not cookie_value:
        return None
    return _get_client().user_management.load_sealed_session(
        session_data=cookie_value,
        cookie_password=settings.workos_cookie_password,
    )


async def list_user_data_providers(user_id: str):
    providers = await _get_client().pipes.list_user_data_providers(user_id=user_id)
    return providers.data


async def authorize_data_integration(slug: str, user_id: str, return_to: str) -> str:
    response = await _get_client().pipes.authorize_data_integration(
        slug=slug,
        user_id=user_id,
        return_to=return_to,
    )
    return response.url
