"""Reviews routes: surface the caller's review runs from the ``review``
table, joined with the repo / PR context and the token usage row.

All ``GET`` endpoints are user-scoped: they read ``request.state.user_id``
(set by ``AuthMiddleware``) and filter every query on it.

The eval-only ``POST /review`` Invokes the durable review function
asynchronously (``202`` + poll via ``GET /review/by-workflow/{id}``) so
 API Gateway's 29s budget is never held by the agent run. Both are gated
on the ``X-Eval-Token`` header (compared against
:attr:`Settings.eval_api_token`) rather than the WorkOS session cookie,
because the eval harness is a CLI process that cannot seal a session.
The routes are exempted from ``AuthMiddleware`` via ``BYPASS_METHODS``.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.enums import ReviewRunStatus
from app.models.pull_request import PullRequest
from app.models.repo import Repo
from app.models.review import Review, ReviewState
from app.models.review_usage import ReviewUsage
from app.repositories.code_comment import CodeCommentRepository
from app.repositories.installation import InstallationRepository
from app.repositories.repo import RepoRepository
from app.repositories.review import ReviewRepository
from app.repositories.review_summary import ReviewSummaryRepository
from app.repositories.review_usage import ReviewUsageRepository
from app.utils.schema import CommentSeverityStr, CommentSideStr, ReviewVerdictStr

router = APIRouter(prefix="/review", tags=["review"])


# --------------------------------------------------------------------------- #
# Eval trigger                                                                 #
# --------------------------------------------------------------------------- #


class EvalReviewRequest(BaseModel):
    """Body of ``POST /review``.

    Mirrors the eval dataset ``input.json`` plus the canonical
    identifiers the workflow needs (``github_repo_id`` /
    ``github_installation_id`` / ``user_id``). The route synthesises
    placeholder PR metadata (author / title / branches / status) since
    the workflow only consumes the SHAs and the installation token for
    cloning — the placeholders land on the ``pull_requests`` row but do
    not affect the review logic.
    """

    session_id: str = Field(default="eval-review-session")
    model: str = Field(description="llm model")
    baseUrl: str = Field(description="llm base url")

    user_id: str = Field(
        min_length=1,
        description="Synthetic WorkOS user_id the run is attributed to. "
        "Used as ``repos.user_id`` and ``review.user_id``.",
    )
    github_repo_id: int = Field(
        ge=1,
        description="GitHub repository id (the numeric id from "
        "``GET /repos/{owner}/{name}``). Idempotency key for the local "
        "``repos`` row.",
    )
    github_installation_id: int = Field(
        ge=1,
        description="GitHub App installation id used to mint the "
        "clone token inside the sandbox.",
    )

    github_pr_id: int = Field(ge=1, description="GitHub pr id")

    repo_url: str = Field(
        min_length=1,
        max_length=1024,
        description="Clone URL written to ``repos.clone_url`` for the "
        "synthetic Repo row.",
    )
    repo_owner: str = Field(
        min_length=1,
        description="GitHub repository owner (user or org login).",
    )
    repo_name: str = Field(
        min_length=1,
        description="GitHub repository name.",
    )
    pr_number: int = Field(ge=1, description="PR number on the repo.")

    base_sha: str = Field(
        min_length=7,
        max_length=64,
        description="Base commit SHA (full or abbreviated hex).",
    )

    base_branch: str = Field(description="Base Branch")
    default_branch: str = Field(description="Head Branch")
    head_branch: str = Field(description="Head Branch")

    head_sha: str = Field(
        min_length=7,
        max_length=64,
        description="Head commit SHA (full or abbreviated hex).",
    )

    post_to_github: bool = Field(
        default=False,
        description="When true, the workflow posts the review inline "
        "via the GitHub App. The eval harness always sets this to false.",
    )

    author: str = Field(default="sentinal", description="PR author")
    title: str = Field(default="Eval PR", description="PR title")


class EvalReviewComment(BaseModel):
    """One inline review comment in the eval response."""

    file_name: str
    comment: str
    severity: CommentSeverityStr
    from_line: int = Field(ge=0)
    to_line: int = Field(ge=0)
    side: CommentSideStr
    node_type: str | None = None


class EvalReviewUsage(BaseModel):
    """Per-model token usage for the run (one bucket per model name)."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


class EvalReviewResponse(BaseModel):
    """What ``POST /review`` returns on success.

    ``workflow_id`` is the deterministic
    ``review-v2:{repo_id}:{pr_number}:{head_sha[:7]}`` id (plus the eval
    route's ``:{rand6}`` suffix so repeated eval POSTs re-run instead of
    deduping). ``comments`` are the extractor output over the concatenated
    per-file reports, merged by the v2 combine step; ``summary`` is currently
    empty (the v2 base build is comments-only).
    """

    workflow_id: str
    verdict: ReviewVerdictStr
    summary: str
    comments: Annotated[list[EvalReviewComment], Field(default_factory=list)]
    usages: Annotated[dict[str, EvalReviewUsage], Field(default_factory=dict)]
    model: str | None


def _validate_user_id(user_id: str) -> None:
    """Reject the request when ``user_id`` is not a syntactically-valid UUID."""
    try:
        UUID(user_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"user_id must be a UUID: {user_id!r}",
        ) from exc


async def get_eval_token(
    x_eval_token: str | None = Header(default=None, alias="X-Eval-Token"),
) -> None:
    """Gate ``POST /review`` on a static shared secret.

    Returns 503 when ``settings.eval_api_token`` is unset (the route is
    disabled), 401 when the header is absent or mismatched. The
    middleware exempts ``POST /review`` from the session-cookie check
    via ``BYPASS_METHODS``, so this dependency is the sole gate.
    """
    if not settings.eval_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Eval API is not configured (set EVAL_API_TOKEN).",
        )
    if not x_eval_token or not _secrets_match(x_eval_token, settings.eval_api_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


def _secrets_match(provided: str, expected: str) -> bool:
    """Constant-time string comparison.

    Both sides are hashed with SHA-256 before ``hmac.compare_digest`` so
    a long mismatched secret does not leak via timing. ``hmac.compare_digest``
    requires equal-length inputs; hashing normalises that.
    """
    digest_a = hashlib.sha256(provided.encode("utf-8")).digest()
    digest_b = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(digest_a, digest_b)


class EvalReviewAccepted(BaseModel):
    """What ``POST /review`` returns: async dispatch, poll for results."""

    workflow_id: str
    execution_name: str
    status_url: str


def _eval_synthetic_payload(body: EvalReviewRequest) -> dict[str, object]:
    """Build a minimal ``pull_request.opened``-shaped payload for the durable."""
    return {
        "repository": {
            "id": body.github_repo_id,
            "name": body.repo_name,
            "owner": {"login": body.repo_owner},
            "default_branch": body.default_branch,
        },
        "pull_request": {
            "id": body.github_pr_id,
            "number": body.pr_number,
            "state": "open",
            "merged": False,
            "title": body.title,
            "body": "",
            "additions": 0,
            "deletions": 0,
            "changed_files": 0,
            "base": {"ref": body.base_branch, "sha": body.base_sha},
            "head": {"ref": body.head_branch, "sha": body.head_sha},
            "user": {"login": body.author},
        },
        "installation": {"id": body.github_installation_id},
    }


@router.post("", response_model=EvalReviewAccepted, status_code=status.HTTP_202_ACCEPTED)
async def trigger_review(
    request: Request,
    body: EvalReviewRequest,
    session: AsyncSession = Depends(get_session),
    _eval_token: None = Depends(get_eval_token),
) -> EvalReviewAccepted:
    """Invoke the review durable asynchronously; poll the result.

    Validates installation + repo rows (400 when missing), builds a
    synthetic ``opened`` payload the durable parses with the same
    ``extractPrPayload`` path as webhooks, Invokes with a
    ``:{rand6}``-suffixed execution name so repeated eval POSTs re-run
    instead of deduping, and returns ``202`` immediately. The durable
    flips the ``review`` lifecycle row to SUCCESS/FAILED; fetch it via
    ``GET /review/by-workflow/{workflow_id}``.
    """
    from app.workflows.durable.invoke import invokeOpenedDurable
    from app.workflows.durable.naming import createOpenedExecutionName
    from app.workflows.durable.types import OpenedDurableEvent

    installations = InstallationRepository(session=session)
    installation = await installations.find_by_github_installation_id(
        body.github_installation_id
    )
    if installation is None:
        raise HTTPException(status_code=400, detail={"error": "repo not found"})

    repos = RepoRepository(session=session)
    repo = await repos.find_by_github_repo_id(body.github_repo_id)
    if repo is None:
        raise HTTPException(status_code=400, detail={"error": "repo not found"})

    base_name = createOpenedExecutionName(
        ghRepoId=body.github_repo_id,
        prNumber=body.pr_number,
        headSha=body.head_sha,
    )
    execution_name = f"{base_name}:{uuid4().hex[:6]}"
    result = await invokeOpenedDurable(
        function_name=settings.review_opened_function_name
        or settings.review_durable_function_name,
        event=OpenedDurableEvent(
            delivery=f"eval-{execution_name}",
            execution_name=execution_name,
            payload=_eval_synthetic_payload(body),  # type: ignore[arg-type]
        ),
    )
    if not result.invoked:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"workflow_id": execution_name, "error": result.error},
        )
    return EvalReviewAccepted(
        workflow_id=execution_name,
        execution_name=execution_name,
        status_url=f"/review/by-workflow/{execution_name}",
    )


class EvalReviewStatus(BaseModel):
    """Poll response for ``GET /review/by-workflow/{workflow_id}``."""

    workflow_id: str
    state: str
    verdict: ReviewVerdictStr | None = None
    summary: str | None = None
    comments: list[EvalReviewComment] = Field(default_factory=list)
    usages: dict[str, EvalReviewUsage] = Field(default_factory=dict)
    model: str | None = None
    error: str | None = None


@router.get("/by-workflow/{workflow_id}", response_model=EvalReviewStatus)
async def get_review_by_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    _eval_token: None = Depends(get_eval_token),
) -> EvalReviewStatus:
    """Return the eval run's status + results once SUCCESS (poll target)."""
    repo = ReviewRepository(session=session)
    row = await repo.find_by_workflow_id(workflow_id)
    if row is None:
        raise HTTPException(status_code=404, detail="review not found")
    if row.state != ReviewState.SUCCESS:
        return EvalReviewStatus(
            workflow_id=workflow_id,
            state=str(row.state),
            error=row.error_message,
        )
    summaries = ReviewSummaryRepository(session=session)
    summary_row = await summaries.find_by_review_id(row.id)
    comments_repo = CodeCommentRepository(session=session)
    comment_rows = await comments_repo.find_by_review_id(
        row.id, order_by_created_at=True
    )
    usages = ReviewUsageRepository(session=session)
    usage_rows = await usages.find(
        col(usages.model.review_id) == row.id,
        limit=1,
    )
    usage_row = usage_rows[0] if usage_rows else None
    if summary_row is None:
        raise HTTPException(status_code=404, detail="review summary not found")
    return EvalReviewStatus(
        workflow_id=workflow_id,
        state=str(row.state),
        verdict=summary_row.verdict,  # type: ignore[arg-type]
        summary=summary_row.summary,
        comments=[
            EvalReviewComment(
                file_name=c.file_name,
                comment=c.comment,
                severity=c.severity,  # type: ignore[arg-type]
                from_line=c.from_line,
                to_line=c.to_line,
                side=c.side,  # type: ignore[arg-type]
                node_type=c.node_type,
            )
            for c in comment_rows
        ],
        usages=(
            {
                str(usage_row.llm_model_id or "default"): EvalReviewUsage(
                    input_tokens=usage_row.input_tokens,
                    output_tokens=usage_row.output_tokens,
                    total_tokens=usage_row.total_tokens,
                )
            }
            if usage_row is not None
            else {}
        ),
        model=row.llm_model,
    )


# --------------------------------------------------------------------------- #
# Lifecycle reader (existing)                                                  #
# --------------------------------------------------------------------------- #


class ReviewUsageOut(BaseModel):
    """Token usage for a single review run (one row per run)."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    review_status: ReviewRunStatus


class ReviewOut(BaseModel):
    """One review run with repo / PR context and its usage row.

    The usage join is a left join: runs without a persisted usage row
    (e.g. an early lifecycle failure) surface ``usage=None``.
    """

    id: str
    repo_name: str | None = None
    repo_owner: str | None = None
    pr_number: int
    pr_title: str | None = None
    commit_id: str
    trigger: str | None = None
    state: ReviewState
    comment_count: int | None = None
    llm_client: str | None = None
    llm_model: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    usage: ReviewUsageOut | None = None


@router.get("", response_model=list[ReviewOut])
async def list_reviews(
    request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=100),
) -> list[ReviewOut]:
    """List the caller's review runs, newest first.

    One query left-joins the ``review`` row with its repo, PR, and usage
    rows. The onclause casts mirror the ``repositories/base.py`` pattern
    to keep pyright happy with SQLModel instrumented-attribute equality.
    """
    try:
        repo = ReviewRepository(session=session)
        stmt = (
            select(Review, Repo, PullRequest, ReviewUsage)
            .outerjoin(Repo, cast(ColumnElement[bool], Review.repo_id == Repo.id))
            .outerjoin(
                PullRequest,
                cast(ColumnElement[bool], Review.pr_id == PullRequest.id),
            )
            .outerjoin(
                ReviewUsage,
                cast(ColumnElement[bool], ReviewUsage.review_id == Review.id),
            )
            .where(Review.user_id == request.state.user_id)
            .order_by(desc(Review.created_at))
            .limit(limit)
        )
        result = await repo.session.exec(stmt)
        rows = result.all()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list reviews")

    return [
        ReviewOut(
            id=review.id,
            repo_name=repo.repo_name if repo is not None else None,
            repo_owner=repo.repo_owner if repo is not None else None,
            pr_number=review.pr_number,
            pr_title=pr.title if pr is not None else None,
            commit_id=review.commit_id,
            trigger=review.trigger,
            state=review.state,
            comment_count=review.comment_count,
            llm_client=review.llm_client,
            llm_model=review.llm_model,
            started_at=review.started_at,
            completed_at=review.completed_at,
            created_at=review.created_at,
            usage=(
                ReviewUsageOut(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    review_status=usage.review_status,
                )
                if usage is not None
                else None
            ),
        )
        for review, repo, pr, usage in rows
    ]
