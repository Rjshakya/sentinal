"""Search routes.

A single endpoint, protected by :class:`AuthMiddleware` (the path
prefix ``/api/search`` is added to ``AuthMiddleware.PROTECTED_PREFIXES``):

- ``POST /api/search`` — accept ``{owner, repo, query, limit?}`` and
  run a hybrid (FTS + vector) code search against the caller's
  indexed LanceDB dataset for ``owner/repo``. Returns the ranked
  matches, each carrying ``file_name``, ``language``, ``start_line``,
  ``end_line``, ``node_types``, ``content``, and ``_relevance_score``.

The router is a thin shell: it reads ``request.state.user_id`` (set by
``AuthMiddleware``), forwards into :func:`app.services.search.run_search`,
and maps typed :class:`SearchError` subclasses to HTTP via
:func:`app.services.search.errors.search_error_to_http_exception`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.services.search import (
    CodeSearchRequest,
    CodeSearchResponse,
    SearchError,
    run_search,
    search_error_to_http_exception,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


# --------------------------------------------------------------------------- #
# POST /api/search                                                             #
# --------------------------------------------------------------------------- #


@router.post(
    "/",
    status_code=status.HTTP_200_OK,
    response_model=CodeSearchResponse,
)
async def search_code(
    body: CodeSearchRequest,
    request: Request,
) -> CodeSearchResponse:
    """Run a hybrid code search over the caller's indexed repo.

    Auth: ``request.state.user_id`` is populated by
    :class:`AuthMiddleware` from the sealed session cookie. The
    service uses it to look up the matching :class:`app.models.repo.Repo`
    row and verify ``is_indexed=True`` before opening LanceDB.

    Error mapping (via :func:`search_error_to_http_exception`):

    - :class:`SearchConfigError`       → 503
    - :class:`SearchRepoNotFoundError` → 404
    - :class:`SearchNotIndexedError`   → 400
    - :class:`SearchTableError`        → 502
    - anything else                    → 500
    """
    user_id: str = request.state.user_id
    try:
        return await run_search(user_id=user_id, request=body)
    except SearchError as exc:
        log.info(
            "search: rejected owner=%s repo=%s user_id=%s kind=%s message=%s",
            body.owner,
            body.repo,
            user_id,
            type(exc).__name__,
            exc,
        )
        raise search_error_to_http_exception(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.exception(
            "search: unexpected failure owner=%s repo=%s user_id=%s",
            body.owner,
            body.repo,
            user_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"unexpected search failure: {type(exc).__name__}",
        ) from exc


__all__ = ["router"]
