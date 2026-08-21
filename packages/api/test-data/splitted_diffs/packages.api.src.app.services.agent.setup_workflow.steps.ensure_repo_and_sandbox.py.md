### packages/api/src/app/services/agent/setup_workflow/steps/ensure_repo_and_sandbox.py

```diff

new file mode 100644
index 0000000..f5a048a
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/steps/ensure_repo_and_sandbox.py
@@ -0,0 +1,248 @@
          2 +"""Step 1: upsert the local :class:`Repo` row, create the E2B sandbox,
          3 +and persist the :class:`Sandbox` row.
          4 +
          5 +Single :func:`@DBOS.step` so the E2B create and the Sandbox row
          6 +insert either both happen or both are re-attempted on retry. The
          7 +``Repo`` upsert is select-then-insert and idempotent; the E2B create
          8 +is the only non-idempotent piece, so we keep it inside one step to
          9 +make the failure mode obvious.
         10 +
         11 +Trade-off: a retry after the E2B create but before the Sandbox row
         12 +insert will leak the first sandbox. This is a known v1 limitation;
         13 +fixable later by passing a sandbox id between two separate steps.
         14 +"""
         15 +
         16 +from __future__ import annotations
         17 +
         18 +import logging
         19 +from datetime import UTC, datetime
         20 +from typing import cast
         21 +
         22 +from dbos import DBOS
         23 +from sqlmodel import select
         24 +from sqlmodel.ext.asyncio.session import AsyncSession
         25 +
         26 +from app.core.db import async_session_maker
         27 +from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
         28 +from app.core.sandbox.factory import build_default_spec
         29 +from app.models.enums import SandboxState
         30 +from app.models.installation import Installation
         31 +from app.models.repo import Repo
         32 +from app.models.sandbox import Sandbox as SandboxModel
         33 +from app.services.agent.setup_workflow.errors import (
         34 +    InstallationNotFoundError,
         35 +    SandboxCreateError,
         36 +    SetupError,
         37 +)
         38 +from app.services.agent.setup_workflow.types import RepoContext, SetupWorkflowInput
         39 +from app.utils.util import uuidToStr
         40 +
         41 +log = logging.getLogger(__name__)
         42 +
         43 +
         44 +def _should_retry_setup(exc: BaseException) -> bool:
         45 +    """DBOS ``should_retry`` predicate: retry only on transient setup errors."""
         46 +    from app.services.agent.setup_workflow.errors import TransientSetupError
         47 +
         48 +    return isinstance(exc, TransientSetupError)
         49 +
         50 +
         51 +@DBOS.step(
         52 +    retries_allowed=True,
         53 +    max_attempts=3,
         54 +    should_retry=_should_retry_setup,
         55 +)
         56 +async def ensure_repo_and_sandbox_step(
         57 +    input: SetupWorkflowInput,
         58 +) -> RepoContext:
         59 +    """Look up the :class:`Installation`, upsert the :class:`Repo`,
         60 +    create the E2B sandbox, persist the :class:`Sandbox` row.
         61 +
         62 +    Order of operations is deliberate so a partial failure is easy
         63 +    to reason about:
         64 +
         65 +    1. DB lookup ``Installation`` by ``(id, user_id)`` — missing row
         66 +       is a final ``InstallationNotFoundError``.
         67 +    2. DB upsert ``Repo`` by ``github_repo_id`` — select-then-insert,
         68 +       safe to retry.
         69 +    3. E2B ``AsyncSandbox.create`` — wrapped in
         70 +       :class:`SandboxCreateError` so the retry predicate can re-run
         71 +       the whole step on a transient E2B blip.
         72 +    4. DB insert ``Sandbox`` row — keyed on the E2B-side
         73 +       ``sandbox_id``, so the Sandbox row's PK is durable.
         74 +
         75 +    Returns:
         76 +        :class:`RepoContext` carrying every id the rest of the
         77 +        workflow needs. Frozen so DBOS can serialize the return.
         78 +
         79 +    Raises:
         80 +        InstallationNotFoundError: the ``Installation`` row is
         81 +            missing or owned by another user. Final — not retried.
         82 +        SandboxCreateError: E2B sandbox creation failed transiently.
         83 +            Retried by DBOS up to ``max_attempts`` times.
         84 +    """
         85 +    user_id = input.user_id
         86 +    installation_id = input.installation_id
         87 +
         88 +    async with async_session_maker() as session:
         89 +        installation = await _find_installation(
         90 +            session=session,
         91 +            installation_id=installation_id,
         92 +            user_id=user_id,
         93 +        )
         94 +        if installation is None:
         95 +            raise InstallationNotFoundError(
         96 +                installation_id=installation_id,
         97 +                user_id=user_id,
         98 +            )
         99 +
        100 +        repo_record = await _upsert_repo(
        101 +            session=session,
        102 +            user_id=user_id,
        103 +            github_repo_id=input.github_repo_id,
        104 +            repo_name=input.repo_name,
        105 +            repo_owner=input.repo_owner,
        106 +            default_branch=input.default_branch,
        107 +        )
        108 +
        109 +        spec: E2BSandboxSpec = cast(E2BSandboxSpec, build_default_spec("e2b"))
        110 +
        111 +        try:
        112 +            sandbox = E2BSandbox(
        113 +                spec=spec,
        114 +                user_id=user_id,
        115 +                repo_id=repo_record.id,
        116 +                sandbox_name=f"sbx-{input.repo_owner}-{input.repo_name}",
        117 +            )
        118 +            await sandbox.create()
        119 +        except SetupError:
        120 +            raise
        121 +        except Exception as exc:
        122 +            log.exception(
        123 +                "ensure_repo_and_sandbox: e2b create failed: user_id=%s repo_id=%s",
        124 +                user_id,
        125 +                repo_record.id,
        126 +            )
        127 +            raise SandboxCreateError(cause=f"{type(exc).__name__}: {exc}") from exc
        128 +
        129 +        sandbox_row = await _insert_sandbox_row(
        130 +            session=session,
        131 +            user_id=user_id,
        132 +            repo_id=repo_record.id,
        133 +            sandbox_id=sandbox.id,
        134 +            sandbox_name=sandbox.sandbox_name,
        135 +        )
        136 +        await session.commit()
        137 +        log.info(
        138 +            "ensure_repo_and_sandbox: ok user_id=%s repo_id=%s sandbox_id=%s",
        139 +            user_id,
        140 +            repo_record.id,
        141 +            sandbox.id,
        142 +        )
        143 +
        144 +    return RepoContext(
        145 +        user_id=user_id,
        146 +        repo_id=repo_record.id,
        147 +        repo_owner=input.repo_owner,
        148 +        repo_name=input.repo_name,
        149 +        sandbox_id=sandbox_row.id,
        150 +        sandbox_name=sandbox_row.sandbox_name,
        151 +        installation_id=installation_id,
        152 +        github_installation_id=installation.github_installation_id,
        153 +    )
        154 +
        155 +
        156 +# --------------------------------------------------------------------------- #
        157 +# DB shell helpers (inlined so the step file is self-contained)                #
        158 +# --------------------------------------------------------------------------- #
        159 +
        160 +
        161 +async def _find_installation(
        162 +    *,
        163 +    session: AsyncSession,
        164 +    installation_id: str,
        165 +    user_id: str,
        166 +) -> Installation | None:
        167 +    """Return the user's :class:`Installation` row, or ``None``.
        168 +
        169 +    Single ``SELECT ... WHERE id = ? AND user_id = ?``. The
        170 +    ``user_id`` predicate is enforced at the DB layer; if a row
        171 +    matches ``id`` but belongs to a different user we get no hit.
        172 +    """
        173 +    stmt = select(Installation).where(
        174 +        Installation.id == installation_id,
        175 +        Installation.user_id == user_id,
        176 +    )
        177 +    result = await session.exec(stmt)
        178 +    return result.first()
        179 +
        180 +
        181 +async def _upsert_repo(
        182 +    *,
        183 +    session: AsyncSession,
        184 +    user_id: str,
        185 +    github_repo_id: int,
        186 +    repo_name: str,
        187 +    repo_owner: str,
        188 +    default_branch: str | None,
        189 +) -> Repo:
        190 +    """Insert-or-fetch the :class:`Repo` row keyed on ``github_repo_id``.
        191 +
        192 +    Select-then-insert, idempotent on retry. ``Repo.id`` is a UUID
        193 +    assigned by :func:`uuidToStr` on first insert; on subsequent
        194 +    calls the existing row is returned unchanged. ``default_branch``
        195 +    is only applied on insert — the router skips repos that already
        196 +    have a row, and the retry path never re-inserts a committed row.
        197 +    """
        198 +    stmt = select(Repo).where(Repo.github_repo_id == github_repo_id)
        199 +    existing = (await session.exec(stmt)).first()
        200 +    if existing is not None:
        201 +        return existing
        202 +
        203 +    repo = Repo(
        204 +        id=uuidToStr(),
        205 +        user_id=user_id,
        206 +        github_repo_id=github_repo_id,
        207 +        repo_name=repo_name,
        208 +        repo_owner=repo_owner,
        209 +        clone_url=f"https://github.com/{repo_owner}/{repo_name}.git",
        210 +        default_branch=default_branch,
        211 +    )
        212 +    session.add(repo)
        213 +    await session.flush()
        214 +    await session.refresh(repo)
        215 +    return repo
        216 +
        217 +
        218 +async def _insert_sandbox_row(
        219 +    *,
        220 +    session: AsyncSession,
        221 +    user_id: str,
        222 +    repo_id: str,
        223 +    sandbox_id: str,
        224 +    sandbox_name: str,
        225 +) -> SandboxModel:
        226 +    """Insert a :class:`Sandbox` row keyed on the E2B-side ``sandbox_id``.
        227 +
        228 +    The PK is the E2B-assigned id, so two ``create`` calls for the
        229 +    same repo would clash (the second insert fails with a PK
        230 +    conflict). DBOS does not re-run a completed step, so this is
        231 +    only a concern on the rare retry path described in the step's
        232 +    docstring.
        233 +    """
        234 +    sandbox = SandboxModel(
        235 +        id=sandbox_id,
        236 +        user_id=user_id,
        237 +        repo_id=repo_id,
        238 +        sandbox_name=sandbox_name,
        239 +        state=SandboxState.STARTED,
        240 +        provider_id="e2b",
        241 +        started_at=datetime.now(UTC),
        242 +    )
        243 +    session.add(sandbox)
        244 +    await session.flush()
        245 +    await session.refresh(sandbox)
        246 +    return sandbox
        247 +
        248 +
        249 +__all__ = ["ensure_repo_and_sandbox_step"]

```
