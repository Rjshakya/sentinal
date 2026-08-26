"""DBOS durable step: create the per-review ephemeral E2B sandbox.

The review pipeline is **stateless**: every run creates its own fresh
sandbox, clones the repo into it, and destroys the sandbox in the
workflow's ``finally`` (:func:`app.services.review.steps.stop_sandbox.kill_sandbox_step`).
There is no dependency on the setup-time per-repo ``sandboxes`` row.

:func:`create_review_sandbox_step` deliberately does **not** persist a
:class:`app.models.sandbox.Sandbox` row: ``E2BSandbox.create`` only
writes through its ``_on_create_hook``, which the review path never
sets, so the sandbox exists purely for the duration of the run. The
``review`` lifecycle row records its id (``review.sandbox_id``) for
traceability.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox
from app.services.review._internal import _SHOULD_RETRY_TRANSIENT, _e2b_spec
from app.services.review.errors import SandboxCreateStepError
from app.services.review.workflow_types import SandboxMeta

log = logging.getLogger(__name__)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_SHOULD_RETRY_TRANSIENT,
)
async def create_review_sandbox_step(
    *,
    user_id: str,
    repo_id: str,
    repo_name: str,
) -> SandboxMeta:
    """Durable step: create a fresh, ephemeral E2B sandbox for this run.

    The sandbox is created from the active E2B template and returned as
    a :class:`ResolvedSandbox` (the serialisable subset) so only the id
    travels through the workflow; each later step reconnects by id.

    Raises:
        SandboxCreateStepError: E2B creation failed. Transient — DBOS
            retries the step, which creates a fresh sandbox.
    """
    spec = _e2b_spec()
    sandbox = E2BSandbox(
        spec=spec,
        user_id=user_id,
        repo_id=repo_id,
        sandbox_name=f"review-{repo_name}",
    )

    try:
        await sandbox.create()
    except Exception as exc:
        log.warning(
            "create_review_sandbox_step: e2b create failed (will retry): "
            "user_id=%s repo_id=%s cause=%s: %s",
            user_id,
            repo_id,
            type(exc).__name__,
            exc,
        )
        raise SandboxCreateStepError(
            user_id=user_id,
            repo_id=repo_id,
            cause=f"{type(exc).__name__}: {exc}",
        ) from exc

    log.info(
        "create_review_sandbox_step: ok user_id=%s repo_id=%s sandbox_id=%s",
        user_id,
        repo_id,
        sandbox.id,
    )
    return SandboxMeta(sandbox_id=sandbox.id, sandbox_name=sandbox.sandbox_name)


__all__ = ["create_review_sandbox_step"]
