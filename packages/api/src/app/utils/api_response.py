"""Standard response envelope used by every router.

The ``{data, success, error}`` envelope is the canonical response shape
for endpoints that want a single, type-safe contract regardless of
the HTTP status. Routers that already declare a typed Pydantic
``response_model=`` do not need to call this helper — FastAPI handles
serialisation directly.

Used by the indexing endpoints (and any future endpoint that wants a
uniform envelope shape). Routers that prefer a typed Pydantic envelope
model can keep using that pattern.
"""

from __future__ import annotations

from typing import Any


def api_response(
    data: Any = None,
    *,
    success: bool = True,
    error: str | None = None,
) -> dict[str, Any]:
    """Return the standard ``{data, success, error}`` envelope.

    Args:
        data: The payload. ``None`` is a valid value (e.g. an empty
            list serialised explicitly). Defaults to ``None``.
        success: ``True`` when the operation succeeded. The frontend
            renders the error branch when this is ``False``.
        error: Human-readable error string. ``None`` on success.

    Returns:
        ``{"data": data, "success": success, "error": error}``.
    """
    return {"data": data, "success": success, "error": error}


__all__ = ["api_response"]
