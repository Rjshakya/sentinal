"""Search-pipeline typed errors.

Mirrors the convention from :mod:`app.services.indexing.errors`: every
failure raised inside the search service is a subclass of
:class:`SearchError`. The router maps each subclass to an HTTP status
via a small :func:`search_error_to_http_exception` helper. There is no
retry layer (search is a stateless read, no DBOS) so transient-vs-final
distinction is not encoded — every error here is final and surfaces to
the caller verbatim.
"""

from __future__ import annotations

from fastapi import HTTPException

__all__ = [
    "SearchConfigError",
    "SearchError",
    "SearchRepoNotFoundError",
    "SearchTableError",
    "search_error_to_http_exception",
]


class SearchError(Exception):
    """Base class for every search-pipeline error."""


class SearchConfigError(SearchError):
    """The indexing pipeline is not configured on the host.

    Required env vars: ``OPENAI_API_KEY``, ``INDEX_S3_BUCKET`` and the
    AWS credentials (``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``
    / ``AWS_REGION`` / ``AWS_ENDPOINT_URL``). Surfaces as ``503``.
    """

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(message or detail or "search is not configured")


class SearchRepoNotFoundError(SearchError):
    """No :class:`app.models.repo.Repo` row exists for this user + owner + name.

    Surfaces as ``404``. The repo has never been set up by the caller
    (no row in ``repos``).
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        user_id: str = "",
        owner: str = "",
        repo: str = "",
    ) -> None:
        self.user_id = user_id
        self.owner = owner
        self.repo = repo
        super().__init__(
            message or f"repo {owner}/{repo} is not installed for this user"
        )


class SearchNotIndexedError(SearchError):
    """The repo exists for the user but has never been indexed (``is_indexed=False``).

    Surfaces as ``400``. The caller needs to finish indexing (the
    dashboard's repositories page already has an Index button) before
    searching.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        owner: str = "",
        repo: str = "",
    ) -> None:
        self.owner = owner
        self.repo = repo
        super().__init__(
            message or f"repo {owner}/{repo} has not been indexed yet"
        )


class SearchTableError(SearchError):
    """LanceDB failed to open the dataset or execute the query.

    Wraps every exception raised by the LanceDB / S3 stack so the
    router can map it to a single ``502`` regardless of the underlying
    cause. The original exception's ``type(exc).__name__`` and message
    are preserved on :attr:`cause` for log correlation.
    """

    def __init__(self, message: str | None = None, *, cause: str = "") -> None:
        self.cause = cause
        super().__init__(message or f"search backend failure: {cause}")


def search_error_to_http_exception(exc: SearchError) -> HTTPException:
    """Map a :class:`SearchError` to the right :class:`HTTPException`.

    Centralised so the router stays free of error-class branching and
    so the HTTP contract is documented in one place.
    """
    if isinstance(exc, SearchConfigError):
        return HTTPException(
            status_code=503,
            detail=(
                "Search is not configured. Set OPENAI_API_KEY, "
                "INDEX_S3_BUCKET, AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY, AWS_REGION and "
                "AWS_ENDPOINT_URL on the API server."
            ),
        )
    if isinstance(exc, SearchRepoNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, SearchNotIndexedError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, SearchTableError):
        return HTTPException(
            status_code=502,
            detail=f"search backend failure: {exc.cause or exc}",
        )
    return HTTPException(status_code=500, detail=str(exc))
