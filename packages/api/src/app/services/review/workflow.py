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
- GitHub posting is a separate durable workflow
  (:func:`app.services.github.workflow.post_review_to_github_workflow`)
  so it can be retried / restarted independently without re-running
  the LLM agent.
- Token-usage accounting happens at the end of the local pipeline
  via :func:`app.services.review.steps.persist_usage.persist_review_usage_tx`,
  which writes a :class:`app.models.review_usage.ReviewUsage` row
  for every successful run.
"""

from __future__ import annotations

import asyncio
import logging

from dbos import DBOS, SetWorkflowID

from app.models.enums import ReviewRunStatus
from app.services.github.workflow import post_review_to_github_workflow
from app.services.review.hunk_map import HunkMap, filter_drafts
from app.services.review.steps import (
    fetch_diff_step,
    parse_diff_step,
    persist_code_comments_tx,
    persist_review_summary_tx,
    persist_review_usage_tx,
    resolve_repo_tx,
    resolve_sandbox_step,
    stop_sandbox_step,
    update_repo_step,
    upsert_pull_request_tx,
)
from app.services.review.steps.invoke_agent import (
    combine_agent_outcomes,
    invoke_comments_agent_step,
    invoke_summary_agent_step,
)
from app.services.review.steps.persist_usage import sum_total_usages
from app.services.review.workflow_types import (
    PostReviewInput,
    ReviewRunResult,
    ReviewWorkflowInput,
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

    The :func:`app.services.review.steps.stop_sandbox_step` cleanup
    runs in a ``finally`` block that covers every step that follows a
    successful :func:`app.services.review.steps.resolve_sandbox_step`.
    If :func:`app.services.review.steps.resolve_sandbox_step` itself
    raises, there is no connected sandbox to stop.
    """
    repo = await resolve_repo_tx(input.gh_repo_id)
    sandbox = await resolve_sandbox_step(user_id=input.user_id, repo_id=repo.id)

    try:
        await update_repo_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            repo_name=repo.repo_name,
            user_id=input.user_id,
            default_branch=input.default_branch or repo.default_branch,
        )

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
            ),
            return_exceptions=True,
        )

        review, usages = combine_agent_outcomes(
            agent_results,
            pr_number=input.pr_number,
            head_sha=input.head_sha,
            repo_id=repo.id,
            user_id=input.user_id,
            llm_config=input.llm_config,
            workflow_id=DBOS.workflow_id or "<no-workflow-id>",
        )

        filtered_review = filter_drafts(review, hunk_map)

        summary_id = await persist_review_summary_tx(
            pr_id=pr_id,
            commit_id=input.head_sha,
            result=filtered_review,
        )

        await persist_code_comments_tx(
            pr_id=pr_id,
            commit_id=input.head_sha,
            comments=[c.model_dump(mode="json") for c in filtered_review.comments],
        )

        input_tokens, output_tokens, total_tokens, input_token_details = (
            sum_total_usages(usages)
        )
        await persist_review_usage_tx(
            pr_id=pr_id,
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

        log.info(
            "workflow: stopping workflow: workflow_id=%s "
            "gh_repo_id=%s number=%s head_sha=%s",
            DBOS.workflow_id,
            input.gh_repo_id,
            input.pr_number,
            input.head_sha,
        )

        return ReviewRunResult(
            pr_id=pr_id,
            commit_id=input.head_sha,
            review=filtered_review,
            usages=usages,
        )

    finally:
        await stop_sandbox_step(
            sandbox_id=sandbox.sandbox_id,
            sandbox_name=sandbox.sandbox_name,
            repo_id=repo.id,
            user_id=input.user_id,
        )


__all__ = ["review_workflow"]
