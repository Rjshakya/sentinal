"""Sandbox wrapper.

Owns the Daytona client and the ``sandboxes`` DB row. The rest of the
app talks to ``Sandbox``; nothing else imports Daytona directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from daytona import AsyncDaytona, AsyncSandbox, CreateSandboxFromImageParams
from daytona.common.process import ExecuteResponse
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import SandboxState
from app.models.sandbox import Sandbox as SandboxModel


class SandboxAlreadyActive(Exception):
    """Raised when an active sandbox already exists for the (user, repo) pair."""

    def __init__(self, existing_sandbox_id: str) -> None:
        self.existing_sandbox_id = existing_sandbox_id
        super().__init__(f"Sandbox {existing_sandbox_id} is already active")


async def active_sandbox(
    session: AsyncSession,
    user_id: str,
    repo_id: str,
) -> SandboxModel | None:
    query = select(SandboxModel).where(
        SandboxModel.repo_id == repo_id,
        SandboxModel.user_id == user_id,
        or_(
            SandboxModel.state == "STARTED",
            SandboxModel.state == "PAUSED",
            SandboxModel.state == "STOPPED",
        ),
    )
    result = await session.exec(query)
    return result.first()


class Sandbox:
    """Thin wrapper over a Daytona sandbox, plus its DB row.

    The class is constructed from an existing DB row. To create a new
    sandbox, use :meth:`Sandbox.create` (the factory).
    """

    def __init__(self, *, provider: AsyncDaytona, user_id: str, repo_id: str) -> None:
        self.provider: AsyncDaytona = provider
        self.sandbox: AsyncSandbox | None = None
        self.user_id = user_id
        self.repo_id = repo_id

    # ---- factory ----

    async def create(
        self,
        *,
        session: AsyncSession,
        sandbox_name: str,
        provider_params: CreateSandboxFromImageParams,
    ) -> tuple[SandboxModel, AsyncSandbox]:
        """Create a Daytona sandbox and persist a `STARTED` row.

        Raises :class:`SandboxAlreadyActive` if there is already an active
        sandbox for the same ``(user_id, repo_id)`` pair.

        """

        existing = await active_sandbox(
            session,
            self.user_id,
            self.repo_id,
        )
        if (
            existing
            and existing.daytona_sandbox_id
            and (existing.state == "PAUSED" or existing.state == "STOPPED")
        ):
            await self.start(session)
            sandbox = await self.get_sandbox(existing.daytona_sandbox_id)
            return existing, sandbox

        sandbox = await self.provider.create(provider_params)

        sandbox_record = SandboxModel(
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=sandbox_name,
            state=SandboxState.STARTED,
            daytona_sandbox_id=sandbox.id,
            started_at=datetime.now(UTC),
        )
        session.add(sandbox_record)
        self.sandbox = sandbox
        await session.commit()
        await session.refresh(sandbox_record)
        return sandbox_record, sandbox

    # ---- passthrough properties ----

    @property
    def id(self) -> str:
        if self.sandbox is None:
            raise Exception("[ERROR]:Cannot access sandbox before its creation")
        return self.sandbox.id

    # ---- Daytona operations ----

    async def get_sandbox(self, id: str) -> AsyncSandbox:
        """Resolve the live Daytona sandbox handle."""
        return await self.provider.get(id)

    async def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ExecuteResponse:

        if self.sandbox is None:
            raise Exception("SANDBOX:REFERENCE ERROR:CANNOT RUN EXECUTE")
        sb = self.sandbox
        return await sb.process.exec(command, cwd=cwd, env=env, timeout=timeout)

    async def upload_file(self, src: str, dst: str) -> None:
        """Upload a local file to the sandbox filesystem."""

        if self.sandbox is None:
            raise Exception("SANDBOX:REFERENCE ERROR:CANNOT RUN UPLOAD FILE")
        sb = self.sandbox
        await sb.fs.upload_file(src, dst)

    async def upload_bytes(self, content: bytes, dst: str) -> None:
        """Upload raw bytes to the sandbox filesystem."""
        if self.sandbox is None:
            raise Exception("SANDBOX:REFERENCE ERROR:CANNOT RUN UPLOAD BYTES")
        sb = self.sandbox
        await sb.fs.upload_file(content, dst)

    async def download_file(self, remote_path: str) -> bytes | None:
        if self.sandbox is None:
            raise Exception("SANDBOX:REFERENCE ERROR:CANNOT RUN DOWNLOAD FILE")
        sb = self.sandbox
        return await sb.fs.download_file(remote_path)

    async def read_file(self, remote_path: str) -> str:
        raw = await self.download_file(remote_path)
        if raw is None:
            return ""
        return raw.decode("utf-8", errors="ignore")

    async def create_folder(self, path: str, mode: str = "755") -> None:
        if self.sandbox is None:
            raise Exception("SANDBOX:REFERENCE ERROR:CANNOT RUN CREATE FOLDER")
        sb = self.sandbox
        await sb.fs.create_folder(path, mode)

    async def list_files(self, path: str = "/workspace") -> list[Any]:
        if self.sandbox is None:
            raise Exception("SANDBOX:REFERENCE ERROR:CANNOT RUN LIST FILES")
        sb = self.sandbox
        return await sb.fs.list_files(path)

    # ---- lifecycle ----

    async def _update_state(
        self,
        session: AsyncSession,
        *,
        sandbox_instance_id: str,
        sandbox_name: str,
        new_state: SandboxState,
        set_stopped_at: bool = False,
    ) -> None:

        query = select(SandboxModel).where(
            SandboxModel.daytona_sandbox_id == sandbox_instance_id
        )
        sandbox_record = await session.exec(query)
        sandbox_record = sandbox_record.first()

        if sandbox_record is None:
            raise Exception(
                f"[SANDBOX:_UPDATE_STATE]:No sandbox_record found for: {sandbox_instance_id}"
            )

        update_data = SandboxModel(
            state=new_state,
            sandbox_name=sandbox_name,
            user_id=self.user_id,
            repo_id=self.repo_id,
            stopped_at=datetime.now() if set_stopped_at else None,
        )

        sandbox_record.sqlmodel_update(update_data)
        session.add(sandbox_record)
        await session.commit()
        await session.refresh(sandbox_record)

    async def stop(self, *, session: AsyncSession) -> None:
        """Stop the Daytona sandbox and flip the row to STOPPED."""
        try:
            if self.sandbox is not None:
                sb = await self.provider.get(self.sandbox.id)
                await sb.stop()
                await self._update_state(
                    session,
                    sandbox_name=self.sandbox.name,
                    sandbox_instance_id=self.sandbox.id,
                    new_state=SandboxState.STOPPED,
                    set_stopped_at=True,
                )

        except Exception as e:
            print(f"[SANDBOX:STOP]:user:{self.user_id} , repo:{self.repo_id}", e)
            raise e

    async def delete(self, session: AsyncSession) -> None:
        """Delete the Daytona sandbox and flip the row to DELETED."""
        try:
            if self.sandbox is not None:
                sb = await self.provider.get(self.sandbox.id)
                await sb.delete()
                await self._update_state(
                    session,
                    sandbox_name=self.sandbox.name,
                    sandbox_instance_id=self.sandbox.id,
                    new_state=SandboxState.DELETED,
                    set_stopped_at=True,
                )
        except Exception as e:
            print(f"[SANDBOX:DELETE]:user:{self.user_id} , repo:{self.repo_id}", e)
            raise e

    async def archive(self, session: AsyncSession) -> None:
        try:
            if self.sandbox is not None:
                sb = await self.provider.get(self.sandbox.id)
                await sb.archive()
                await self._update_state(
                    session,
                    sandbox_name=self.sandbox.name,
                    sandbox_instance_id=self.sandbox.id,
                    new_state=SandboxState.ARCHIVED,
                    set_stopped_at=True,
                )
        except Exception as e:
            print(f"[SANDBOX:ARCHIVE]:user:{self.user_id} , repo:{self.repo_id}", e)
            raise e

    async def start(self, session: AsyncSession) -> None:
        try:
            if self.sandbox is not None:
                sandbox_instance = await self.provider.get(self.sandbox.id)
                await sandbox_instance.start()
                await self._update_state(
                    session,
                    sandbox_name=self.sandbox.name,
                    sandbox_instance_id=self.sandbox.id,
                    new_state=SandboxState.STARTED,
                    set_stopped_at=False,
                )
        except Exception as e:
            print(f"[SANDBOX:START]:user:{self.user_id} , repo:{self.repo_id}", e)
            raise e
