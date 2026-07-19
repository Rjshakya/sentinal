"""DBOS durable workflows for the review pipeline.

This module replaces the old background-task pipeline with durable DBOS
workflows. The main review workflow is idempotent (keyed by
``review:{repo_id}:{pr_number}:{head_sha[:7]}``), checkpoints after every
step, and survives process restarts.

Design notes:

- All workflow inputs and outputs are Pydantic models so DBOS can serialize
  them into its system database.
- Non-deterministic / external operations live in ``@DBOS.step()`` functions.
  Database writes use ``@dbos_datasource.transaction()`` for exactly-once
  semantics.
- The E2B sandbox object is never passed between steps. Only the sandbox id
  travels through the workflow; each step reconnects by id.
- GitHub posting is a separate durable workflow so it can be retried / restarted
  independently without re-running the LLM agent.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, cast

from dbos import DBOS, SetWorkflowID
from githubkit_schemas.v2026_03_10.models import PullRequestReview
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.core.db import dbos_datasource
from app.core.github_app import installation_client
from app.core.llm import LLMProviderStr
from app.core.result import Err, Ok, Result
from app.core.sandbox import build_default_spec
from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.models.enums import PRStatus
from app.models.repo import Repo as RepoModel
from app.repositories import Repository
from app.services.agent.models import ReviewResult
from app.services.github.post_review import (
    GitHubPosterError,
    GitHubRateLimited,
    GitHubReviewPostFailed,
    post_review_to_github,
)
from app.services.review.agent import assemble_user_prompt, build_review_agent
from app.services.review.diff import fetch_diff
from app.services.review.errors import (
    DiffUnavailable,
    NoActiveSandbox,
    RepoNotFound,
    ReviewAgentCrashed,
    ReviewAgentReturnedNoStructuredResponse,
    ReviewPipelineError,
    SandboxConnectFailed,
)
from app.services.review.helpers import get_repo_path, parse_review_response
from app.services.review.steps.persist_summary import persist_review_summary
from app.services.review.steps.upsert_pr import upsert_pull_request

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Serializable workflow inputs / outputs                                      #
# --------------------------------------------------------------------------- #


class ReviewWorkflowInput(BaseModel):
    """Everything needed to durably review one PR."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    gh_repo_id: int
    pr_id: int
    pr_number: int
    branch: str
    base_sha: str
    head_sha: str
    head_branch: str
    author: str
    body: str
    title: str
    status: PRStatus
    llm_baseurl: str | None
    llm_api_key: str
    llm_model: str
    provider: LLMProviderStr
    post_to_github: bool
    github_installation_id: int | None = None


class PostReviewInput(BaseModel):
    """Input for the independent GitHub post workflow."""

    model_config = ConfigDict(frozen=True)

    repo_id: str
    pr_id: str
    commit_id: str
    github_installation_id: int
    repo_owner: str
    repo_name: str
    pr_number: int
    review: ReviewResult


class ReviewRunResult(BaseModel):
    """What the main review workflow returns."""

    model_config = ConfigDict(frozen=True)

    pr_id: str
    commit_id: str
    review: ReviewResult


class PostReviewResult(BaseModel):
    """What the GitHub post workflow returns."""

    model_config = ConfigDict(frozen=True)

    posted: bool
    github_review_id: int | None = None
    error: str | None = None


class RepoSnapshot(BaseModel):
    """Serializable subset of :class:`Repo`."""

    model_config = ConfigDict(frozen=True)

    id: str
    repo_name: str
    repo_owner: str


class ResolvedSandbox(BaseModel):
    """Serializable subset of a resolved sandbox."""

    model_config = ConfigDict(frozen=True)

    sandbox_id: str
    sandbox_name: str


# --------------------------------------------------------------------------- #
# DBOS steps / transactions                                                   #
# --------------------------------------------------------------------------- #


def _e2b_spec() -> E2BSandboxSpec:
    """Reconstruct the active E2B spec from settings.

    This is deterministic at workflow runtime because settings are loaded
    once on process startup and never change during a workflow.
    """
    provider: Literal["e2b", "daytona"] = (
        "daytona" if settings.sandbox_provider == "daytona" else "e2b"
    )
    return cast(E2BSandboxSpec, build_default_spec(provider))


@dbos_datasource.transaction()
async def resolve_repo_tx(gh_repo_id: int) -> Result[RepoSnapshot, RepoNotFound]:
    """Durable transaction: find the local repo row by GitHub repo id."""
    session = dbos_datasource.sql_session()
    repo = await Repository(RepoModel, session).find_by_field(
        RepoModel.github_repo_id, gh_repo_id
    )
    if repo is None:
        return Err(RepoNotFound(repo_id=str(gh_repo_id)))
    return Ok(
        RepoSnapshot(
            id=repo.id,
            repo_name=repo.repo_name,
            repo_owner=repo.repo_owner,
        )
    )


@DBOS.step(retries_allowed=True, max_attempts=3)
async def resolve_sandbox_step(
    *, user_id: str, repo_id: str
) -> Result[ResolvedSandbox, NoActiveSandbox | SandboxConnectFailed]:
    """Durable step: find the active sandbox row and connect to E2B.

    We only return the sandbox id/name; the E2B handle itself is not
    serializable, so each step reconnects by id.
    """
    session = dbos_datasource.sql_session()
    from app.models.sandbox import Sandbox as SandboxModel

    sb_record = await Repository(SandboxModel, session).find_by_field(
        SandboxModel.repo_id, repo_id
    )
    if sb_record is None:
        return Err(NoActiveSandbox(user_id=user_id, repo_id=repo_id))

    spec = _e2b_spec()
    try:
        connected = await E2BSandbox.connect(
            sandbox_id=sb_record.id,
            sandbox_name=sb_record.sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        log.exception(
            "failed to connect sandbox: user_id=%s repo_id=%s sandbox_id=%s",
            user_id,
            repo_id,
            sb_record.id,
        )
        return Err(
            SandboxConnectFailed(
                user_id=user_id,
                repo_id=repo_id,
                sandbox_id=sb_record.id,
                cause=f"{type(exc).__name__}: {exc}",
            )
        )
    return Ok(
        ResolvedSandbox(
            sandbox_id=connected.id,
            sandbox_name=sb_record.sandbox_name,
        )
    )


@DBOS.step()
async def fetch_diff_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
) -> Result[str, DiffUnavailable]:
    """Durable step: reconnect to the sandbox and fetch the unified diff."""
    spec = _e2b_spec()
    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        return Err(
            DiffUnavailable(
                repo_id=repo_id,
                base_sha=base_sha,
                head_sha=head_sha,
                cause=f"failed to reconnect sandbox: {type(exc).__name__}: {exc}",
            )
        )

    try:
        return await fetch_diff(
            sandbox=sandbox,
            repo_id=repo_id,
            repo_path_str=get_repo_path(repo_name),
            pr_number=pr_number,
            base_sha=base_sha,
            head_sha=head_sha,
        )
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after diff fetch")


@dbos_datasource.transaction()
async def upsert_pull_request_tx(
    *,
    repo_id: str,
    github_pr_id: int,
    number: int,
    base_branch: str,
    base_sha: str,
    head_branch: str,
    head_sha: str,
    title: str,
    body: str,
    author: str,
    status: PRStatus,
) -> str:
    """Durable transaction: insert or update the PullRequest row. Returns pr_id."""
    session = dbos_datasource.sql_session()
    pr = await upsert_pull_request(
        session,
        repo_id=repo_id,
        github_pr_id=github_pr_id,
        number=number,
        base_branch=base_branch,
        base_sha=base_sha,
        head_branch=head_branch,
        head_sha=head_sha,
        title=title,
        body=body,
        author=author,
        status=status,
    )
    return pr.id


@DBOS.step(retries_allowed=True, max_attempts=2)
async def invoke_review_agent_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    repo_name: str,
    user_id: str,
    pr_number: int,
    head_sha: str,
    provider: LLMProviderStr,
    llm_baseurl: str | None,
    llm_api_key: str,
    llm_model: str,
) -> Result[ReviewResult, ReviewAgentCrashed | ReviewAgentReturnedNoStructuredResponse]:
    """Durable step: reconnect to the sandbox, build the agent, and invoke it.

    This is the most expensive step in the pipeline. Wrapping it with DBOS
    means a crash mid-invocation resumes from the completed invocation without
    re-running the LLM.
    """
    spec = _e2b_spec()
    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        return Err(
            ReviewAgentCrashed(
                cause=f"failed to reconnect sandbox for agent: {type(exc).__name__}: {exc}"
            )
        )

    try:
        agent = build_review_agent(
            sandbox=sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            provider=provider,
            llm_baseurl=llm_baseurl,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
        )
        user_prompt = assemble_user_prompt(
            repo_name=repo_name,
            repo_id=repo_id,
            user_id=user_id,
            pr_number=pr_number,
        )
        log.info(
            "invoking review agent: repo=%s user=%s pr_number=%s",
            repo_name,
            user_id,
            pr_number,
        )
        try:
            raw = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_prompt}]}
            )
        except Exception as exc:
            log.exception("review agent crashed: repo=%s pr_number=%s", repo_name, pr_number)
            return Err(
                ReviewAgentCrashed(cause=f"{type(exc).__name__}: {exc}")
            )
        return parse_review_response(raw)
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after agent invocation")


@dbos_datasource.transaction()
async def persist_review_summary_tx(
    *,
    pr_id: str,
    commit_id: str,
    result: ReviewResult,
) -> str:
    """Durable transaction: persist the review summary row. Returns summary_id."""
    session = dbos_datasource.sql_session()
    summary = await persist_review_summary(
        session,
        pr_id=pr_id,
        commit_id=commit_id,
        result=result,
    )
    return str(summary.id)


@dbos_datasource.transaction()
async def persist_code_comments_tx(
    *,
    pr_id: str,
    commit_id: str,
    comments: list[dict[str, Any]],
) -> list[str]:
    """Durable transaction: persist the code comment rows. Returns ids."""
    from app.services.agent.models import CodeCommentDraft
    from app.services.review.helpers import map_drafts_to_comment_rows

    session = dbos_datasource.sql_session()
    drafts = [CodeCommentDraft.model_validate(c) for c in comments]
    rows = map_drafts_to_comment_rows(
        pr_id=pr_id, commit_id=commit_id, comments=drafts
    )
    if not rows:
        return []
    session.add_all(rows)
    await session.flush()
    for row in rows:
        await session.refresh(row)
    return [row.id for row in rows]


@DBOS.step()
async def stop_sandbox_step(
    *, sandbox_id: str, sandbox_name: str, repo_id: str, user_id: str
) -> None:
    """Durable step: stop the E2B sandbox. Failures are logged, not raised."""
    spec = _e2b_spec()
    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
        await sandbox.stop()
    except Exception:
        log.exception("failed to stop sandbox: sandbox_id=%s", sandbox_id)


# --------------------------------------------------------------------------- #
# GitHub post workflow                                                        #
# --------------------------------------------------------------------------- #


class RetryableGitHubPostError(Exception):
    """Raised when a GitHub post fails with a transient (retryable) error."""

    def __init__(self, cause: str, status_code: int | None = None):
        self.cause = cause
        self.status_code = status_code
        super().__init__(cause)


class NonRetryableGitHubPostError(Exception):
    """Raised when a GitHub post fails with a non-retryable error (4xx)."""

    def __init__(self, error: GitHubPosterError):
        self.error = error
        super().__init__(str(error))


def _is_retryable_github_error(error: GitHubPosterError) -> bool:
    """Return True if the GitHub post error should be retried.

    Retryable: 5xx, 429 rate limited.
    Not retryable: 401/403 auth, 404 not found.
    """
    if isinstance(error, GitHubRateLimited):
        return True
    if isinstance(error, GitHubReviewPostFailed):
        if error.status_code is not None and error.status_code >= 500:
            return True
        if error.status_code == 429:
            return True
    return False


def _raise_github_post_error(error: GitHubPosterError) -> None:
    """Convert a GitHubPosterError into an exception for DBOS retry handling."""
    if _is_retryable_github_error(error):
        raise RetryableGitHubPostError(
            cause=getattr(error, "cause", str(error)),
            status_code=getattr(error, "status_code", None),
        )
    raise NonRetryableGitHubPostError(error)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=lambda exc: isinstance(exc, RetryableGitHubPostError),
)
async def post_review_to_github_step(
    input: PostReviewInput,
) -> PullRequestReview:
    """Durable step: post the review to GitHub with automatic retries.

    Raises RetryableGitHubPostError on transient failures so DBOS retries.
    Raises NonRetryableGitHubPostError on 4xx so the workflow can complete.
    """
    github_client = installation_client(input.github_installation_id)
    result = await post_review_to_github(
        github_client=github_client,
        owner=input.repo_owner,
        repo=input.repo_name,
        pr_number=input.pr_number,
        commit_id=input.commit_id,
        result=input.review,
    )
    if isinstance(result, Ok):
        return result.value
    _raise_github_post_error(result.error)
    # _raise_github_post_error always raises; this satisfies the type checker.
    raise AssertionError("unreachable")


@DBOS.workflow()
async def post_review_to_github_workflow(
    input: PostReviewInput,
) -> PostReviewResult:
    """Durable workflow: post a review to GitHub.

    Separated from the main review workflow so it can be retried independently
    via DBOS Conductor / the admin server without re-running the LLM.
    """
    try:
        review = await post_review_to_github_step(input)
        log.info(
            "posted review to GitHub: owner=%s repo=%s pr_number=%s review_id=%s",
            input.repo_owner,
            input.repo_name,
            input.pr_number,
            review.id,
        )
        return PostReviewResult(posted=True, github_review_id=review.id)
    except RetryableGitHubPostError as exc:
        log.warning(
            "github post failed after retries: owner=%s repo=%s pr_number=%s cause=%s",
            input.repo_owner,
            input.repo_name,
            input.pr_number,
            exc.cause,
        )
        return PostReviewResult(posted=False, error=exc.cause)
    except NonRetryableGitHubPostError as exc:
        log.warning(
            "github post non-retryable error: owner=%s repo=%s pr_number=%s error=%s",
            input.repo_owner,
            input.repo_name,
            input.pr_number,
            exc.error,
        )
        return PostReviewResult(posted=False, error=str(exc.error))


# --------------------------------------------------------------------------- #
# Main review workflow                                                        #
# --------------------------------------------------------------------------- #


@DBOS.workflow()
async def review_workflow(
    input: ReviewWorkflowInput,
) -> Result[ReviewRunResult, ReviewPipelineError]:
    """Durable workflow: review one PR end-to-end.

    The workflow is deterministic and only orchestrates DBOS steps. It returns
    a Result so business errors (repo not found, no sandbox, etc.) do not mark
    the workflow as ERROR in DBOS.
    """
    repo_result = await resolve_repo_tx(input.gh_repo_id)
    if isinstance(repo_result, Err):
        return Err(repo_result.error)
    repo = repo_result.value

    sandbox_result = await resolve_sandbox_step(
        user_id=input.user_id, repo_id=repo.id
    )
    if isinstance(sandbox_result, Err):
        return Err(sandbox_result.error)
    sandbox = sandbox_result.value

    try:
        diff_result = await fetch_diff_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            repo_name=repo.repo_name,
            user_id=input.user_id,
            pr_number=input.pr_number,
            base_sha=input.base_sha,
            head_sha=input.head_sha,
        )
        if isinstance(diff_result, Err):
            return Err(diff_result.error)

        pr_id = await upsert_pull_request_tx(
            repo_id=repo.id,
            github_pr_id=input.pr_id,
            number=input.pr_number,
            base_branch=input.branch,
            base_sha=input.base_sha,
            head_branch=input.head_branch,
            head_sha=input.head_sha,
            title=input.title,
            body=input.body,
            author=input.author,
            status=input.status,
        )

        review_result = await invoke_review_agent_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            repo_name=repo.repo_name,
            user_id=input.user_id,
            pr_number=input.pr_number,
            head_sha=input.head_sha,
            provider=input.provider,
            llm_baseurl=input.llm_baseurl,
            llm_api_key=input.llm_api_key,
            llm_model=input.llm_model,
        )
        if isinstance(review_result, Err):
            return Err(review_result.error)
        review = review_result.value

        await persist_review_summary_tx(
            pr_id=pr_id,
            commit_id=input.head_sha,
            result=review,
        )
        await persist_code_comments_tx(
            pr_id=pr_id,
            commit_id=input.head_sha,
            comments=[c.model_dump(mode="json") for c in review.comments],
        )

        if input.post_to_github and input.github_installation_id is not None:
            post_input = PostReviewInput(
                repo_id=repo.id,
                pr_id=pr_id,
                commit_id=input.head_sha,
                github_installation_id=input.github_installation_id,
                repo_owner=repo.repo_owner,
                repo_name=repo.repo_name,
                pr_number=input.pr_number,
                review=review,
            )
            post_workflow_id = (
                f"post:{repo.id}:{input.pr_number}:{input.head_sha[:7]}"
            )
            with SetWorkflowID(post_workflow_id):
                await DBOS.start_workflow_async(post_review_to_github_workflow, post_input)

        return Ok(
            ReviewRunResult(
                pr_id=pr_id,
                commit_id=input.head_sha,
                review=review,
            )
        )
    finally:
        await stop_sandbox_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            user_id=input.user_id,
        )


__all__ = [
    "PostReviewInput",
    "PostReviewResult",
    "ReviewRunResult",
    "ReviewWorkflowInput",
    "post_review_to_github_workflow",
    "review_workflow",
]
