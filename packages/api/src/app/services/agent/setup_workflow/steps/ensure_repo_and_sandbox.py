"""Step 1: upsert the local :class:`Repo` row, create the E2B sandbox,
and persist the :class:`Sandbox` row.

Single :func:`@DBOS.step` so the E2B create and the Sandbox row
insert either both happen or both are re-attempted on retry. The
``Repo`` upsert is select-then-insert and idempotent; the E2B create
is the only non-idempotent piece, so we keep it inside one step to
make the failure mode obvious.

Trade-off: a retry after the E2B create but before the Sandbox row
insert will leak the first sandbox. This is a known v1 limitation;
fixable later by passing a sandbox id between two separate steps.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

from dbos import DBOS
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.core.sandbox.factory import build_default_spec
from app.models.enums import SandboxState
from app.models.installation import Installation
from app.models.repo import Repo
from app.models.sandbox import Sandbox as SandboxModel
from app.services.agent.setup_workflow.errors import (
    InstallationNotFoundError,
    SandboxCreateError,
    SetupError,
)
from app.services.agent.setup_workflow.types import RepoContext, SetupWorkflowInput
from app.utils.util import uuidToStr

log = logging.getLogger(__name__)


def _should_retry_setup(exc: BaseException) -> bool:
    """DBOS ``should_retry`` predicate: retry only on transient setup errors."""
    from app.services.agent.setup_workflow.errors import TransientSetupError

    return isinstance(exc, TransientSetupError)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry_setup,
)
async def ensure_repo_and_sandbox_step(
    input: SetupWorkflowInput,
) -> RepoContext:
    """Look up the :class:`Installation`, upsert the :class:`Repo`,
    create the E2B sandbox, persist the :class:`Sandbox` row.

    Order of operations is deliberate so a partial failure is easy
    to reason about:

    1. DB lookup ``Installation`` by ``(id, user_id)`` — missing row
       is a final ``InstallationNotFoundError``.
    2. DB upsert ``Repo`` by ``github_repo_id`` — select-then-insert,
       safe to retry.
    3. E2B ``AsyncSandbox.create`` — wrapped in
       :class:`SandboxCreateError` so the retry predicate can re-run
       the whole step on a transient E2B blip.
    4. DB insert ``Sandbox`` row — keyed on the E2B-side
       ``sandbox_id``, so the Sandbox row's PK is durable.

    Returns:
        :class:`RepoContext` carrying every id the rest of the
        workflow needs. Frozen so DBOS can serialize the return.

    Raises:
        InstallationNotFoundError: the ``Installation`` row is
            missing or owned by another user. Final — not retried.
        SandboxCreateError: E2B sandbox creation failed transiently.
            Retried by DBOS up to ``max_attempts`` times.
    """
    user_id = input.user_id
    installation_id = input.installation_id

    async with async_session_maker() as session:
        installation = await _find_installation(
            session=session,
            installation_id=installation_id,
            user_id=user_id,
        )
        if installation is None:
            raise InstallationNotFoundError(
                installation_id=installation_id,
                user_id=user_id,
            )

        repo_record = await _upsert_repo(
            session=session,
            user_id=user_id,
            github_repo_id=input.github_repo_id,
            repo_name=input.repo_name,
            repo_owner=input.repo_owner,
            default_branch=input.default_branch,
        )

        spec: E2BSandboxSpec = cast(E2BSandboxSpec, build_default_spec("e2b"))

        try:
            sandbox = E2BSandbox(
                spec=spec,
                user_id=user_id,
                repo_id=repo_record.id,
                sandbox_name=f"sbx-{input.repo_owner}-{input.repo_name}",
            )
            await sandbox.create()
        except SetupError:
            raise
        except Exception as exc:
            log.exception(
                "ensure_repo_and_sandbox: e2b create failed: user_id=%s repo_id=%s",
                user_id,
                repo_record.id,
            )
            raise SandboxCreateError(cause=f"{type(exc).__name__}: {exc}") from exc

        sandbox_row = await _insert_sandbox_row(
            session=session,
            user_id=user_id,
            repo_id=repo_record.id,
            sandbox_id=sandbox.id,
            sandbox_name=sandbox.sandbox_name,
        )
        await session.commit()
        log.info(
            "ensure_repo_and_sandbox: ok user_id=%s repo_id=%s sandbox_id=%s",
            user_id,
            repo_record.id,
            sandbox.id,
        )

    return RepoContext(
        user_id=user_id,
        repo_id=repo_record.id,
        repo_owner=input.repo_owner,
        repo_name=input.repo_name,
        sandbox_id=sandbox_row.id,
        sandbox_name=sandbox_row.sandbox_name,
        installation_id=installation_id,
        github_installation_id=installation.github_installation_id,
    )


# --------------------------------------------------------------------------- #
# DB shell helpers (inlined so the step file is self-contained)                #
# --------------------------------------------------------------------------- #


async def _find_installation(
    *,
    session: AsyncSession,
    installation_id: str,
    user_id: str,
) -> Installation | None:
    """Return the user's :class:`Installation` row, or ``None``.

    Single ``SELECT ... WHERE id = ? AND user_id = ?``. The
    ``user_id`` predicate is enforced at the DB layer; if a row
    matches ``id`` but belongs to a different user we get no hit.
    """
    stmt = select(Installation).where(
        Installation.id == installation_id,
        Installation.user_id == user_id,
    )
    result = await session.exec(stmt)
    return result.first()


async def _upsert_repo(
    *,
    session: AsyncSession,
    user_id: str,
    github_repo_id: int,
    repo_name: str,
    repo_owner: str,
    default_branch: str | None,
) -> Repo:
    """Insert-or-fetch the :class:`Repo` row keyed on ``github_repo_id``.

    Select-then-insert, idempotent on retry. ``Repo.id`` is a UUID
    assigned by :func:`uuidToStr` on first insert; on subsequent
    calls the existing row is returned unchanged. ``default_branch``
    is only applied on insert — the router skips repos that already
    have a row, and the retry path never re-inserts a committed row.
    """
    stmt = select(Repo).where(Repo.github_repo_id == github_repo_id)
    existing = (await session.exec(stmt)).first()
    if existing is not None:
        return existing

    repo = Repo(
        id=uuidToStr(),
        user_id=user_id,
        github_repo_id=github_repo_id,
        repo_name=repo_name,
        repo_owner=repo_owner,
        clone_url=f"https://github.com/{repo_owner}/{repo_name}.git",
        default_branch=default_branch,
    )
    session.add(repo)
    await session.flush()
    await session.refresh(repo)
    return repo


async def _insert_sandbox_row(
    *,
    session: AsyncSession,
    user_id: str,
    repo_id: str,
    sandbox_id: str,
    sandbox_name: str,
) -> SandboxModel:
    """Insert a :class:`Sandbox` row keyed on the E2B-side ``sandbox_id``.

    The PK is the E2B-assigned id, so two ``create`` calls for the
    same repo would clash (the second insert fails with a PK
    conflict). DBOS does not re-run a completed step, so this is
    only a concern on the rare retry path described in the step's
    docstring.
    """
    sandbox = SandboxModel(
        id=sandbox_id,
        user_id=user_id,
        repo_id=repo_id,
        sandbox_name=sandbox_name,
        state=SandboxState.STARTED,
        provider_id="e2b",
        started_at=datetime.now(UTC),
    )
    session.add(sandbox)
    await session.flush()
    await session.refresh(sandbox)
    return sandbox


__all__ = ["ensure_repo_and_sandbox_step"]
