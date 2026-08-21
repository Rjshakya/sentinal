"""Shared Pydantic types for the search service.

Frozen models — the service is stateless so they don't need to be
DBOS-serializable, but freezing catches accidental mutation and keeps
the wire shape stable.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CodeSearchRequest",
    "CodeSearchResponse",
    "CodeSearchResultOut",
]


class CodeSearchRequest(BaseModel):
    """Body of ``POST /api/search``.

    ``owner`` + ``repo`` are the GitHub-side identifiers — the same
    pair the indexing pipeline takes on its input. ``query`` is the
    free-form text the user typed; ``limit`` caps the result list
    (default 10, max 50).
    """

    model_config = ConfigDict(frozen=True)

    owner: str = Field(min_length=1, max_length=255)
    repo: str = Field(min_length=1, max_length=255)
    query: str = Field(min_length=1, max_length=2048)
    limit: int = Field(default=10, ge=1, le=50)


class CodeSearchResultOut(BaseModel):
    """One ranked match from the LanceDB hybrid search.

    Fields mirror the in-sandbox ``CodeChunks`` schema, with two
    additions:

    - ``node_types`` is split from the comma-separated storage form
      back into a list of strings for the JSON payload.
    - ``_relevance_score`` is the LanceDB FTS / hybrid ``_score``;
      it is included for the dashboard's sort-by-score logic.
    """

    model_config = ConfigDict(frozen=True)

    file_name: str
    language: str
    start_line: int
    end_line: int
    node_types: list[str]
    content: str
    _relevance_score: float


class CodeSearchResponse(BaseModel):
    """Body of the ``POST /api/search`` response.

    Echoes ``owner`` / ``repo`` / ``query`` so the frontend does not
    need to keep its own request echo in sync.
    """

    model_config = ConfigDict(frozen=True)

    owner: str
    repo: str
    query: str
    results: list[CodeSearchResultOut]
