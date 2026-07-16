"""Review pipeline — Functional Core / Imperative Shell.

Mirrors :mod:`app.services.agent.setup_pipeline`:

- **Ring 1 (pure)** — prompt assembly, comment-row mapping, error flattening.
- **Ring 2 (orchestration)** — :func:`run_review_pipeline` sequences I/O and
  threads ``Result`` values.
- **Ring 3 (shell)** — :class:`E2BReviewAgentRunner`,
  :class:`GivenDiffProvider`, :class:`SandboxDiffProvider`, and
  :func:`connect_active_sandbox`.

Persistence helpers live at the bottom of this module and are called by
the orchestrator. The router is a thin adapter that validates config,
builds the diff provider / agent runner, and hands them in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Sequence

from e2b import AsyncSandbox
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.result import Err, Ok, Result
from app.core.sandbox import BaseSandbox
from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.models.code_comment import CodeComment
from app.models.enums import (
    CommentSeverity,
    CommentSide,
    CommentState,
    PRStatus,
    ReviewVerdict,
)
from app.models.pull_request import PullRequest
from app.models.repo import Repo
from app.models.review_summary import ReviewSummary
from app.services.agent import review as agent_review
from app.services.agent.models import CodeCommentDraft, ReviewResult
from app.services.agent.review_errors import (
    DiffUnavailable,
    NoActiveSandbox,
    RepoNotFound,
    ReviewAgentCrashed,
    ReviewAgentReturnedNoStructuredResponse,
    SandboxConnectFailed,
    ReviewPipelineError,
)
from app.services.agent.setup import active_sandbox
from app.services.sandbox_scripts.utils import workspace_path
from app.utils.util import uuidToStr

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# result type                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReviewRunResult:
    """What the orchestrator hands back to the router."""

    pr_id: str
    commit_id: str
    summary_id: str
    comment_ids: list[str]


# --------------------------------------------------------------------------- #
# ports                                                                       #
# --------------------------------------------------------------------------- #


class DiffProvider(Protocol):
    """Source of the unified diff the review agent reads."""

    async def get_diff(
        self,
        sandbox: BaseSandbox,
        *,
        repo_id: str,
        repo_name: str,
        base_sha: str,
        head_sha: str,
    ) -> Result[str, DiffUnavailable]: ...


class ReviewAgentRunner(Protocol):
    """LLM-SDK boundary for the review agent."""

    async def run(
        self,
        *,
        diff: str,
        repo_id: str,
        repo_name: str,
        user_id: str,
        sandbox: AsyncSandbox,
    ) -> Result[
        ReviewResult,
        ReviewAgentCrashed | ReviewAgentReturnedNoStructuredResponse,
    ]: ...


# --------------------------------------------------------------------------- #
# Ring 3 — shell adapters                                                     #
# --------------------------------------------------------------------------- #


class GivenDiffProvider:
    """Use a diff that the caller already supplied (manual / dashboard path)."""

    def __init__(self, diff: str) -> None:
        self._diff = diff

    async def get_diff(
        self,
        sandbox: BaseSandbox,
        *,
        repo_id: str,
        repo_name: str,
        base_sha: str,
        head_sha: str,
    ) -> Result[str, DiffUnavailable]:
        return Ok(self._diff)


class SandboxDiffProvider:
    """Compute the PR diff inside the already-cloned sandbox (webhook path)."""

    async def get_diff(
        self,
        sandbox: BaseSandbox,
        *,
        repo_id: str,
        repo_name: str,
        base_sha: str,
        head_sha: str,
    ) -> Result[str, DiffUnavailable]:
        repo_path = f"{workspace_path()}/{repo_name}"

        fetch = await sandbox.execute(
            "git fetch origin",
            cwd=repo_path,
            timeout=120,
        )
        if fetch.exit_code != 0:
            log.warning(
                "git fetch origin failed (continuing): repo=%s exit_code=%s stderr=%s",
                repo_name,
                fetch.exit_code,
                fetch.stderr,
            )

        diff_result = await sandbox.execute(
            f"git diff {base_sha}...{head_sha}",
            cwd=repo_path,
            timeout=120,
        )
        if diff_result.exit_code != 0:
            tail = (diff_result.stderr or diff_result.stdout or "").strip()[:500]
            return Err(
                DiffUnavailable(
                    repo_id=repo_id,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    cause=f"git diff exited {diff_result.exit_code}: {tail}",
                )
            )

        return Ok(diff_result.stdout or "")


class E2BReviewAgentRunner:
    """Production adapter for :class:`ReviewAgentRunner`.

    Wraps :func:`app.services.agent.review.run_review` and converts all
    exceptions into typed ``Err`` variants so the orchestrator never
    sees a raised exception from the LLM SDK.
    """

    async def run(
        self,
        *,
        diff: str,
        repo_id: str,
        repo_name: str,
        user_id: str,
        sandbox: AsyncSandbox,
    ) -> Result[
        ReviewResult,
        ReviewAgentCrashed | ReviewAgentReturnedNoStructuredResponse,
    ]:
        try:
            result = await agent_review.run_review(
                diff=diff,
                repo_id=repo_id,
                repo_name=repo_name,
                user_id=user_id,
                sandbox=sandbox,
            )
            return Ok(result)
        except RuntimeError as exc:
            # ``run_review`` raises RuntimeError when structured_response is missing.
            return Err(
                ReviewAgentReturnedNoStructuredResponse(
                    message_kinds=(str(exc),),
                )
            )
        except Exception as exc:
            return Err(ReviewAgentCrashed(cause=f"{type(exc).__name__}: {exc}"))


async def connect_active_sandbox(
    session: AsyncSession,
    *,
    user_id: str,
    repo_id: str,
    spec: E2BSandboxSpec,
) -> Result[E2BSandbox, NoActiveSandbox | SandboxConnectFailed]:
    """Look up the active sandbox row and connect to the underlying E2B sandbox."""
    sb_row = await active_sandbox(
        session=session, user_id=user_id, repo_id=repo_id
    )
    if sb_row is None:
        return Err(NoActiveSandbox(user_id=user_id, repo_id=repo_id))

    try:
        connected = await E2BSandbox.connect(
            sandbox_id=sb_row.id,
            sandbox_name=sb_row.sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
        return Ok(connected)
    except Exception as exc:
        log.exception(
            "failed to connect sandbox: user_id=%s repo_id=%s sandbox_id=%s",
            user_id,
            repo_id,
            sb_row.id,
        )
        return Err(
            SandboxConnectFailed(
                user_id=user_id,
                repo_id=repo_id,
                sandbox_id=sb_row.id,
                cause=f"{type(exc).__name__}: {exc}",
            )
        )


# --------------------------------------------------------------------------- #
# Ring 1 — pure helpers                                                       #
# --------------------------------------------------------------------------- #


def map_drafts_to_comment_rows(
    *,
    pr_id: str,
    commit_id: str,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Build :class:`CodeComment` rows from the agent's draft comments."""
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
    """Convert any typed review error into a short human-readable message."""
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


# --------------------------------------------------------------------------- #
# persistence helpers                                                         #
# --------------------------------------------------------------------------- #


async def _resolve_repo(
    session: AsyncSession,
    repo_id: str,
) -> Result[Repo, RepoNotFound]:
    """Fetch the repo row by id."""
    repo = await session.get(Repo, repo_id)
    if repo is None:
        return Err(RepoNotFound(repo_id=repo_id))
    return Ok(repo)


async def _upsert_pull_request(
    session: AsyncSession,
    *,
    repo_id: str,
    github_pr_id: int | None,
    number: int,
    author: str,
    title: str,
    body: str | None,
    base_branch: str,
    base_sha: str,
    head_branch: str,
    head_sha: str,
) -> PullRequest:
    """Insert or update a PullRequest row keyed on ``(repo_id, number)``."""
    existing = (
        await session.exec(
            select(PullRequest).where(
                PullRequest.repo_id == repo_id,
                PullRequest.number == number,
            )
        )
    ).first()

    if existing is not None:
        existing.title = title
        existing.body = body
        existing.author = author
        existing.base_branch = base_branch
        existing.base_sha = base_sha
        existing.head_branch = head_branch
        existing.head_sha = head_sha
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        log.info(
            "updated pull request: pr_id=%s repo_id=%s number=%s",
            existing.id,
            repo_id,
            number,
        )
        return existing

    pr = PullRequest(
        id=uuidToStr(),
        repo_id=repo_id,
        number=number,
        author=author,
        title=title,
        body=body,
        status=PRStatus.OPEN,
        base_branch=base_branch,
        base_sha=base_sha,
        head_branch=head_branch,
        head_sha=head_sha,
    )
    session.add(pr)
    await session.commit()
    await session.refresh(pr)
    log.info(
        "inserted pull request: pr_id=%s repo_id=%s number=%s",
        pr.id,
        repo_id,
        number,
    )
    return pr


async def _persist_review_summary(
    session: AsyncSession,
    *,
    pr_id: str,
    commit_id: str,
    result: ReviewResult,
) -> ReviewSummary:
    """Insert a single ReviewSummary row."""
    summary = ReviewSummary(
        pr_id=pr_id,
        commit_id=commit_id,
        summary=result.summary,
        verdict=ReviewVerdict(result.verdict),
    )
    session.add(summary)
    await session.commit()
    await session.refresh(summary)
    log.info(
        "persisted review summary: summary_id=%s pr_id=%s verdict=%s",
        summary.id,
        pr_id,
        summary.verdict,
    )
    return summary


async def _persist_code_comments(
    session: AsyncSession,
    *,
    pr_id: str,
    commit_id: str,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Insert one CodeComment row per finding."""
    rows = map_drafts_to_comment_rows(
        pr_id=pr_id, commit_id=commit_id, comments=comments
    )
    if not rows:
        log.info("no code comments to persist (pr_id=%s)", pr_id)
        return []
    for row in rows:
        session.add(row)
    await session.commit()
    for row in rows:
        await session.refresh(row)
    log.info(
        "persisted %d code comment(s): pr_id=%s commit_id=%s",
        len(rows),
        pr_id,
        commit_id,
    )
    return rows


# --------------------------------------------------------------------------- #
# Ring 2 — orchestrator                                                       #
# --------------------------------------------------------------------------- #


async def run_review_pipeline(
    *,
    user_id: str,
    repo_id: str,
    repo_name: str | None = None,
    github_pr_id: int | None = None,
    pr_number: int,
    pr_title: str,
    pr_author: str,
    pr_body: str | None = None,
    base_branch: str,
    base_sha: str,
    head_branch: str,
    head_sha: str,
    diff_provider: DiffProvider,
    agent_runner: ReviewAgentRunner,
    session: AsyncSession,
    spec: E2BSandboxSpec,
) -> Result[ReviewRunResult, ReviewPipelineError]:
    """Run one review end-to-end.

    Sequence: resolve repo → upsert PR → connect sandbox → get diff →
    run agent → persist summary + comments. Each stage returns a
    ``Result``; an ``Err`` short-circuits to the caller.

    The single outermost ``try / except`` catches anything escaping the
    typed pipeline and converts it to :class:`ReviewAgentCrashed`.
    """
    try:
        repo_result = await _resolve_repo(session, repo_id)
        if isinstance(repo_result, Err):
            return Err(repo_result.error)
        repo = repo_result.value

        name = repo_name or repo.repo_name

        pr = await _upsert_pull_request(
            session=session,
            repo_id=repo_id,
            github_pr_id=github_pr_id,
            number=pr_number,
            author=pr_author,
            title=pr_title,
            body=pr_body,
            base_branch=base_branch,
            base_sha=base_sha,
            head_branch=head_branch,
            head_sha=head_sha,
        )
        commit_id = head_sha

        sandbox_result = await connect_active_sandbox(
            session=session,
            user_id=user_id,
            repo_id=repo_id,
            spec=spec,
        )
        if isinstance(sandbox_result, Err):
            return Err(sandbox_result.error)
        sandbox = sandbox_result.value

        diff_result = await diff_provider.get_diff(
            sandbox,
            repo_id=repo_id,
            repo_name=name,
            base_sha=base_sha,
            head_sha=head_sha,
        )
        if isinstance(diff_result, Err):
            return Err(diff_result.error)
        diff = diff_result.value

        agent_result = await agent_runner.run(
            diff=diff,
            repo_id=repo_id,
            repo_name=name,
            user_id=user_id,
            sandbox=sandbox.sandbox,
        )
        if isinstance(agent_result, Err):
            return Err(agent_result.error)
        review = agent_result.value

        summary = await _persist_review_summary(
            session=session,
            pr_id=pr.id,
            commit_id=commit_id,
            result=review,
        )
        comment_rows = await _persist_code_comments(
            session=session,
            pr_id=pr.id,
            commit_id=commit_id,
            comments=review.comments,
        )

        return Ok(
            ReviewRunResult(
                pr_id=pr.id,
                commit_id=commit_id,
                summary_id=str(summary.id),
                comment_ids=[row.id for row in comment_rows],
            )
        )
    except Exception as exc:
        log.exception(
            "review pipeline crashed: repo_id=%s pr_number=%s",
            repo_id,
            pr_number,
        )
        return Err(ReviewAgentCrashed(cause=f"{type(exc).__name__}: {exc}"))
