"""Webhook trigger adapters for the review workflow.

The edge that turns verified GitHub deliveries into dispatched
:func:`app.workflows.review.workflow.reviewWorkflow` runs.

Two entry points, one per webhook event the review pipeline consumes:

- :func:`handlePullRequestOpened` — a ``pull_request`` ``opened``
  delivery; the PR fields ride on the payload.
- :func:`handleIssueCommentCreated` — an ``issue_comment`` ``created``
  delivery mentioning ``@<app_slug> review``; the PR state is fetched
  from the GitHub API (:mod:`app.services.github.pr` sub-service) and
  the diff range narrows to the commits since the last successful
  review (incremental re-review via ``diffBaseSha``).

Both are called by the github webhook sub-service delegation handlers
(:mod:`app.services.github.webhook.handlers`) through a deferred import
(cycle avoidance). They follow the adapter conventions:

- Every expected outcome — skip paths, malformed payloads, missing
  rows — returns a :class:`ReviewTriggerAck`; the adapters never raise
  for business outcomes (infrastructure failures propagate so GitHub
  redelivers the delivery).
- DB access is scoped to one :func:`app.core.db.async_session_maker`
  session per delivery; GitHub API calls go through the pr sub-service
  ctx.
- The run environment (:class:`ReviewWorkflowCtx` — per-user
  :class:`LLMCtx` with a settings fallback, settings-driven
  :class:`SandboxCtx`) is resolved here, at the edge.
- Dispatch uses the deterministic ``review:{repo_id}:{pr}:{head_sha[:7]}``
  id, so duplicate deliveries dedupe in DBOS.
"""

from __future__ import annotations

import logging
from operator import rshift
from typing import Any, cast

from dbos import DBOS, SetWorkflowID
from pydantic import BaseModel, ValidationError
from sqlalchemy.engine import result
from sqlmodel import select

from app.core.config import settings
from app.core.db import async_session_maker
from app.models.enums import PRStatus
from app.models.installation import Installation
from app.models.repo import Repo
from app.models.review import Review, ReviewState
from app.services.github.pr.errors import GitHubPRError
from app.services.github.pr.service import addReaction, createPRCtx, getPrState
from app.services.llm import (
    LLMContextError,
    LLMCtx,
    createDefaultLLMContext,
    createUserLLMContext,
)
from app.services.pr_issue_comment.helpers import (
    classify_comment,
    effective_diff_base,
    validate_comment_payload,
)
from app.services.pr_issue_comment.types import LastReviewSnapshot
from app.services.sandbox.service import (
    DEFAULT_ROOT_PATH,
    createSandboxCtx,
    getDefaulSandboxName,
)
from app.services.sandbox.types import ProviderId, SanboxProviderApiKey, SandboxCtx
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)
from app.workflows.review.types import (
    PRSizeStats,
    ReviewWorkflowCtx,
    ReviewWorkflowInput,
)
from app.workflows.review.workflow import (
    buildReviewWorkflowInput,
    createReviewWorkflowId,
    reviewWorkflow,
)

from sqlmodel.ext.asyncio.session import AsyncSession

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# ack                                                                          #
# --------------------------------------------------------------------------- #


class ReviewTriggerAck(BaseModel):
    """What a trigger adapter hands back to the webhook handler for logging."""

    accepted: bool
    action: str
    delivery: str
    skip_reason: str | None = None


# --------------------------------------------------------------------------- #
# pure helpers                                                                 #
# --------------------------------------------------------------------------- #


class PRPayload(BaseModel):
    """Flat, typed projection of a verified ``pull_request`` ``opened`` payload."""

    ghRepoId: int
    ghPrId: int
    number: PRNumber
    baseBranch: str
    defaultBranch: str | None
    baseSha: str
    headBranch: str
    headSha: CommitId
    author: str
    title: str
    body: str
    status: PRStatus
    prSize: PRSizeStats


def _prStatus(state: Any, merged: Any) -> PRStatus | None:
    """Map GitHub's ``(state, merged)`` pair onto :class:`PRStatus`.

    Returns ``None`` for any state other than ``open`` / ``closed`` so
    the caller can reject the payload as malformed.
    """
    if state == "open":
        return PRStatus.OPEN
    if state == "closed":
        return PRStatus.MERGED if merged else PRStatus.CLOSED
    return None


def _prStatusFromState(state: str, merged: bool) -> PRStatus:
    """Map a GitHub API ``(state, merged)`` pair onto :class:`PRStatus`.

    Defaults to :attr:`PRStatus.OPEN` for any non-``closed`` state —
    the PR was fetched while open (or the payload carries no state).
    """
    if state == "closed":
        return PRStatus.MERGED if merged else PRStatus.CLOSED
    return PRStatus.OPEN


def extractPrPayload(payload: dict[str, Any]) -> PRPayload | None:
    """Project the ``pull_request`` payload onto :class:`PRPayload`.

    Returns ``None`` on any malformed input — the caller folds that
    into a ``malformed_payload`` skip. Never raises.
    """
    repo = payload.get("repository") or {}
    pr = payload.get("pull_request") or {}
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    user = pr.get("user") or {}

    flat: dict[str, Any] = {
        "ghRepoId": repo.get("id"),
        "ghPrId": pr.get("id"),
        "number": pr.get("number"),
        "baseBranch": base.get("ref"),
        "defaultBranch": repo.get("default_branch"),
        "baseSha": base.get("sha"),
        "headBranch": head.get("ref"),
        "headSha": head.get("sha"),
        "author": user.get("login"),
        "title": pr.get("title"),
        "body": pr.get("body") or "",
        "status": _prStatus(pr.get("state"), pr.get("merged")),
        "prSize": {
            "additions": int(pr.get("additions") or 0),
            "deletions": int(pr.get("deletions") or 0),
            "changedFiles": int(pr.get("changed_files") or 0),
        },
    }
    try:
        return PRPayload.model_validate(flat)
    except ValidationError:
        return None


# --------------------------------------------------------------------------- #
# edge helpers                                                                 #
# --------------------------------------------------------------------------- #


def reviewConfigured() -> bool:
    """True iff the review pipeline's env prerequisites are met."""
    return settings.llm_configured and settings.sandbox_configured


async def resolveLlmCtx(session: AsyncSession, *, userId: str) -> LLMCtx:
    """Resolve the run's LLM context: the user's stored row, else settings."""
    result = await createUserLLMContext(session, UserId(userId))
    if isinstance(result, LLMContextError):
        log.info(
            "review.trigger: no user llm config, falling back to settings: user_id=%s",
            userId,
        )
        return createDefaultLLMContext()
    return result


def buildSandboxCtx(*, userId: str, repoId: str, repoName: str) -> SandboxCtx:
    """Assemble the run's sandbox context from settings-driven defaults."""
    provider = cast(ProviderId, settings.sandbox_provider)
    api_key = settings.e2b_api_key if provider == "e2b" else settings.daytona_api_key
    return createSandboxCtx(
        userId=UserId(userId),
        repoId=RepoId(repoId),
        repoName=repoName,
        providerId=provider,
        apiKey=SanboxProviderApiKey(api_key),
        sandboxName=getDefaulSandboxName(repoName),
        rootPath=DEFAULT_ROOT_PATH[provider],
    )


async def getUserIdFromInstallation(
    session: AsyncSession, *, githubInstallationId: int
) -> str | None:
    """Return the WorkOS ``user_id`` that owns the installation, or ``None``."""
    stmt = select(Installation.user_id).where(
        Installation.github_installation_id == githubInstallationId,
        Installation.user_id.is_not(None),  # type: ignore[union-attr]
    )
    return (await session.exec(stmt)).first()


async def getRepoRecord(session: AsyncSession, *, ghRepoId: int) -> Repo | None:
    """Return the local :class:`Repo` row for a GitHub repo id, or ``None``."""
    stmt = select(Repo).where(Repo.github_repo_id == ghRepoId)
    result = await session.exec(stmt)
    return result.first()


async def loadLastReview(
    session: AsyncSession,
    *,
    repoId: str,
    prNumber: int,
) -> LastReviewSnapshot | None:
    """Return the latest successful :class:`Review` row for the PR, or ``None``."""
    stmt = (
        select(Review)
        .where(
            Review.repo_id == repoId,
            Review.pr_number == prNumber,
            Review.state == ReviewState.SUCCESS,
        )
        .order_by(Review.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    row = (await session.exec(stmt)).first()
    if row is None:
        return None
    return LastReviewSnapshot(
        commit_id=row.commit_id,
        base_sha=row.base_sha,
        created_at=row.created_at,
    )


async def dispatchReview(
    *,
    repoId: str,
    prNumber: int,
    headSha: str,
    workflowCtx: ReviewWorkflowCtx,
    workflowInput: ReviewWorkflowInput,
) -> str:
    """Start ``reviewWorkflow`` under its deterministic id; return the id."""
    workflow_id = createReviewWorkflowId(
        repoId=RepoId(repoId),
        prNumber=PRNumber(prNumber),
        headSha=headSha,
    )
    with SetWorkflowID(workflow_id):
        await DBOS.start_workflow_async(reviewWorkflow, workflowCtx, workflowInput)
    return workflow_id


# --------------------------------------------------------------------------- #
# entry points                                                                 #
# --------------------------------------------------------------------------- #


async def handlePullRequestOpened(
    payload: dict[str, Any], delivery: str, session: AsyncSession
) -> ReviewTriggerAck:
    """Dispatch a verified ``pull_request`` ``opened`` delivery to the workflow.

    Skip reasons: ``not_opened``, ``malformed_payload``,
    ``malformed_installation``, ``review_not_configured``,
    ``unowned_installation``, ``repo_not_configured``. Never raises for
    business outcomes.
    """

    sandboxApiKey = settings.e2b_api_key
    sandboxDefaultProvider: ProviderId = "e2b"
    action = payload.get("action")

    pr_payload = extractPrPayload(payload)
    if pr_payload is None:
        return ReviewTriggerAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="malformed_payload",
        )

    installation = payload.get("installation") or {}
    installation_id = cast(int, installation.get("id"))

    userId = await getUserIdFromInstallation(
        session, githubInstallationId=installation_id
    )
    if userId is None:
        return ReviewTriggerAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="unowned_installation",
        )

    repo = await getRepoRecord(session, ghRepoId=pr_payload.ghRepoId)
    if repo is None:
        return ReviewTriggerAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="repo_not_configured",
        )

    llm_ctx = await resolveLlmCtx(session, userId=userId)
    sandbox_ctx = createSandboxCtx(
        userId=UserId(userId),
        repoId=RepoId(repo.id),
        repoName=repo.repo_name,
        providerId=sandboxDefaultProvider,
        apiKey=SanboxProviderApiKey(sandboxApiKey),
        sandboxName=getDefaulSandboxName(repo.repo_name),
        rootPath=DEFAULT_ROOT_PATH[sandboxDefaultProvider],
    )

    workflow_input = buildReviewWorkflowInput(
        userId=UserId(userId),
        ghRepoId=pr_payload.ghRepoId,
        ghPrId=pr_payload.ghPrId,
        prNumber=pr_payload.number,
        baseBranch=pr_payload.baseBranch,
        defaultBranch=pr_payload.defaultBranch,
        baseSha=pr_payload.baseSha,
        headBranch=pr_payload.headBranch,
        headSha=pr_payload.headSha,
        author=pr_payload.author,
        title=pr_payload.title,
        body=pr_payload.body,
        status=pr_payload.status,
        prSize=pr_payload.prSize,
        githubInstallationId=InstallationId(installation_id),
        postToGithub=True,
        trigger="opened",
    )
    workflow_ctx = ReviewWorkflowCtx(llmCtx=llm_ctx, sandboxCtx=sandbox_ctx)
    workflow_id = await dispatchReview(
        repoId=repo.id,
        prNumber=pr_payload.number,
        headSha=pr_payload.headSha,
        workflowCtx=workflow_ctx,
        workflowInput=workflow_input,
    )

    log.info(
        "review.trigger: started workflow: delivery=%s workflow_id=%s "
        "gh_repo_id=%s number=%s head_sha=%s",
        delivery,
        workflow_id,
        pr_payload.ghRepoId,
        pr_payload.number,
        pr_payload.headSha,
    )
    return ReviewTriggerAck(accepted=True, action="opened", delivery=delivery)


async def handleIssueCommentCreated(
    payload: dict[str, Any], delivery: str
) -> ReviewTriggerAck:
    """Dispatch a verified ``issue_comment`` ``created`` delivery to the workflow.

    The comment must mention ``@<app_slug> review`` (classification
    from :mod:`app.services.pr_issue_comment.helpers`). The PR state is
    fetched from the GitHub API; when the head moved since the last
    successful review, ``diffBaseSha`` narrows the diff to the commits
    pushed since (incremental re-review).

    Skip reasons: ``malformed_payload``, ``not_created``, ``not_a_pr``,
    ``self_comment``, ``missing_mention``, ``unauthorized_commenter``,
    ``review_not_configured``, ``unowned_installation``,
    ``repo_not_configured``, ``pr_fetch_failed``. Never raises for
    business outcomes.
    """
    try:
        trigger = validate_comment_payload(payload, delivery=delivery)
    except ValidationError:
        return ReviewTriggerAck(
            accepted=False,
            action="issue_comment",
            delivery=delivery,
            skip_reason="malformed_payload",
        )

    classified = classify_comment(payload, app_slug=settings.github_app_slug)
    if not classified.should_proceed:
        return ReviewTriggerAck(
            accepted=False,
            action="issue_comment",
            delivery=delivery,
            skip_reason=classified.skip_reason or "not_created",
        )

    if not reviewConfigured():
        return ReviewTriggerAck(
            accepted=False,
            action="issue_comment",
            delivery=delivery,
            skip_reason="review_not_configured",
        )

    async with async_session_maker() as session:
        user_id = await getUserIdFromInstallation(
            session, githubInstallationId=trigger.installation_id
        )
        if user_id is None:
            return ReviewTriggerAck(
                accepted=False,
                action="issue_comment",
                delivery=delivery,
                skip_reason="unowned_installation",
            )

        repo = await getRepoRecord(session, ghRepoId=trigger.gh_repo_id)
        if repo is None:
            return ReviewTriggerAck(
                accepted=False,
                action="issue_comment",
                delivery=delivery,
                skip_reason="repo_not_configured",
            )

        pr_ctx = createPRCtx(
            userId=UserId(user_id),
            installationId=InstallationId(trigger.installation_id),
            owner=RepoOwner(trigger.repo_owner),
            repo=RepoName(trigger.repo_name),
            prNumber=PRNumber(trigger.pr_number),
        )
        state = await getPrState(pr_ctx)
        if isinstance(state, GitHubPRError):
            log.info(
                "review.trigger: skip (pr fetch failed): delivery=%s "
                "gh_repo_id=%s number=%s cause=%s",
                delivery,
                trigger.gh_repo_id,
                trigger.pr_number,
                state.message,
            )
            return ReviewTriggerAck(
                accepted=False,
                action="issue_comment",
                delivery=delivery,
                skip_reason="pr_fetch_failed",
            )

        last_review = await loadLastReview(
            session, repoId=repo.id, prNumber=trigger.pr_number
        )
        diff_base_sha = effective_diff_base(
            api_base_sha=state.baseSha,
            api_head_sha=state.headSha,
            last_review=last_review,
        )

        llm_ctx = await resolveLlmCtx(session, userId=user_id)
        sandbox_ctx = buildSandboxCtx(
            userId=user_id, repoId=repo.id, repoName=repo.repo_name
        )

        workflow_input = buildReviewWorkflowInput(
            userId=UserId(user_id),
            ghRepoId=trigger.gh_repo_id,
            ghPrId=state.ghPrId,
            prNumber=PRNumber(trigger.pr_number),
            baseBranch=state.baseBranch,
            defaultBranch=trigger.default_branch,
            baseSha=state.baseSha,
            headBranch=state.headBranch,
            headSha=CommitId(state.headSha),
            author=state.author,
            title=state.title,
            body=state.body,
            status=_prStatusFromState(state.state, state.merged),
            prSize={
                "additions": state.additions,
                "deletions": state.deletions,
                "changedFiles": state.changedFiles,
            },
            githubInstallationId=InstallationId(trigger.installation_id),
            postToGithub=True,
            trigger="comment",
            diffBaseSha=CommitId(diff_base_sha) if diff_base_sha is not None else None,
        )
        workflow_ctx = ReviewWorkflowCtx(llmCtx=llm_ctx, sandboxCtx=sandbox_ctx)

        await addReaction(pr_ctx, trigger.comment_id)  # best-effort ack

        workflow_id = await dispatchReview(
            repoId=repo.id,
            prNumber=trigger.pr_number,
            headSha=state.headSha,
            workflowCtx=workflow_ctx,
            workflowInput=workflow_input,
        )

    log.info(
        "review.trigger: started workflow: delivery=%s workflow_id=%s "
        "gh_repo_id=%s number=%s head_sha=%s diff_base_sha=%s",
        delivery,
        workflow_id,
        trigger.gh_repo_id,
        trigger.pr_number,
        state.headSha,
        diff_base_sha,
    )
    return ReviewTriggerAck(accepted=True, action="issue_comment", delivery=delivery)


__all__ = [
    "PRPayload",
    "ReviewTriggerAck",
    "extractPrPayload",
    "handleIssueCommentCreated",
    "handlePullRequestOpened",
]
