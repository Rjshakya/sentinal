"""Indexing pipeline.

Functional, per-item pipeline. Each step is a top-level ``async def``
that operates on a single repo (or sandbox) and returns a typed value.
The orchestrator ``indexing_pipeline`` is a single ``for`` loop wrapped
in a single ``try / except / finally`` block; it owns its own DB
session via :func:`async_session_maker` and runs sequentially per repo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from daytona import (
    AsyncDaytona,
    CreateSandboxFromImageParams,
    Image,
    Resources,
    SessionExecuteRequest,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.core.sandbox import Sandbox, SandboxAlreadyActive
from app.models.enums import SandboxState
from app.models.repo import Repo
from app.schemas.indexing import IndexingRepo

log = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).parent / "sandbox_scripts"


def _log_ctx(*, repo_id: str, sandbox_name: str | None, step: str) -> dict:
    """Common ``extra`` payload for every pipeline log line."""
    return {"repo_id": repo_id, "sandbox_name": sandbox_name, "step": step}


def build_sandbox_image() -> Image:
    """Declarative Daytona image with ingestion deps baked in.

    Cached per runner for 24h; subsequent runs on the same runner reuse
    the built image and skip the ``pip install`` step.
    """
    return (
        Image.debian_slim("3.13")
        .pip_install(
            [
                "cognee",
                "tree-sitter-language-pack",
            ]
        )
        .run_commands(
            "apt-get update && "
            "apt-get install -y --no-install-recommends git curl && "
            "rm -rf /var/lib/apt/lists/*"
        )
        .add_local_file(
            str(SCRIPTS_DIR / "extensions" / "libjson.lbug_extension"),
            "/root/.kuzu/extensions/libjson.lbug_extension",
        )
        .run_commands(
            "mkdir -p /root/.kuzu/extensions && "
            "chmod 755 /root/.kuzu/extensions /root/.kuzu/extensions/libjson.lbug_extension"
        )
        .workdir("/workspace")
    )


# --------------------------------------------------------------------------- #
# result types (frozen dataclasses)
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
# step 1: save repo
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
# step 2: init sandbox
# --------------------------------------------------------------------------- #


async def init_sandbox(
    session: AsyncSession,
    *,
    sandbox_provider: AsyncDaytona,
    user_id: str,
    repo: Repo,
) -> Sandbox:
    """Step 2: create a Daytona sandbox and persist a ``STARTED`` row.

    Raises :class:`SandboxAlreadyActive` if an active sandbox already
    exists for the (user, repo) pair.
    """
    sandbox_name = f"{repo.repo_name}-sandbox"
    provider_params = CreateSandboxFromImageParams(
        name=sandbox_name,
        image=build_sandbox_image(),
        resources=Resources(cpu=1, memory=1, disk=8),
    )
    sandbox = Sandbox(
        provider=sandbox_provider,
        user_id=user_id,
        repo_id=repo.id,
    )
    await sandbox.create(
        session=session,
        sandbox_name=sandbox_name,
        provider_params=provider_params,
    )
    return sandbox


# --------------------------------------------------------------------------- #
# step 3: clone repo
# --------------------------------------------------------------------------- #


async def clone_repo(sandbox: Sandbox, repo: Repo) -> CloneResult:
    """Step 3: ``git clone --depth 1`` inside the sandbox.

    Returns the exit code in the result; never raises on a non-zero exit.
    """
    repo_dir = f"/workspace/{repo.repo_name}"
    response = await sandbox.execute(
        f"git clone --depth 1 {repo.url} {repo_dir}",
    )
    return CloneResult(
        repo_path=repo_dir,
        exit_code=response.exit_code,
        stdout=response.result or "",
    )


# --------------------------------------------------------------------------- #
# step 4: upload scripts
# --------------------------------------------------------------------------- #


async def upload_scripts(sandbox: Sandbox) -> None:
    """Step 4: copy chunking.py, ingestion.py, sandbox.env into /workspace/context."""
    context_dir = "/workspace/context"
    await sandbox.create_folder(context_dir)
    for src_name in ("chunking.py", "ingestion.py", "sandbox.env"):
        src = SCRIPTS_DIR / src_name
        if not src.exists():
            raise FileNotFoundError(f"Indexing file missing: {src}")
        dst_name = ".env" if src_name == "sandbox.env" else src_name
        await sandbox.upload_file(str(src), f"{context_dir}/{dst_name}")


# --------------------------------------------------------------------------- #
# step 5: run ingestion
# --------------------------------------------------------------------------- #


def _dataset_name_for(repo: Repo) -> str:
    return f"{repo.repo_name}"


async def run_ingestion(sandbox: Sandbox, repo: Repo) -> IngestResult:
    """Step 5: ``python ingestion.py`` inside /workspace/context, with real-time log streaming.

    Uses Daytona's session API so stdout/stderr are streamed back via
    callbacks that ``log.info`` every line (tagged with ``step=ingest``,
    ``repo_id``, ``sandbox_name``) while the script runs. Blocks until
    the command exits, then returns the exit code and full output.
    """
    daytona_sb = sandbox.sandbox
    if daytona_sb is None:
        return IngestResult(exit_code=-1, stdout="sandbox not initialized")

    session_id = f"ingest-{repo.id}"
    await daytona_sb.process.create_session(session_id)

    # SessionExecuteRequest has no cwd/env fields, so set them inline.
    command_str = (
        f"cd /workspace/context && "
        f'REPO_PATH="/workspace/{repo.repo_name}" '
        f'DATASET_NAME="{_dataset_name_for(repo)}" '
        f"PYTHONUNBUFFERED=1 python -u ingestion.py"
    )
    cmd = await daytona_sb.process.execute_session_command(
        session_id,
        SessionExecuteRequest(command=command_str, run_async=True),
    )

    sandbox_name = getattr(daytona_sb, "name", None)
    stream_buf: dict[str, str] = {"stdout": "", "stderr": ""}

    def _drain(stream: str, chunk: str | None) -> None:
        if not chunk:
            return
        buf = stream_buf[stream] + chunk
        lines = buf.split("\n")
        stream_buf[stream] = lines[-1]
        for line in lines[:-1]:
            if not line:
                continue
            try:
                log.info(
                    f"[ingest {stream}] {line}",
                    extra={
                        **_log_ctx(
                            repo_id=repo.id, sandbox_name=sandbox_name, step="ingest"
                        ),
                        "stream": stream,
                        "line": line,
                    },
                )
            except Exception:
                log.exception(
                    "ingest log callback failed",
                    extra={"stream": stream, "repo_id": repo.id},
                )

    def _on_stdout(chunk: str) -> None:
        _drain("stdout", chunk)

    def _on_stderr(chunk: str) -> None:
        _drain("stderr", chunk)

    # Blocks until the command exits.
    await daytona_sb.process.get_session_command_logs_async(
        session_id,
        cmd.cmd_id,
        _on_stdout,
        _on_stderr,
    )

    for stream in ("stdout", "stderr"):
        tail = stream_buf[stream]
        if tail:
            try:
                log.info(
                    f"[ingest {stream}] {tail}",
                    extra={
                        **_log_ctx(
                            repo_id=repo.id, sandbox_name=sandbox_name, step="ingest"
                        ),
                        "stream": stream,
                        "line": tail,
                    },
                )
            except Exception:
                log.exception(
                    "ingest log tail flush failed",
                    extra={"stream": stream, "repo_id": repo.id},
                )
            stream_buf[stream] = ""

    # After streaming completes, fetch the exit code and full output.
    final_cmd = await daytona_sb.process.get_session_command(session_id, cmd.cmd_id)
    final_logs = await daytona_sb.process.get_session_command_logs(
        session_id, cmd.cmd_id
    )

    full_stdout = ((final_logs.stdout or "") + (final_logs.stderr or "")).strip()
    return IngestResult(
        exit_code=final_cmd.exit_code if final_cmd.exit_code is not None else 0,
        stdout=full_stdout,
    )


# --------------------------------------------------------------------------- #
# step 6: stop sandbox
# --------------------------------------------------------------------------- #


async def stop_sandbox(session: AsyncSession, sandbox: Sandbox) -> None:
    """Step 6: stop the Daytona sandbox (and update the DB row, if the
    underlying ``Sandbox.stop`` allows it).
    """
    await sandbox.stop(session=session)


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #


async def indexing_pipeline(
    *,
    repos: list[IndexingRepo],
    user_id: str,
    sandbox_provider: AsyncDaytona,
) -> list[IndexingItemResult]:
    """Run the full indexing pipeline for each repo, sequentially.

    One ``try / except / finally`` wraps the entire loop. The pipeline
    owns its DB session via :func:`async_session_maker` and is safe to
    run as a background task.
    """
    results: list[IndexingItemResult] = []
    started: list[Sandbox] = []

    async with async_session_maker() as session:
        try:
            for payload in repos:
                db_repo = await save_repo(session, user_id=user_id, payload=payload)
                sandbox = await init_sandbox(
                    session,
                    sandbox_provider=sandbox_provider,
                    user_id=user_id,
                    repo=db_repo,
                )
                started.append(sandbox)

                if sandbox.sandbox is None:
                    raise Exception(f"FAILED TO INITIATE SANDBOX FOR REPO:{payload.id}")

                await sandbox.sandbox.wait_for_sandbox_start()
                sandbox_name = getattr(sandbox.sandbox, "name", None)
                clone = await clone_repo(sandbox, db_repo)
                if clone.exit_code != 0:
                    log.error(
                        "git clone failed",
                        extra={
                            **_log_ctx(
                                repo_id=db_repo.id,
                                sandbox_name=sandbox_name,
                                step="clone",
                            ),
                            "exit_code": clone.exit_code,
                            "stdout": clone.stdout or "",
                        },
                    )
                else:
                    log.info(
                        "step finished",
                        extra=_log_ctx(
                            repo_id=db_repo.id,
                            sandbox_name=sandbox_name,
                            step="clone",
                        ),
                    )
                    await upload_scripts(sandbox)
                    log.info(
                        "step finished",
                        extra=_log_ctx(
                            repo_id=db_repo.id,
                            sandbox_name=sandbox_name,
                            step="upload",
                        ),
                    )
                    ingest = await run_ingestion(sandbox, db_repo)
                    log.info(
                        "step finished",
                        extra={
                            **_log_ctx(
                                repo_id=db_repo.id,
                                sandbox_name=sandbox_name,
                                step="ingest",
                            ),
                            "exit_code": ingest.exit_code,
                        },
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
                                    sandbox_name=sandbox_name,
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
        finally:
            for sb in started:
                try:
                    await stop_sandbox(session, sb)
                except Exception:
                    log.exception(
                        "failed to stop sandbox",
                        extra={"sandbox_id": getattr(sb, "id", None)},
                    )

    return results
