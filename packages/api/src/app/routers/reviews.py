"""Reviews routes: surface the caller's review runs from the ``review``
table, joined with the repo / PR context and the token usage row.

All endpoints are user-scoped: they read ``request.state.user_id`` (set by
``AuthMiddleware``) and filter every query on it.

The eval-only ``POST /review`` triggers the production ``reviewWorkflow``
synchronously and returns its output. It is gated on the
``X-Eval-Token`` request header (compared against
:attr:`Settings.eval_api_token`) rather than the WorkOS session cookie,
because the eval harness is a CLI process that cannot seal a session.
The route is exempted from ``AuthMiddleware`` via ``BYPASS_METHODS``.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID, uuid4

from dbos import DBOS, SetWorkflowID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.enums import PRStatus, ReviewRunStatus
from app.models.pull_request import PullRequest
from app.models.repo import Repo
from app.models.review import Review, ReviewState
from app.models.review_usage import ReviewUsage
from app.services.llm import createDefaultLLMContext
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoId,
    UserId,
)
from app.utils.schema import CommentSeverityStr, CommentSideStr, ReviewVerdictStr
from app.utils.util import uuidToStr
from app.workflows.review.triggers import (
    buildSandboxCtx,
    getRepoRecord,
    getUserIdFromInstallation,
)
from app.workflows.review.types import (
    emptyPrSize,
    ReviewWorkflowCtx,
)
from app.workflows.review.workflow import (
    buildReviewWorkflowInput,
    createReviewWorkflowId,
    reviewWorkflow,
)

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
    ``review:{repo_id}:{pr_number}:{head_sha[:7]}`` id, so duplicate
    POSTs for the same head SHA dedupe in DBOS and the second caller
    receives the first run's cached result. ``comments`` are sorted
    P1_CRITICAL → P2_WARNING → P3_NITPICK by the workflow's combine step.
    """

    workflow_id: str
    verdict: ReviewVerdictStr
    summary: str
    comments: Annotated[list[EvalReviewComment], Field(default_factory=list)]
    usages: Annotated[dict[str, EvalReviewUsage], Field(default_factory=dict)]


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


async def _ensure_repo_row(
    session: AsyncSession,
    *,
    user_id: str,
    github_repo_id: int,
    repo_owner: str,
    repo_name: str,
    clone_url: str,
) -> str:
    """Idempotent upsert of the local ``repos`` row.

    The workflow's FK chain (``pull_requests`` / ``review`` /
    ``code_comments`` / ``review_summaries``) needs a ``Repo`` row to
    exist. The route does this work because the webhook triggers do it
    too, but those resolve the row from the user's installation; the
    eval path has no installation-to-user mapping on the call side, so
    the row is synthesised here under the caller-supplied ``user_id``.
    Returns the row's id (UUID string).
    """
    stmt = select(Repo).where(Repo.github_repo_id == github_repo_id)
    existing = (await session.exec(stmt)).first()
    if existing is not None:
        return existing.id

    repo = Repo(
        id=uuidToStr(),
        user_id=user_id,
        github_repo_id=github_repo_id,
        repo_name=repo_name,
        repo_owner=repo_owner,
        clone_url=clone_url,
        url=None,
        private=False,
        default_branch=None,
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo.id


@router.post("", response_model=EvalReviewResponse)
async def trigger_review(
    request: Request,
    body: EvalReviewRequest,
    session: AsyncSession = Depends(get_session),
    _eval_token: None = Depends(get_eval_token),
) -> EvalReviewResponse:
    """Dispatch the production ``reviewWorkflow`` and return its output.

    See :class:`EvalReviewRequest` for the body shape. The handler
    upserts the local ``repos`` row, builds the ``ReviewWorkflowCtx``
    from settings (``createDefaultLLMContext()`` + a settings-driven
    ``SandboxCtx``), dispatches the workflow under its deterministic
    id, and waits synchronously for ``ReviewRunResult`` via
    ``handle.get_result()``. On workflow failure the route returns 500
    with the typed error name + message; the workflow's own ``except``
    block has already flipped the ``review`` lifecycle row to FAILED.
    """

    ghRepoId = body.github_repo_id
    ghPrId = body.github_pr_id

    githubInstallationId = InstallationId(body.github_installation_id)

    userId = await getUserIdFromInstallation(
        session,
        githubInstallationId=githubInstallationId,
    )

    if userId is None:
        raise HTTPException(status_code=400, detail={"error": "repo not found"})

    repo = await getRepoRecord(
        session,
        ghRepoId=ghRepoId,
    )

    if repo is None:
        raise HTTPException(status_code=400, detail={"error": "repo not found"})

    llm_ctx = createDefaultLLMContext()

    sandbox_ctx = buildSandboxCtx(
        userId=body.user_id,
        repoId=repo.id,
        repoName=body.repo_name,
    )

    workflow_input = buildReviewWorkflowInput(
        userId=UserId(
            body.user_id
        ),  # not derivable — synthetic UUID (dataset: 00000000-…-0001)
        ghRepoId=body.github_repo_id,  # dataset currently has fake 100000001
        # ghPrId=4395127676,  # API pull id (eval path uses 0)
        ghPrId=body.github_pr_id,
        prNumber=PRNumber(body.pr_number),
        baseBranch=body.base_branch,  # base.ref — matches the hardcode
        defaultBranch=body.default_branch,  # repo's default_branch (currently None)
        baseSha=body.base_sha,
        # headBranch="add-endpoints",  # currently "feature/eval"
        headBranch=body.head_branch,
        headSha=CommitId(body.head_sha),
        # author="Rjshakya",  # currently "eval"
        # title="Add endpoints",  # currently "Eval PR"
        author=body.author,
        title=body.title,
        body="",  # API body is null
        status=PRStatus.OPEN,
        prSize=emptyPrSize(),
        githubInstallationId=InstallationId(
            body.github_installation_id
        ),  # not publicly derivable (per-install secret)
        postToGithub=body.post_to_github,
        trigger="opened",
    )

    workflow_ctx = ReviewWorkflowCtx(llmCtx=llm_ctx, sandboxCtx=sandbox_ctx)
    workflow_id = createReviewWorkflowId(
        repoId=RepoId(repo.id),
        prNumber=PRNumber(body.pr_number),
        headSha=body.head_sha,
    )

    id = str(uuid4())
    workflow_id += f":{id[:6]}"

    with SetWorkflowID(workflow_id):
        handle = await DBOS.start_workflow_async(
            reviewWorkflow, workflow_ctx, workflow_input
        )

    try:
        result = await handle.get_result()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "workflow_id": workflow_id,
                "error": type(exc).__name__,
                "message": str(exc),
            },
        ) from exc

    review = result.review
    return EvalReviewResponse(
        workflow_id=workflow_id,
        verdict=review.verdict,
        summary=review.summary,
        comments=[
            EvalReviewComment(
                file_name=c.file_name,
                comment=c.comment,
                severity=c.severity,
                from_line=c.from_line,
                to_line=c.to_line,
                side=c.side,
                node_type=c.node_type,
            )
            for c in review.comments
        ],
        usages={
            model_name: EvalReviewUsage(
                input_tokens=int(bucket["input_tokens"]),
                output_tokens=int(bucket["output_tokens"]),
                total_tokens=int(bucket["total_tokens"]),
            )
            for model_name, bucket in result.usages["usages"].items()
        },
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
        result = await session.exec(stmt)
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
