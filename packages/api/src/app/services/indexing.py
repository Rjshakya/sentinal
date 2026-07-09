"""Indexing pipeline.

Functional, per-item pipeline. Each step is a top-level ``async def``
that operates on a single repo (or sandbox) and returns a typed value.
The orchestrator ``indexing_pipeline`` is a single ``for`` loop wrapped
in a single ``try / except / finally`` block; it owns its own DB
session via :func:`async_session_maker` and runs sequentially per repo.

The pipeline is provider-agnostic: it only ever talks to
:class:`BaseSandbox` and never imports a concrete provider. Per-repo
DB persistence is wired through the sandbox's lifecycle hooks
(``on_create`` / ``on_pause`` / ``on_kill``) — each hook is an
``async`` closure that captures the active DB session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import or_, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.sandbox import (
    BaseSandbox,
    CommandResult,
    SandboxModel,
    create_sandbox,
)
from app.core.sandbox.base import SandboxAlreadyActive
from app.core.sandbox.e2b import E2BSandboxSpec
from app.models.enums import SandboxState
from app.models.repo import Repo
from app.models.sandbox import Sandbox as SandboxTable
from app.schemas.indexing import IndexingRepo

log = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).parent / "sandbox_scripts"

WORKSPACE_DIR = "/sentinel-workspace"


# --------------------------------------------------------------------------- #
# result types (frozen dataclasses)                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IndexingItemResult:
    repo_id: str
    sandbox_id: str
    state: SandboxState


@dataclass(frozen=True)
class CloneResult:
    repo_path: str
    exit_code: int
    stdout: str


@dataclass(frozen=True)
class IngestResult:
    exit_code: int
    stdout: str


# --------------------------------------------------------------------------- #
# "active sandbox" helpers (pure DB)                                          #
# --------------------------------------------------------------------------- #


async def active_sandbox(
    session: AsyncSession,
    user_id: str,
    repo_id: str,
) -> SandboxTable | None:
    """Return the active sandbox row for ``(user_id, repo_id)``, if any.

    An active sandbox is one whose state is ``STARTED``, ``PAUSED`` or
    ``STOPPED`` (i.e. anything except ``DELETED`` or ``ARCHIVED``).
    """

    query = select(SandboxTable).where(
        SandboxTable.repo_id == repo_id,
        SandboxTable.user_id == user_id,
        or_(
            SandboxTable.state == SandboxState.STARTED,
            SandboxTable.state == SandboxState.PAUSED,
            SandboxTable.state == SandboxState.STOPPED,
        ),
    )
    result = await session.exec(query)
    return result.first()


# --------------------------------------------------------------------------- #
# DB hook implementations                                                     #
# --------------------------------------------------------------------------- #
#
# These are plain ``async`` functions that take the DB session explicitly
# (instead of capturing it via a closure). The pipeline builds a thin
# ``lambda`` adapter for each hook, which is what :meth:`BaseSandbox.on_create`
# etc. expect.


async def _persist_create(session: AsyncSession, m: SandboxModel) -> None:
    """Upsert a ``STARTED`` sandbox row keyed on the provider's external id."""
    stmt = pg_insert(SandboxTable).values(
        id=m.id,
        user_id=m.user_id,
        repo_id=m.repo_id,
        sandbox_name=m.sandbox_name,
        provider_id=m.provider_id,
        state=m.state,
        started_at=m.started_at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SandboxTable.id],
        set_={
            "user_id": stmt.excluded.user_id,
            "repo_id": stmt.excluded.repo_id,
            "sandbox_name": stmt.excluded.sandbox_name,
            "provider_id": stmt.excluded.provider_id,
            "state": stmt.excluded.state,
            "started_at": stmt.excluded.started_at,
        },
    )
    await session.exec(stmt)
    await session.commit()


async def _persist_pause(session: AsyncSession, m: SandboxModel) -> None:
    """Mark a sandbox row as ``PAUSED`` with the supplied ``stopped_at``."""
    stmt = (
        update(SandboxTable)
        .where(SandboxTable.id == m.id)  # type: ignore[arg-type]
        .values(
            state=SandboxState.PAUSED,
            stopped_at=m.stopped_at or datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.exec(stmt)
    await session.commit()


async def _persist_kill(session: AsyncSession, m: SandboxModel) -> None:
    """Mark a sandbox row as ``DELETED`` with the supplied ``stopped_at``."""
    stmt = (
        update(SandboxTable)
        .where(SandboxTable.id == m.id)  # type: ignore[arg-type]
        .values(
            state=SandboxState.DELETED,
            stopped_at=m.stopped_at or datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.exec(stmt)
    await session.commit()


# --------------------------------------------------------------------------- #
# step 1: save repo                                                           #
# --------------------------------------------------------------------------- #


async def _upsert_repo(
    *, session: AsyncSession, user_id: str, payload: IndexingRepo
) -> Repo:
    stmt = pg_insert(Repo).values(
        id=payload.id,
        user_id=user_id,
        repo_name=payload.name,
        repo_owner=payload.owner,
        private=payload.private,
        default_branch=payload.default_branch,
        url=payload.html_url,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Repo.id],
        set_={
            "repo_name": stmt.excluded.repo_name,
            "repo_owner": stmt.excluded.repo_owner,
            "private": stmt.excluded.private,
            "default_branch": stmt.excluded.default_branch,
            "url": stmt.excluded.url,
        },
    ).returning(Repo)

    res = await session.exec(stmt)
    repo_record: Repo = res.scalars().one()
    await session.commit()
    return repo_record


async def save_repo(
    session: AsyncSession, *, user_id: str, payload: IndexingRepo
) -> Repo:
    """Step 1: upsert one Repo row. Commits on success."""
    return await _upsert_repo(session=session, user_id=user_id, payload=payload)


# --------------------------------------------------------------------------- #
# step 2: init sandbox                                                        #
# --------------------------------------------------------------------------- #


async def init_sandbox(
    session: AsyncSession,
    *,
    spec: E2BSandboxSpec,
    user_id: str,
    repo: Repo,
) -> BaseSandbox:
    """Step 2: build a :class:`BaseSandbox`, register DB hooks, create it.

    Raises :class:`SandboxAlreadyActive` if an active sandbox already
    exists for the ``(user_id, repo_id)`` pair.
    """
    existing = await active_sandbox(session, user_id=user_id, repo_id=repo.id)
    if existing is not None:
        raise SandboxAlreadyActive(existing.id)

    sandbox_name = f"{repo.repo_name}-sandbox"
    sb = create_sandbox(
        spec=spec,
        user_id=user_id,
        repo_id=repo.id,
        sandbox_name=sandbox_name,
    )
    sb.on_create(lambda m: _persist_create(session, m))
    sb.on_pause(lambda m: _persist_pause(session, m))
    sb.on_kill(lambda m: _persist_kill(session, m))

    await sb.create()
    return sb


# --------------------------------------------------------------------------- #
# step 3: clone repo                                                          #
# --------------------------------------------------------------------------- #


async def clone_repo(sandbox: BaseSandbox, repo: Repo) -> CloneResult:
    """Step 3: ``git clone --depth 1`` inside the sandbox.

    Returns the exit code in the result; never raises on a non-zero exit.
    """
    await sandbox.fs_create_folder("sentinel-workspace")
    repo_dir = f"{repo.repo_name}"
    command = f"git clone --depth 1 {repo.url} {repo_dir}"
    log.info(command)
    response: CommandResult = await sandbox.execute(command, cwd="sentinel-workspace")

    return CloneResult(
        repo_path=repo_dir,
        exit_code=0,
        stdout=response.stdout + "",
    )


# --------------------------------------------------------------------------- #
# step 4: upload scripts                                                      #
# --------------------------------------------------------------------------- #


async def upload_scripts(sandbox: BaseSandbox) -> None:
    """Step 4: copy ``chunking.py`` / ``ingestion.py`` / ``sandbox.env``
    into ``/sentinel-workspace/context`` inside the sandbox.

    The Kuzu/Ladybug JSON extension is fetched by the in-sandbox script
    itself (``LOAD EXTENSION`` over the CDN) — Tier-1 networks are no
    longer in play now that the active provider is E2B.
    """

    context_dir = f"/home/user/{WORKSPACE_DIR}/context"
    await sandbox.fs_create_folder(context_dir)

    for src_name in (
        "chunking.py",
        "ingestion.py",
        "embedding.py",
        "search.py",
        "sandbox.env",
    ):
        src = SCRIPTS_DIR / src_name
        if not src.exists():
            raise FileNotFoundError(f"Indexing file missing: {src}")
        dst_name = ".env" if src_name == "sandbox.env" else src_name
        await sandbox.upload_file(str(src), f"{context_dir}/{dst_name}")


# --------------------------------------------------------------------------- #
# step 5: run ingestion                                                       #
# --------------------------------------------------------------------------- #


def _dataset_name_for(repo: Repo) -> str:
    return f"{repo.repo_name}"


def _log_ctx(*, repo_id: str, sandbox_name: str | None, step: str) -> dict:
    """Common ``extra`` payload for every pipeline log line."""
    return {"repo_id": repo_id, "sandbox_name": sandbox_name, "step": step}


async def run_ingestion(sandbox: BaseSandbox, repo: Repo) -> IngestResult:
    """Step 5: ``python ingestion.py`` inside ``/sentinel-workspace/context``,
    with real-time log streaming.

    Uses :meth:`BaseSandbox.execute_streaming` so stdout / stderr are
    streamed back via callbacks that ``log.info`` every line (tagged with
    ``step=ingest``, ``repo_id``, ``sandbox_name``) while the script runs.
    Provider-specific session / process plumbing lives inside the
    concrete adapter; the pipeline stays provider-agnostic.
    """

    command_str = (
        f"cd /home/user/{WORKSPACE_DIR}/context && "
        f'REPO_PATH="/home/user/{WORKSPACE_DIR}/{repo.repo_name}" '
        f'DATASET_NAME="{_dataset_name_for(repo)}" '
        f'OPENAI_API_KEY="{settings.openai_api_key}" '
        f"PYTHONUNBUFFERED=1 python -u ingestion.py"
    )

    def _on_stdout(chunk: str) -> None:
        log.info(f"[stdout:run_ingestion]:{chunk}")

    def _on_stderr(chunk: str) -> None:
        log.error(f"[stderr:run_ingestion]:{chunk}")

    # envs: dict[str, str] = {}
    # if settings.openai_api_key:
    #     envs["OPENAI_API_KEY"] = settings.openai_api_key

    response = await sandbox.execute_streaming(
        command_str,
        on_stdout=_on_stdout,
        on_stderr=_on_stderr,
        timeout=300,
    )

    full_stdout = (response.stdout or "") + (response.stderr or "")
    return IngestResult(
        exit_code=response.exit_code,
        stdout=full_stdout.strip(),
    )


# --------------------------------------------------------------------------- #
# step 6: stop sandbox                                                        #
# --------------------------------------------------------------------------- #


async def stop_sandbox(sandbox: BaseSandbox) -> None:
    """Step 6: stop the sandbox. The registered ``on_pause`` hook
    handles the DB row update."""
    await sandbox.stop()


# --------------------------------------------------------------------------- #
# orchestrator                                                                #
# --------------------------------------------------------------------------- #


async def indexing_pipeline(
    *,
    repos: list[IndexingRepo],
    user_id: str,
    spec: E2BSandboxSpec,
) -> list[IndexingItemResult]:
    """Run the full indexing pipeline for each repo, sequentially.

    One ``try / except / finally`` wraps the entire loop. The pipeline
    owns its DB session via :func:`async_session_maker` and is safe to
    run as a background task.

    The pipeline only ever talks to :class:`BaseSandbox`; provider
    selection is encoded in ``spec``.
    """
    results: list[IndexingItemResult] = []
    started: list[BaseSandbox] = []

    async with async_session_maker() as session:
        try:
            for payload in repos:
                db_repo = await save_repo(session, user_id=user_id, payload=payload)
                sandbox = await init_sandbox(
                    session,
                    spec=spec,
                    user_id=user_id,
                    repo=db_repo,
                )
                started.append(sandbox)

                clone = await clone_repo(sandbox, db_repo)
                if clone.exit_code != 0:
                    log.error(
                        "git clone failed",
                        extra={
                            **_log_ctx(
                                repo_id=db_repo.id,
                                sandbox_name=sandbox.sandbox_name,
                                step="clone",
                            ),
                            "exit_code": clone.exit_code,
                            "stdout": clone.stdout or "",
                        },
                    )
                    # await sandbox.kill()
                else:
                    log.info(
                        "step:[git clone]: finished",
                        extra=_log_ctx(
                            repo_id=db_repo.id,
                            sandbox_name=sandbox.sandbox_name,
                            step="clone",
                        ),
                    )
                    await upload_scripts(sandbox)
                    log.info(
                        "step:[scripts upload]: finished",
                        extra=_log_ctx(
                            repo_id=db_repo.id,
                            sandbox_name=sandbox.sandbox_name,
                            step="upload",
                        ),
                    )
                    ingest = await run_ingestion(sandbox, db_repo)
                    log.info(
                        "step:[ingestion]: finished",
                        extra={
                            **_log_ctx(
                                repo_id=db_repo.id,
                                sandbox_name=sandbox.sandbox_name,
                                step="ingest",
                            ),
                            "exit_code": ingest.exit_code,
                        },
                    )
                    log.info(
                        f"step:[ingestion]:output: {ingest.stdout} , exit_code:{ingest.exit_code}"
                    )
                    if ingest.exit_code != 0:
                        log.error(
                            f"ingestion failed (exit_code={ingest.exit_code})\n"
                            f"--- script output ---\n"
                            f"{ingest.stdout or '<no output captured>'}\n"
                            f"--- end ---",
                            extra={
                                **_log_ctx(
                                    repo_id=db_repo.id,
                                    sandbox_name=sandbox.sandbox_name,
                                    step="ingest",
                                ),
                                "exit_code": ingest.exit_code,
                            },
                        )

                results.append(
                    IndexingItemResult(
                        repo_id=db_repo.id,
                        sandbox_id=sandbox.id,
                        state=SandboxState.STARTED,
                    )
                )

        except SandboxAlreadyActive:
            raise
        except Exception:
            log.exception("indexing pipeline crashed")
        # finally:
        #     for sb in started:
        #         try:
        #             await stop_sandbox(sb)
        #         except Exception:
        #             log.exception(
        #                 "failed to stop sandbox",
        #                 extra={"sandbox_id": sb.id or None},
        #             )

    return results
