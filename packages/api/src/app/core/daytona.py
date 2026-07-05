"""Daytona SDK wrapper.

One ``AsyncDaytona`` per process. Configured from ``Settings``; raising
if Daytona is not configured returns a clear 503 from any caller that
needs it.
"""

from __future__ import annotations

from daytona import AsyncDaytona, DaytonaConfig

from app.core.config import settings

_client: AsyncDaytona | None = None


def _get_client() -> AsyncDaytona:
    global _client
    if _client is None:
        if not settings.daytona_configured:
            raise RuntimeError("Daytona is not configured. Set DAYTONA_API_KEY in .env")
        _client = AsyncDaytona(
            DaytonaConfig(
                api_key=settings.daytona_api_key,
                # api_url=settings.daytona_api_url or None,
            )
        )
    return _client


def get_daytona() -> AsyncDaytona:
    """Return the process-wide Daytona client (lazy)."""
    return _get_client()


async def close_daytona() -> None:
    """Close the client. Call from FastAPI shutdown if you wire one up."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
