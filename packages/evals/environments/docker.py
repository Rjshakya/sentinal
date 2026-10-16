"""Docker environment: one container per run, driven via the CLI.

``DockerBackend`` subclasses ``BaseSandbox`` and implements only the
four abstract members over ``docker exec`` / ``docker cp``. All other
helpers (``read``, ``ls``, ``grep``, ``glob``) come free from the base
class. ``DockerService`` owns the container lifecycle.
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

from environments.base import BaseSandboxService, EnvConfig, EnvError

_DEFAULT_IMAGE = "python:3.13-slim"
_START_TIMEOUT_S = 120


def runDockerCommand(args: list[str], *, timeout: int | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class DockerBackend(BaseSandbox):
    """``BaseSandbox`` over ``docker exec`` in one container."""

    def __init__(self, container_id: str) -> None:
        self._container_id = container_id

    @property
    def id(self) -> str:
        return self._container_id

    def execute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse:
        try:
            completed = runDockerCommand(
                ["exec", self._container_id, "sh", "-c", command],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(output="docker exec timed out", exit_code=124)
        except FileNotFoundError:
            return ExecuteResponse(
                output="docker CLI not found on PATH", exit_code=-1
            )
        except Exception as exc:
            return ExecuteResponse(
                output=f"docker exec failed: {type(exc).__name__}: {exc}"[:2000],
                exit_code=-1,
            )
        output = (completed.stdout or "") + (completed.stderr or "")
        return ExecuteResponse(
            output=output[-8000:],
            exit_code=completed.returncode,
            truncated=len(output) > 8000,
        )

    async def aexecute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    def upload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for raw_path, content in files:
            responses.append(self.uploadSingleFile(raw_path, content))
        return responses

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        return await asyncio.to_thread(self.upload_files, files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for raw_path in paths:
            responses.append(self.downloadSingleFile(raw_path))
        return responses

    async def adownload_files(
        self, paths: list[str]
    ) -> list[FileDownloadResponse]:
        return await asyncio.to_thread(self.download_files, paths)

    def uploadSingleFile(self, raw_path: str, content: bytes) -> FileUploadResponse:
        cleaned = raw_path.strip().lstrip("/")
        try:
            with tempfile.TemporaryDirectory(prefix="sentinel-docker-up-") as tmp:
                local = Path(tmp) / Path(*Path(cleaned).parts).name
                local.write_bytes(content)
                parent = str(Path("/") / Path(cleaned).parent)
                mkdir = runDockerCommand(
                    ["exec", self._container_id, "mkdir", "-p", parent],
                    timeout=30,
                )
                if mkdir.returncode != 0:
                    return FileUploadResponse(
                        path=raw_path,
                        error=f"mkdir failed: {(mkdir.stderr or '').strip()[:300]}",
                    )
                copied = runDockerCommand(
                    ["cp", str(local), f"{self._container_id}:/{cleaned}"],
                    timeout=60,
                )
                if copied.returncode != 0:
                    return FileUploadResponse(
                        path=raw_path,
                        error=f"docker cp failed: {(copied.stderr or '').strip()[:300]}",
                    )
                return FileUploadResponse(path=raw_path, error=None)
        except FileNotFoundError:
            return FileUploadResponse(path=raw_path, error="docker CLI not found")
        except Exception as exc:
            return FileUploadResponse(
                path=raw_path,
                error=f"upload failed: {type(exc).__name__}: {exc}",
            )

    def downloadSingleFile(self, raw_path: str) -> FileDownloadResponse:
        cleaned = raw_path.strip().lstrip("/")
        try:
            with tempfile.TemporaryDirectory(prefix="sentinel-docker-dl-") as tmp:
                local = Path(tmp) / f"dl-{uuid.uuid4().hex[:8]}"
                pulled = runDockerCommand(
                    ["cp", f"{self._container_id}:/{cleaned}", str(local)],
                    timeout=60,
                )
                if pulled.returncode != 0:
                    return FileDownloadResponse(
                        path=raw_path, content=None, error="file_not_found"
                    )
                target = local / Path(cleaned).name if local.is_dir() else local
                if not target.is_file():
                    candidates = list(local.rglob("*"))
                    file_hit = next(
                        (c for c in candidates if c.is_file()), None
                    )
                    if file_hit is None:
                        return FileDownloadResponse(
                            path=raw_path, content=None, error="file_not_found"
                        )
                    target = file_hit
                return FileDownloadResponse(
                    path=raw_path, content=target.read_bytes(), error=None
                )
        except FileNotFoundError:
            return FileDownloadResponse(
                path=raw_path, content=None, error="docker CLI not found"
            )
        except Exception as exc:
            return FileDownloadResponse(
                path=raw_path,
                content=None,
                error=f"download failed: {type(exc).__name__}: {exc}",
            )


class DockerService(BaseSandboxService):
    """Start / reuse / remove one container per eval run."""

    def __init__(self, cfg: EnvConfig) -> None:
        super().__init__(cfg)
        self._container_id: str | None = None

    @property
    def image(self) -> str:
        return self.cfg.image or _DEFAULT_IMAGE

    async def create(self) -> DockerBackend | EnvError:
        try:
            completed = await asyncio.to_thread(
                runDockerCommand,
                [
                    "run",
                    "-d",
                    "--rm",
                    self.image,
                    "sleep",
                    "infinity",
                ],
                timeout=_START_TIMEOUT_S,
            )
        except FileNotFoundError:
            return EnvError(message="docker CLI not found on PATH", provider="docker")
        except Exception as exc:
            return EnvError(
                message=f"docker run failed: {type(exc).__name__}: {exc}",
                provider="docker",
            )
        if completed.returncode != 0:
            err = (completed.stderr or "").strip()[:500]
            return EnvError(message=f"docker run failed: {err}", provider="docker")
        container_id = (completed.stdout or "").strip()
        if not container_id:
            return EnvError(message="docker run returned no id", provider="docker")
        # Ensure git + python exist for the clone/diff/split flow.
        setup = "command -v git >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1"
        backend = DockerBackend(container_id)
        try:
            check = await backend.aexecute(setup, timeout=30)
        except Exception as exc:
            await self.removeContainer(container_id)
            return EnvError(
                message=f"docker setup check failed: {type(exc).__name__}: {exc}",
                provider="docker",
            )
        if check.exit_code != 0:
            install_cmd = (
                "apt-get update >/dev/null 2>&1 && "
                "apt-get install -y --no-install-recommends git python3 >/dev/null 2>&1; "
                "command -v git >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1"
            )
            try:
                installed = await backend.aexecute(install_cmd, timeout=300)
            except Exception as exc:
                await self.removeContainer(container_id)
                return EnvError(
                    message=f"docker setup failed: {type(exc).__name__}: {exc}",
                    provider="docker",
                )
            if installed.exit_code != 0:
                await self.removeContainer(container_id)
                return EnvError(
                    message="docker image has no git/python3 and install failed",
                    provider="docker",
                )
        # Quote the workdir for sh: single-quote and escape inner quotes.
        _ = shlex.quote(self.cfg.root_path)
        self._container_id = container_id
        self._backend = backend
        return backend

    async def connect(self, sandbox_id: str) -> DockerBackend | EnvError:
        try:
            completed = await asyncio.to_thread(
                runDockerCommand, ["inspect", "-f", "{{.State.Running}}", sandbox_id],
                timeout=30,
            )
        except FileNotFoundError:
            return EnvError(message="docker CLI not found on PATH", provider="docker")
        except Exception as exc:
            return EnvError(
                message=f"docker inspect failed: {type(exc).__name__}: {exc}",
                provider="docker",
            )
        if completed.returncode != 0 or "true" not in (completed.stdout or ""):
            return EnvError(
                message=f"docker container not running: {sandbox_id[:12]}",
                provider="docker",
            )
        backend = DockerBackend(sandbox_id)
        self._container_id = sandbox_id
        self._backend = backend
        return backend

    async def kill(self) -> None | EnvError:
        if self._container_id is None:
            self._backend = None
            return None
        await self.removeContainer(self._container_id)
        self._container_id = None
        self._backend = None
        return None

    async def removeContainer(self, container_id: str) -> None:
        try:
            await asyncio.to_thread(
                runDockerCommand, ["rm", "-f", container_id], timeout=60
            )
        except Exception:
            return


__all__ = ["DockerBackend", "DockerService"]
