"""Main review durable workflow.

This module owns the top-level :func:`review_workflow` DBOS workflow
that sequences the review pipeline. Every step / transaction is
implemented in :mod:`app.services.review.steps`; every shared
Pydantic type is in :mod:`app.services.review.workflow_types`; the
shared internal helpers (``_e2b_spec``, ``_SHOULD_RETRY_TRANSIENT``)
are in :mod:`app.services.review._internal`. The GitHub post
workflow is in :mod:`app.services.github.workflow`.

Design notes:

- All workflow inputs and outputs are Pydantic models so DBOS can
  serialise them into its system database.
- Transient failures (LLM rate limits / timeouts, E2B connect blips)
  raise :class:`TransientStepError` subclasses, which DBOS retries
  via :data:`app.services.review._internal._SHOULD_RETRY_TRANSIENT`.
  Business outcomes raise plain :class:`StepError` subclasses and are
  not retried.
- The E2B sandbox object is never passed between steps. Only the
  sandbox id travels through the workflow; each step reconnects by
  id.
- The pipeline is **stateless**: each run creates a fresh ephemeral
  sandbox (:func:`app.services.review.steps.create_sandbox.create_review_sandbox_step`),
  clones the repo at review time
  (:func:`app.services.review.steps.clone_repo.clone_repo_step`), and
  destroys the sandbox in the ``finally``
  (:func:`app.services.review.steps.stop_sandbox.kill_sandbox_step`).
  No dependency on the setup-time per-repo ``sandboxes`` row.
- The ``review`` lifecycle row
  (:func:`app.services.review.steps.review_run_steps`) records one
  row per run: ``RUNNING`` once the PR row exists, ``SUCCESS`` after
  the GitHub post completes, ``FAILED`` on any terminal exception.
  The ``mark_*`` steps are durable — DBOS retries them on transient
  DB failures and they raise
  :class:`app.services.review.errors.ReviewRunUpdateError`; a
  persistent mirror failure marks the workflow ERROR rather than
  silently leaving the row stuck in ``RUNNING``. The row is created
  inside the ``try`` so the sandbox ``finally`` also covers a running
  step that raises.
- GitHub posting is awaited before the review is marked stopped, so
  the ``review`` row's ``github_review_id`` is populated on the
  success path. The post is still a separate durable workflow
  (:func:`app.services.github.workflow.post_review_to_github_workflow`)
  that can be retried / restarted independently without re-running
  the LLM agent; it never raises, so an awaited post failure does
  not fail the review.
- Token-usage accounting happens at the end of the local pipeline
  via :func:`app.services.review.steps.persist_usage.persist_review_usage_tx`,
  which writes a :class:`app.models.review_usage.ReviewUsage` row
  for every successful run.
- The comment-trigger path can set ``input.diff_base_sha`` to the
  last successfully reviewed head; ``fetch_diff_step`` then produces
  ``git diff {diff_base_sha}...{head_sha}`` so an incremental re-review
  covers only the commits pushed since the previous run. ``base_sha``
  keeps the PR's true base for the ``pull_requests`` / ``review`` rows.
- The two research agents run in parallel and return free-form text;
  the structured payloads are produced afterwards by the durable
  extractor steps (:mod:`app.services.review.steps.extract_result`)
  via :func:`app.services.review.steps.invoke_agent.run_extractor_lanes`,
  which re-invoke a small OpenAI model with the schema bound.
"""

from __future__ import annotations

import asyncio
import logging

from dbos import DBOS, SetWorkflowID

from app.models.enums import ReviewRunStatus
from app.services.github.workflow import post_review_to_github_workflow
from app.services.review.helpers import compute_review_limits
from app.services.review.steps import (
    clone_repo_step,
    create_review_sandbox_step,
    fetch_diff_step,
    kill_sandbox_step,
    persist_code_comments_tx,
    persist_review_summary_tx,
    persist_review_usage_tx,
    resolve_repo_tx,
    split_diff_step,
    upsert_pull_request_tx,
)
from app.services.review.steps.extract_result import build_extractor_config
from app.services.review.steps.invoke_agent import (
    combine_agent_outcomes,
    invoke_comments_agent_step,
    invoke_summary_agent_step,
    run_extractor_lanes,
)
from app.services.review.steps.persist_usage import sum_total_usages
from app.services.review.steps.review_run_steps import (
    build_error_context,
    mark_review_is_errored_step,
    mark_review_is_running_step,
    mark_review_is_stopped_step,
)
from app.services.review.workflow_types import (
    PostReviewInput,
    PostReviewResult,
    ReviewRunResult,
    ReviewWorkflowInput,
    SandboxMeta,
)

log = logging.getLogger(__name__)


@DBOS.workflow()
async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
    """Durable workflow: review one PR end-to-end.

    Body is a straight-line sequence of step calls. Each step raises a
    typed exception on failure; transient ones are retried by DBOS via
    :data:`app.services.review._internal._SHOULD_RETRY_TRANSIENT`. The
    workflow itself does not translate exceptions into result types —
    the DBOS workflow record is marked as ERROR on unhandled
    exceptions, and the typed exception propagates to any caller
    awaiting the result.

    The :func:`app.services.review.steps.stop_sandbox.kill_sandbox_step`
    cleanup runs in a ``finally`` block that covers every step that
    follows a successful
    :func:`app.services.review.steps.create_sandbox.create_review_sandbox_step`.
    If the create step itself raises, there is no sandbox to kill.

    The ``review`` lifecycle row runs alongside: the row is created
    in ``RUNNING`` after the PR row exists, flipped to ``SUCCESS`` by
    :func:`app.services.review.steps.review_run_steps.mark_review_is_stopped_step`
    at the end of the success path, and flipped to ``FAILED`` by
    :func:`app.services.review.steps.review_run_steps.mark_review_is_errored_step`
    on any terminal exception (which is then re-raised). The
    ``mark_*`` steps are durable and raise
    :class:`app.services.review.errors.ReviewRunUpdateError` on
    failure; the ``except`` block guards the errored step so a
    failure while recording the error never masks the original
    exception.
    """
    repo = await resolve_repo_tx(input.gh_repo_id)

    workflow_id = DBOS.workflow_id or "<no-workflow-id>"
    review_id: str | None = None
    sandbox: SandboxMeta | None = None

    try:
        sandbox = await create_review_sandbox_step(
            user_id=input.user_id,
            repo_id=repo.id,
            repo_name=repo.repo_name,
        )

        await clone_repo_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            user_id=input.user_id,
            repo_id=repo.id,
            repo_owner=repo.repo_owner,
            repo_name=repo.repo_name,
            pr_number=input.pr_number,
            github_installation_id=input.github_installation_id,
        )

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

        review_id = await mark_review_is_running_step(
            user_id=input.user_id,
            repo_id=repo.id,
            gh_repo_id=input.gh_repo_id,
            pr_id=pr_id,
            pr_number=input.pr_number,
            commit_id=input.head_sha,
            base_sha=input.base_sha,
            trigger=input.trigger,
            sandbox_id=sandbox.sandbox_id,
            workflow_id=workflow_id,
            llm_provider=input.llm_config.provider,
            llm_model=input.llm_config.model_id,
            llm_base_url=input.llm_config.base_url,
        )

        await fetch_diff_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            repo_name=repo.repo_name,
            user_id=input.user_id,
            pr_number=input.pr_number,
            base_sha=input.base_sha,
            diff_base_sha=input.diff_base_sha,
            head_sha=input.head_sha,
        )

        split_result = await split_diff_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            user_id=input.user_id,
            pr_number=input.pr_number,
            head_sha=input.head_sha,
        )

        limits = compute_review_limits(input.pr_size)
        log.info(
            "workflow: computed per-run agent limits: workflow_id=%s "
            "pr_number=%s changed_files=%s model_call_run_limit=%d "
            "tool_call_run_limit=%d split_files=%d",
            workflow_id,
            input.pr_number,
            input.pr_size["changed_files"],
            limits.model_call_run_limit,
            limits.tool_call_run_limit,
            split_result["files_changed"],
        )

        agent_results = await asyncio.gather(
            invoke_summary_agent_step(
                sandbox_id=sandbox.sandbox_id,
                sandbox_name=sandbox.sandbox_name,
                repo_id=repo.id,
                repo_name=repo.repo_name,
                user_id=input.user_id,
                pr_number=input.pr_number,
                head_sha=input.head_sha,
                llm_config=input.llm_config,
                model_call_limit=limits.model_call_run_limit,
                tool_call_limit=limits.tool_call_run_limit,
            ),
            invoke_comments_agent_step(
                sandbox_id=sandbox.sandbox_id,
                sandbox_name=sandbox.sandbox_name,
                repo_id=repo.id,
                repo_name=repo.repo_name,
                user_id=input.user_id,
                pr_number=input.pr_number,
                head_sha=input.head_sha,
                llm_config=input.llm_config,
                model_call_limit=limits.model_call_run_limit,
                tool_call_limit=limits.tool_call_run_limit,
            ),
            return_exceptions=True,
        )

        extractor_config = build_extractor_config()
        extractor_lanes = await run_extractor_lanes(
            agent_results=agent_results,
            extractor_config=extractor_config,
        )

        review, usages = combine_agent_outcomes(
            extractor_lanes,
            pr_number=input.pr_number,
            head_sha=input.head_sha,
            repo_id=repo.id,
            user_id=input.user_id,
            llm_config=input.llm_config,
            workflow_id=workflow_id,
        )

        summary_id = await persist_review_summary_tx(
            pr_id=pr_id,
            review_id=review_id,
            commit_id=input.head_sha,
            result=review,
        )

        await persist_code_comments_tx(
            pr_id=pr_id,
            review_id=review_id,
            commit_id=input.head_sha,
            comments=[c.model_dump(mode="json") for c in review.comments],
        )

        input_tokens, output_tokens, total_tokens, input_token_details = (
            sum_total_usages(usages)
        )

        await persist_review_usage_tx(
            pr_id=pr_id,
            review_id=review_id,
            user_id=input.user_id,
            pr_number=input.pr_number,
            repo_id=repo.id,
            review_summary_id=summary_id,
            review_status=ReviewRunStatus.SUCCESS,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            input_token_details=input_token_details,
            llm_model_id=input.llm_config.model_id,
            llm_provider=input.llm_config.provider,
            llm_base_url=input.llm_config.base_url,
        )

        github_review_id: str | None = None
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

            post_workflow_id = f"post:{repo.id}:{input.pr_number}:{input.head_sha[:7]}"
            with SetWorkflowID(post_workflow_id):
                post_handle = await DBOS.start_workflow_async(
                    post_review_to_github_workflow, post_input
                )
                post_result: PostReviewResult = await post_handle.get_result()
            if post_result.github_review_id is not None:
                github_review_id = str(post_result.github_review_id)

        await mark_review_is_stopped_step(
            review_id=review_id,
            comment_count=len(review.comments),
            github_review_id=github_review_id,
        )

        log.info(
            "workflow: stopping workflow: workflow_id=%s "
            "gh_repo_id=%s number=%s head_sha=%s",
            workflow_id,
            input.gh_repo_id,
            input.pr_number,
            input.head_sha,
        )

        return ReviewRunResult(
            pr_id=pr_id,
            commit_id=input.head_sha,
            review=review,
            usages=usages,
        )

    except BaseException as exc:
        try:
            await mark_review_is_errored_step(
                review_id=review_id,
                error_name=type(exc).__name__,
                error_message=str(exc),
                error_context=build_error_context(exc),
            )
        except Exception:
            log.exception(
                "workflow: failed to record review error review_id=%s workflow_id=%s",
                review_id,
                workflow_id,
            )
        raise

    finally:
        if sandbox is not None:
            await kill_sandbox_step(
                sandbox_id=sandbox.sandbox_id,
                sandbox_name=sandbox.sandbox_name,
                repo_id=repo.id,
                user_id=input.user_id,
            )


__all__ = ["review_workflow"]
