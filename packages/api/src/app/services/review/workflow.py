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
- Steps **raise** typed exceptions on failure (see
  :mod:`app.services.review.errors`). Transient failures — LLM rate
  limits / timeouts, E2B connect blips — raise
  :class:`TransientStepError` subclasses, which DBOS retries via
  ``should_retry=lambda exc: isinstance(exc, TransientStepError)``.
  Business outcomes — repo not indexed, agent returned no structured
  response — raise plain :class:`StepError` subclasses and are not
  retried.
- The E2B sandbox object is never passed between steps. Only the sandbox
  id travels through the workflow; each step reconnects by id.
- GitHub posting is a separate durable workflow so it can be retried /
  restarted independently without re-running the LLM agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal, cast

from dbos import DBOS, SetWorkflowID
from githubkit_schemas.v2026_03_10.models import PullRequestReview
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict
from sqlmodel import select

from app.core.config import settings
from app.core.db import async_session_maker, dbos_datasource
from app.core.github_app import installation_client
from app.core.llm import LLMProviderStr, build_chat_model
from app.core.llm_callbacks import make_llm_io_handler
from app.core.result import Ok
from app.core.sandbox import build_default_spec
from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.models.enums import PRStatus
from app.models.repo import Repo as RepoModel
from app.services.agent.models import (
    CorrectnessComments,
    ReviewResult,
    SecurityComments,
    StyleComments,
)
from app.services.github.post_review import (
    GitHubPosterError,
    GitHubRateLimited,
    GitHubReviewPostFailed,
    post_review_to_github,
)
from app.services.review.agent import (
    assemble_user_prompt,
    build_orchestrator_agent,
    build_review_agents,
    build_review_subagents,
    combine_review_results,
    extract_last_ai_text,
    verdict_for,
)
from app.services.review.diff import fetch_diff, parse_and_write_diff_json
from app.services.review.errors import (
    NoActiveSandboxError,
    RepoNotFoundError,
    ReviewAgentCrashedError,
    ReviewAgentRateLimitedError,
    SandboxConnectError,
    TransientStepError,
    extract_retry_after_seconds,
    is_llm_transient_error,
)
from app.services.review.helpers import get_repo_path
from app.services.review.hunk_map import HunkMap, ParsedDiff, filter_drafts
from app.services.review.steps.persist_summary import persist_review_summary
from app.services.review.steps.upsert_pr import upsert_pull_request
from app.services.review.tools import make_get_diff_tool

log = logging.getLogger(__name__)

_SHOULD_RETRY_TRANSIENT: object = lambda exc: isinstance(exc, TransientStepError)
"""Shared ``should_retry`` predicate for steps: retry on any
:class:`TransientStepError`, fail on plain :class:`StepError`."""


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
async def resolve_repo_tx(gh_repo_id: int) -> RepoSnapshot:
    """Durable transaction: find the local repo row by GitHub repo id.

    Raises:
        RepoNotFoundError: no row matches ``gh_repo_id``. This is a
            business outcome and is not retried.
    """
    session = dbos_datasource.sql_session()
    result = await session.execute(
        select(RepoModel).where(RepoModel.github_repo_id == gh_repo_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise RepoNotFoundError(repo_id=str(gh_repo_id))
    return RepoSnapshot(
        id=repo.id,
        repo_name=repo.repo_name,
        repo_owner=repo.repo_owner,
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def resolve_sandbox_step(*, user_id: str, repo_id: str) -> ResolvedSandbox:
    """Durable step: find the active sandbox row and connect to E2B.

    Raises:
        NoActiveSandboxError: no row matches ``repo_id``. Business
            outcome — not retried.
        SandboxConnectError: the row exists but ``E2BSandbox.connect``
            raised. :class:`TransientStepError` — DBOS retries.
    """
    from app.models.sandbox import Sandbox as SandboxModel

    async with async_session_maker() as session:
        result = await session.exec(
            select(SandboxModel).where(SandboxModel.repo_id == repo_id)
        )
        sb_record = result.one_or_none()
    if sb_record is None:
        raise NoActiveSandboxError(user_id=user_id, repo_id=repo_id)

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
        log.warning(
            "sandbox connect failed (will retry): user_id=%s repo_id=%s "
            "sandbox_id=%s cause=%s: %s",
            user_id,
            repo_id,
            sb_record.id,
            type(exc).__name__,
            exc,
        )
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sb_record.id,
            cause=f"{type(exc).__name__}: {exc}",
        ) from exc
    return ResolvedSandbox(
        sandbox_id=connected.id,
        sandbox_name=sb_record.sandbox_name,
    )


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
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
) -> str:
    """Durable step: reconnect to the sandbox and fetch the unified diff.

    Raises:
        SandboxConnectError: reconnect to E2B failed.
            :class:`TransientStepError` — DBOS retries.
        DiffUnavailableError: ``git diff`` (or ``mkdir``) returned a
            non-zero exit code. Business outcome — not retried.
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
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sandbox_id,
            cause=f"failed to reconnect sandbox for diff: {type(exc).__name__}: {exc}",
        ) from exc

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


@DBOS.step()
async def parse_diff_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
) -> ParsedDiff:
    """Durable step: read ``file.diff``, parse, write ``diff.json``.

    Connects to the E2B sandbox, calls
    :func:`app.services.review.diff.parse_and_write_diff_json`, and
    returns the parsed :data:`ParsedDiff` so the workflow can pass it
    into the agent step and the server-side filter without re-reading
    the sandbox.

    The sandbox is stopped in ``finally`` so a parse failure does not
    leave the connection open.

    Raises:
        SandboxConnectError: failed to reconnect to the sandbox.
        DiffUnavailableError: ``file.diff`` is missing, empty, or
            unparseable.
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
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sandbox_id,
            cause=f"failed to reconnect sandbox for diff parse: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        return await parse_and_write_diff_json(
            sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            repo_id=repo_id,
            base_sha=base_sha,
        )
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after diff parse")


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


# Deprecated: replaced by ``invoke_review_agent_step`` (singular) below,
# which runs the new orchestrator-with-subagents design. This old
# parallel-fanout step is kept as a one-line revert path — the call
# site in ``review_workflow`` was switched to the singular step. Do
# not modify this function. If the new design needs a rollback, change
# the call site in ``review_workflow`` back to this name.
@DBOS.step(
    retries_allowed=True,
    max_attempts=2,
    # should_retry=_SHOULD_RETRY_TRANSIENT,
    backoff_rate=2,
)
async def invoke_review_agents_step(
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
) -> ReviewResult:
    """Durable step: run the four review agents in parallel and combine.

    This replaces the single orchestrator-based agent. The fan-out:

    1. Reconnects to the E2B sandbox (one connection for the step).
    2. Builds the chat model and the four review agents (summary,
       security, correctness, style) — all sharing the same
       ``AsyncE2BSandbox`` backend and the same shared tool
       (``get_diff``). Comment-line validation is prompt-driven:
       each specialist reads ``diff.json`` (the hunk map written
       by :func:`app.services.review.diff.parse_and_write_diff_json`)
       and self-checks / re-anchors its draft anchors before
       emitting them.
    3. ``asyncio.gather`` runs all four ``agent.ainvoke`` calls
       concurrently against the same sandbox.
    4. Each structured-output agent (security / correctness / style)
       returns a ``structured_response`` payload. The summary agent
       uses no ``response_format`` and its last AI message content is
       the markdown summary.
    5. :func:`combine_review_results` merges the four results
       deterministically into a single :class:`ReviewResult`.

    The whole step is a single DBOS checkpoint: a crash mid-fan-out
    resumes from the cached result, so transient failures don't
    re-run the LLM. The sandbox is stopped in a ``finally`` so a
    parse / combine failure does not leak the connection.

    ``hunk_map`` is the parsed diff structure from
    :func:`app.services.review.hunk_map.parse_hunk_map`. The
    specialist agents re-derive what they need from ``diff.json``;
    the server-side :func:`app.services.review.hunk_map.filter_drafts`
    (called by the workflow after this step) is the final backstop
    that drops any draft whose anchor is not in ``hunk_map``.

    Raises:
        SandboxConnectError: reconnect to E2B failed.
            :class:`TransientStepError` — DBOS retries.
        ReviewAgentRateLimitedError: any of the four agents returned
            429 / 5xx / timeout. :class:`TransientStepError` — DBOS
            retries up to ``max_attempts`` times.
        ReviewAgentCrashedError: any other exception from
            ``agent.ainvoke`` — business outcome, not retried.
        ReviewAgentReturnedNoStructuredResponseError: any of the
            three structured agents finished without
            ``structured_response``, or the summary agent's last AI
            message had no string content. Business outcome, not
            retried.
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
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sandbox_id,
            cause=f"failed to reconnect sandbox for agents: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        (
            summary_agent,
            security_agent,
            correctness_agent,
            style_agent,
            _,
            _,
        ) = build_review_agents(
            sandbox=sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            provider=provider,
            llm_baseurl=llm_baseurl,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            repo_id=repo_id,
            repo_name=repo_name,
            workflow_id=DBOS.workflow_id,
        )
        user_prompt = assemble_user_prompt(
            repo_name=repo_name,
            repo_id=repo_id,
            user_id=user_id,
            pr_number=pr_number,
        )
        prompt_payload = {"messages": [{"role": "user", "content": user_prompt}]}
        log.info(
            "invoking review agents (parallel): repo=%s user=%s pr_number=%s",
            repo_name,
            user_id,
            pr_number,
        )

        try:
            (
                summary_raw,
                security_raw,
                correctness_raw,
                style_raw,
            ) = await asyncio.gather(
                summary_agent.ainvoke(prompt_payload),
                security_agent.ainvoke(prompt_payload),
                correctness_agent.ainvoke(prompt_payload),
                style_agent.ainvoke(prompt_payload),
            )
        except Exception as exc:
            if is_llm_transient_error(exc):
                wait = extract_retry_after_seconds(exc)
                log.warning(
                    "review agents transient: repo=%s pr_number=%s wait_s=%s cause=%s",
                    repo_name,
                    pr_number,
                    wait,
                    exc,
                )
                raise ReviewAgentRateLimitedError(
                    cause=f"{type(exc).__name__}: {exc}",
                    retry_after_seconds=wait,
                ) from exc

            log.exception(
                "review agents crashed: repo=%s pr_number=%s",
                repo_name,
                pr_number,
            )
            raise ReviewAgentCrashedError(cause=f"{type(exc).__name__}: {exc}") from exc

        # Parse each result. ``parse_review_response`` is gone; the
        # three structured agents return ``structured_response`` and
        # the summary agent returns its last AI message content.
        try:
            summary_markdown = extract_last_ai_text(summary_raw)
            security = SecurityComments.model_validate(
                security_raw["structured_response"]
            )
            correctness = CorrectnessComments.model_validate(
                correctness_raw["structured_response"]
            )
            style = StyleComments.model_validate(style_raw["structured_response"])
        except KeyError as exc:
            from app.services.agent.helpers import extract_message_kinds
            from app.services.review.errors import (
                ReviewAgentReturnedNoStructuredResponseError,
            )

            raise ReviewAgentReturnedNoStructuredResponseError(
                message_kinds=extract_message_kinds(
                    (security_raw or {}).get("messages")
                )
            ) from exc
        except Exception as exc:
            from app.services.agent.helpers import extract_message_kinds
            from app.services.review.errors import (
                ReviewAgentReturnedNoStructuredResponseError,
            )

            log.exception(
                "review agents returned unparseable output: repo=%s pr_number=%s",
                repo_name,
                pr_number,
            )
            raise ReviewAgentReturnedNoStructuredResponseError(
                message_kinds=extract_message_kinds(
                    (security_raw or {}).get("messages")
                )
            ) from exc

        return combine_review_results(
            summary_markdown=summary_markdown,
            security=security,
            correctness=correctness,
            style=style,
        )
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after agent invocation")


@DBOS.step(
    retries_allowed=True,
    max_attempts=2,
    backoff_rate=2,
)
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
) -> ReviewResult:
    """Durable step: run the orchestrator-with-subagents review and combine.

    This is the production review step. It replaces
    :func:`invoke_review_agents_step` (plural). The flow:

    1. Reconnects to the E2B sandbox (one connection for the step).
    2. Builds four review subagents (summary, security, correctness,
       style) — each with its own chat model and its own per-agent
       LLM I/O callback.
    3. Builds the root deep-agent (the orchestrator) with the four
       subagents attached via ``subagents=[]`` and a chat model
       tagged ``agent="orchestrator"``. The orchestrator's
       ``response_format`` is :class:`ReviewResult` directly.
    4. ``ainvoke``s the orchestrator once. The orchestrator
       delegates to the four subagents in turn, absorbs any
       subagent failure (substituting an empty result), and emits
       a single ``ReviewResult`` as its structured response.
    5. Validates the structured response and overwrites the
       ``verdict`` field with the deterministic value
       :func:`verdict_for` (the orchestrator is told to set
       ``"COMMENT"``; the real verdict is recomputed here from the
       merged comments).

    Failure semantics:

    - The orchestrator absorbs subagent failures (its prompt tells
      it to substitute an empty result and continue). Therefore a
      single subagent's failure does NOT cause a DBOS step retry.
    - Orchestrator-level failures (LLM 5xx / 429 / timeout) raise
      :class:`ReviewAgentRateLimitedError`, which is a
      :class:`TransientStepError`; DBOS retries up to
      ``max_attempts`` times.
    - Orchestrator crashes (anything else) raise
      :class:`ReviewAgentCrashedError` (not retried).
    - A missing or unparseable structured response raises
      :class:`ReviewAgentReturnedNoStructuredResponseError` (not
      retried).

    The whole step is a single DBOS checkpoint: a crash mid-fanout
    resumes from the cached result, so transient failures don't
    re-run the LLM. The sandbox is stopped in a ``finally`` so a
    parse / combine failure does not leak the connection.

    ``hunk_map`` is the parsed diff structure from
    :func:`app.services.review.hunk_map.parse_hunk_map`. Each
    specialist subagent reads the parallel ``diff.json`` file (also
    written by :func:`app.services.review.diff.parse_and_write_diff_json`)
    directly via the deepagents backend's ``read_file`` to
    self-validate and re-anchor its ``(file, line, side)`` anchors
    before emitting :class:`CodeCommentDraft` entries. The
    server-side :func:`app.services.review.hunk_map.filter_drafts`
    (called by the workflow after this step) is the final backstop.

    Raises:
        SandboxConnectError: reconnect to E2B failed.
            :class:`TransientStepError` — DBOS retries.
        ReviewAgentRateLimitedError: the orchestrator returned
            429 / 5xx / timeout. :class:`TransientStepError` —
            DBOS retries up to ``max_attempts`` times.
        ReviewAgentCrashedError: any other exception from
            ``orchestrator.ainvoke`` — business outcome, not
            retried.
        ReviewAgentReturnedNoStructuredResponseError: the
            orchestrator finished without ``structured_response``,
            or the response could not be validated as
            :class:`ReviewResult`. Business outcome, not retried.
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
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sandbox_id,
            cause=(
                f"failed to reconnect sandbox for orchestrator: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    try:
        orchestrator_model = build_chat_model(
            provider=provider,
            base_url=llm_baseurl,
            api_key=llm_api_key,
            model=llm_model,
            headers={"cf-aig-gateway-id": "sentinal-ai-gateway"},
            callbacks=make_llm_io_handler(
                agent_name="orchestrator",
                repo_name=repo_name,
                repo_id=repo_id,
                pr_number=pr_number,
                head_sha=head_sha,
                workflow_id=DBOS.workflow_id,
                model=llm_model,
            ),
        )

        subagents = build_review_subagents(
            sandbox=sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            model=orchestrator_model,
        )

        orchestrator = build_orchestrator_agent(
            model=orchestrator_model,
            backend=cast(Any, _orchestrator_backend(sandbox)),
            subagents=subagents,
            tools=_orchestrator_tools(
                sandbox=sandbox,
                pr_number=pr_number,
                head_sha=head_sha,
            ),
        )
        user_prompt = assemble_user_prompt(
            repo_name=repo_name,
            repo_id=repo_id,
            user_id=user_id,
            pr_number=pr_number,
        )
        prompt_payload = {"messages": [{"role": "user", "content": user_prompt}]}
        log.info(
            "invoking review orchestrator: repo=%s user=%s pr_number=%s",
            repo_name,
            user_id,
            pr_number,
        )

        try:
            result = await orchestrator.ainvoke(prompt_payload)
        except Exception as exc:
            if is_llm_transient_error(exc):
                wait = extract_retry_after_seconds(exc)
                log.warning(
                    "review orchestrator transient: repo=%s pr_number=%s "
                    "wait_s=%s cause=%s",
                    repo_name,
                    pr_number,
                    wait,
                    exc,
                )
                raise ReviewAgentRateLimitedError(
                    cause=f"{type(exc).__name__}: {exc}",
                    retry_after_seconds=wait,
                ) from exc

            log.exception(
                "review orchestrator crashed: repo=%s pr_number=%s",
                repo_name,
                pr_number,
            )
            raise ReviewAgentCrashedError(cause=f"{type(exc).__name__}: {exc}") from exc

        if not isinstance(result, dict) or "structured_response" not in result:
            from app.services.agent.helpers import extract_message_kinds
            from app.services.review.errors import (
                ReviewAgentReturnedNoStructuredResponseError,
            )

            log.exception(
                "review orchestrator returned no structured_response: "
                "repo=%s pr_number=%s",
                repo_name,
                pr_number,
            )
            raise ReviewAgentReturnedNoStructuredResponseError(
                message_kinds=extract_message_kinds((result or {}).get("messages"))
            )

        try:
            review = ReviewResult.model_validate(result["structured_response"])
        except Exception as exc:
            from app.services.agent.helpers import extract_message_kinds
            from app.services.review.errors import (
                ReviewAgentReturnedNoStructuredResponseError,
            )

            log.exception(
                "review orchestrator returned unparseable output: repo=%s pr_number=%s",
                repo_name,
                pr_number,
            )
            raise ReviewAgentReturnedNoStructuredResponseError(
                message_kinds=extract_message_kinds((result or {}).get("messages"))
            ) from exc

        # The orchestrator's LLM is told to set ``verdict="COMMENT"``;
        # we overwrite with the deterministic value derived from the
        # actual comments. This is the only place the verdict is
        # computed; the LLM's value is discarded.
        review.verdict = verdict_for(review.comments)
        return review
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after orchestrator invocation")


# --------------------------------------------------------------------------- #
# Orchestrator helpers                                                          #
# --------------------------------------------------------------------------- #


def _orchestrator_backend(sandbox: E2BSandbox):  # type: ignore[no-untyped-def]
    """Wrap the E2B sandbox as a deepagents AsyncE2BSandbox backend.

    Imported lazily so the singular step file doesn't pay the
    import cost on every step invocation outside this function.
    """
    from langchain_e2b import AsyncE2BSandbox

    return AsyncE2BSandbox(sandbox=sandbox.sandbox, workdir="/home/user")


def _orchestrator_tools(
    *,
    sandbox: E2BSandbox,
    pr_number: int,
    head_sha: str,
) -> list[BaseTool]:
    """Return the orchestrator's own tools (same as a subagent's).

    The orchestrator uses ``get_diff`` to read the diff first.
    Comment-line validation is prompt-driven: any anchor the
    orchestrator (or its subagents) cares to inspect is read
    directly from ``/home/user/tmp/{pr_number}/{head_sha}/diff.json``
    in the sandbox via the deepagents backend's ``read_file`` tool.
    The orchestrator does not own a comment-anchor validation tool
    of its own. Subagents get the same tool independently (each in
    its own sandbox view).
    """
    return [
        make_get_diff_tool(sandbox=sandbox, pr_number=pr_number, head_sha=head_sha),
    ]


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
    rows = map_drafts_to_comment_rows(pr_id=pr_id, commit_id=commit_id, comments=drafts)
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
    """Durable step: stop the E2B sandbox. Failures are logged, not raised.

    This step is best-effort: stopping is idempotent on the E2B side and
    a failure here would only delay (not prevent) cleanup. The outer
    workflow's ``finally`` block calls it; we never want a cleanup
    failure to mask the real outcome of the review.
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
async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
    """Durable workflow: review one PR end-to-end.

    Body is a straight-line sequence of step calls. Each step raises a
    typed exception on failure; transient ones are retried by DBOS via
    :data:`_SHOULD_RETRY_TRANSIENT`. The workflow itself does not
    translate exceptions into result types — the DBOS workflow record
    is marked as ERROR on unhandled exceptions, and the typed exception
    propagates to any caller awaiting the result.

    The :func:`stop_sandbox_step` cleanup runs in a ``finally`` block
    that covers every step that follows a successful
    :func:`resolve_sandbox_step`. If ``resolve_sandbox_step`` itself
    raises, there is no connected sandbox to stop.
    """
    repo = await resolve_repo_tx(input.gh_repo_id)
    sandbox = await resolve_sandbox_step(user_id=input.user_id, repo_id=repo.id)

    try:
        await fetch_diff_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            repo_name=repo.repo_name,
            user_id=input.user_id,
            pr_number=input.pr_number,
            base_sha=input.base_sha,
            head_sha=input.head_sha,
        )

        parsed_diff = await parse_diff_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            user_id=input.user_id,
            pr_number=input.pr_number,
            base_sha=input.base_sha,
            head_sha=input.head_sha,
        )
        hunk_map: HunkMap = {
            file_name: {
                "RIGHT": set(entry["RIGHT"]),
                "LEFT": set(entry["LEFT"]),
            }
            for file_name, entry in parsed_diff["files"].items()
        }

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

        review = await invoke_review_agents_step(
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

        filtered_review = filter_drafts(review, hunk_map)

        await persist_review_summary_tx(
            pr_id=pr_id,
            commit_id=input.head_sha,
            result=filtered_review,
        )
        await persist_code_comments_tx(
            pr_id=pr_id,
            commit_id=input.head_sha,
            comments=[c.model_dump(mode="json") for c in filtered_review.comments],
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
                review=filtered_review,
            )
            post_workflow_id = f"post:{repo.id}:{input.pr_number}:{input.head_sha[:7]}"
            with SetWorkflowID(post_workflow_id):
                await DBOS.start_workflow_async(
                    post_review_to_github_workflow, post_input
                )

        return ReviewRunResult(
            pr_id=pr_id,
            commit_id=input.head_sha,
            review=filtered_review,
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
