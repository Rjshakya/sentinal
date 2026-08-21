"""Typed errors for the ``issue_comment`` trigger pipeline.

Two layers:

- :class:`TriggerError` — the base for every error raised inside the
  trigger pipeline. Plain ``TriggerError`` subclasses are
  business outcomes (bad payload, missing installation, etc.) and are
  not retried.
- :class:`TransientTriggerError` — marker base for transient
  failures (GitHub 5xx, network blips). Steps that wrap an
  external API call classify under this so DBOS can retry them.

The trigger workflow's per-step retry policy is::

    should_retry=lambda exc: isinstance(exc, TransientTriggerError)

so a step only re-runs when its exception inherits from
:class:`TransientTriggerError`. A plain :class:`TriggerError`
short-circuits the workflow; DBOS marks the workflow ``ERROR`` and
the trigger handler in :mod:`app.services.pr_issue_comment.handler`
surfaces the failure through :class:`TriggerRunResult.skip_reason`.
"""

from __future__ import annotations


class TriggerError(Exception):
    """Base class for every trigger-pipeline step error."""


class TransientTriggerError(TriggerError):
    """Marker base for transient failures DBOS should retry.

    Subclasses encode failures that are expected to clear up on a
    subsequent attempt: GitHub 5xx, E2B connect / IO dropouts,
    LLM 429 / timeouts. Step decorators that want DBOS-managed
    retry should set
    ``should_retry=lambda exc: isinstance(exc, TransientTriggerError)``.
    """


class PRFetchError(TransientTriggerError):
    """``GET /repos/{owner}/{repo}/pulls/{pr_number}`` failed transiently.

    Wraps the underlying ``githubkit`` exception. The fetch step
    retries on this error; on persistent failure the workflow
    surfaces the cause through :class:`TriggerRunResult.skip_reason`.
    """

    def __init__(self, *, owner: str, repo: str, pr_number: int, cause: str) -> None:
        self.owner = owner
        self.repo = repo
        self.pr_number = pr_number
        self.cause = cause
        super().__init__(
            f"GET /repos/{owner}/{repo}/pulls/{pr_number} failed: {cause}"
        )


class ReactionError(TriggerError):
    """Adding the 👀 reaction failed.

    The reaction step is **best-effort** and swallows this error
    after structured-logging. The trigger workflow does not depend
    on the reaction succeeding — the review proceeds regardless.
    Kept as a typed variant so the log can be grepped.
    """

    def __init__(self, *, cause: str) -> None:
        self.cause = cause
        super().__init__(f"add_eyes_reaction failed: {cause}")


__all__ = [
    "PRFetchError",
    "ReactionError",
    "TransientTriggerError",
    "TriggerError",
]
