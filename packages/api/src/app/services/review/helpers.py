"""Review pipeline helpers.

Pure functions used by the review orchestrator and its steps: no I/O,
no session, no clock. Every function here is testable with plain
``assert`` calls.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.code_comment import CodeComment
from app.models.enums import (
    CommentSeverity,
    CommentSide,
    CommentState,
)
from app.services.agent.helpers import extract_message_kinds
from app.services.agent.models import (
    CodeCommentDraft,
    ReviewResult,
)
from app.services.review.errors import (
    ReviewAgentReturnedNoStructuredResponseError,
)
from app.utils.util import repo_path, uuidToStr


def get_repo_path(repo_name: str) -> str:
    """Return the in-sandbox path of the cloned ``repo_name``.

    Pure wrapper over :func:`app.utils.util.repo_path`. Lives in the
    pipeline so callers never have to know about the in-sandbox layout
    constants.
    """
    return repo_path(repo_name)


def map_drafts_to_comment_rows(
    *,
    pr_id: str,
    commit_id: str,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Translate :class:`CodeCommentDraft` objects into ORM rows.

    Each draft becomes a :class:`CodeComment` keyed to ``(pr_id,
    commit_id)`` with ``state=ACTIVE``. The agent's severity / side
    strings are coerced into the corresponding enums; a bad value raises
    ``ValueError`` here (this is a programmer error, not a pipeline
    failure mode).
    """
    rows: list[CodeComment] = []
    for draft in comments:
        rows.append(
            CodeComment(
                id=uuidToStr(),
                pr_id=pr_id,
                commit_id=commit_id,
                file_name=draft.file_name,
                comment=draft.comment,
                severity=CommentSeverity(draft.severity),
                from_line=draft.from_line,
                to_line=draft.to_line,
                side=CommentSide(draft.side),
                node_type=draft.node_type,
                state=CommentState.ACTIVE,
            )
        )
    return rows


def parse_review_response(result: object) -> ReviewResult:
    """Extract and validate the agent's ``structured_response`` payload.

    Pure: takes the full ``agent.ainvoke()`` result and returns a
    validated :class:`ReviewResult`. Raises
    :class:`ReviewAgentReturnedNoStructuredResponseError` when the
    agent finished without producing a ``structured_response`` key, or
    when the result is not a dict at all.
    """
    if not isinstance(result, dict):
        raise ReviewAgentReturnedNoStructuredResponseError(
            message_kinds=extract_message_kinds(result)
        )
    structured = result.get("structured_response")
    if structured is None:
        raise ReviewAgentReturnedNoStructuredResponseError(
            message_kinds=extract_message_kinds(result.get("messages"))
        )
    return ReviewResult.model_validate(structured)


__all__: list[str] = [
    "get_repo_path",
    "map_drafts_to_comment_rows",
    "parse_review_response",
]
