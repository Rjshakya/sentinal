"""Search service: hybrid (FTS + vector) code search over an indexed repo.

Public surface:

- :func:`run_search` — plain async entry point consumed by the router.

Errors raised here are mapped to HTTP status codes by
:func:`app.services.search.errors.search_error_to_http_exception`:

- :class:`SearchConfigError`        → ``503``
- :class:`SearchRepoNotFoundError`  → ``404``
- :class:`SearchNotIndexedError`    → ``400``
- :class:`SearchTableError`         → ``502``
"""

from app.services.search.errors import (
    SearchConfigError,
    SearchError,
    SearchNotIndexedError,
    SearchRepoNotFoundError,
    SearchTableError,
    search_error_to_http_exception,
)
from app.services.search.helpers import build_table_uri, parse_node_types
from app.services.search.service import run_search
from app.services.search.types import (
    CodeSearchRequest,
    CodeSearchResponse,
    CodeSearchResultOut,
)

__all__ = [
    "CodeSearchRequest",
    "CodeSearchResponse",
    "CodeSearchResultOut",
    "SearchConfigError",
    "SearchError",
    "SearchNotIndexedError",
    "SearchRepoNotFoundError",
    "SearchTableError",
    "build_table_uri",
    "parse_node_types",
    "run_search",
    "search_error_to_http_exception",
]
