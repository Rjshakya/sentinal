"""Review pipeline helpers.

Pure functions used by the review orchestrator and its steps: no I/O,
no session, no clock. Every function here is testable with plain
``assert`` calls.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.result import Err, Ok, Result
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
from app.services.github.post_review import (
    GitHubAuthFailed,
    GitHubCommentPostFailed,
    GitHubPRNotFound,
    GitHubRateLimited,
    GitHubReviewPostFailed,
)
from app.services.review.errors import (
    DiffUnavailable,
    NoActiveSandbox,
    RepoNotFound,
    ReviewAgentCrashed,
    ReviewAgentReturnedNoStructuredResponse,
    ReviewPipelineError,
    SandboxConnectFailed,
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


def flatten_review_error_to_message(error: ReviewPipelineError) -> str:
    """Convert any :class:`ReviewPipelineError` variant to a one-liner.

    Pure: single ``match`` over the closed union. Exhaustive by
    construction; a new variant forces a pyright error here.
    """
    match error:
        case RepoNotFound(repo_id):
            return f"repo {repo_id!r} not found"
        case NoActiveSandbox(user_id, repo_id):
            return f"no active sandbox for user {user_id!r} repo {repo_id!r}"
        case SandboxConnectFailed(_, _, sandbox_id, cause):
            return f"failed to connect sandbox {sandbox_id!r}: {cause}"
        case DiffUnavailable(_, base_sha, head_sha, cause):
            return f"diff unavailable ({base_sha}...{head_sha}): {cause}"
        case ReviewAgentCrashed(cause):
            return f"review agent crashed: {cause}"
        case ReviewAgentReturnedNoStructuredResponse(message_kinds):
            return (
                "review agent returned no structured response "
                f"(messages={list(message_kinds)})"
            )
        case GitHubReviewPostFailed(owner=owner, repo=repo, pr_number=pr_number, cause=cause):
            return f"github review post failed for {owner}/{repo}#{pr_number}: {cause}"
        case GitHubAuthFailed(installation_id=installation_id, cause=cause):
            return f"github auth failed for installation {installation_id}: {cause}"
        case GitHubRateLimited(installation_id=installation_id, cause=cause):
            return f"github rate limited for installation {installation_id}: {cause}"
        case GitHubPRNotFound(owner=owner, repo=repo, pr_number=pr_number):
            return f"github pr not found: {owner}/{repo}#{pr_number}"
        case GitHubCommentPostFailed(file_name=file_name, line=line, cause=cause):
            return f"github comment post failed for {file_name}:{line}: {cause}"
        case _:
            return f"github post failed: {error}"


def parse_review_response(
    result: object,
) -> Result[ReviewResult, ReviewAgentReturnedNoStructuredResponse]:
    """Extract and validate the agent's ``structured_response`` payload.

    Pure: takes the full ``agent.ainvoke()`` result, returns ``Ok`` with
    a validated :class:`ReviewResult` or ``Err`` with the variant that
    names the message kinds the agent did produce.
    """
    if not isinstance(result, dict):
        return Err(
            ReviewAgentReturnedNoStructuredResponse(
                message_kinds=extract_message_kinds(result)
            )
        )
    structured = result.get("structured_response")
    if structured is None:
        return Err(
            ReviewAgentReturnedNoStructuredResponse(
                message_kinds=extract_message_kinds(result.get("messages"))
            )
        )
    return Ok(ReviewResult.model_validate(structured))


__all__: list[str] = [
    "flatten_review_error_to_message",
    "get_repo_path",
    "map_drafts_to_comment_rows",
    "parse_review_response",
]
