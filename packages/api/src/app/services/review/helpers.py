"""Review pipeline helpers.

Pure functions used by the review workflow and its steps: no I/O,
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
from app.services.agent.models import CodeCommentDraft
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


def create_review_workflow_id(*, repo_id: str, pr_number: int, head_sha: str) -> str:
    """Build the deterministic inner review workflow id.

    Mirrors the formula used by
    :func:`app.services.review.webhook.handle_pull_request_opened`
    so the inner workflow dedupes across triggers.
    """
    short_sha = head_sha[:7]
    return f"review:{repo_id}:{pr_number}:{short_sha}"


__all__ = ["get_repo_path", "map_drafts_to_comment_rows", "create_review_workflow_id"]
