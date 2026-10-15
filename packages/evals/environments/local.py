"""Local environment: a temp dir acting as the sandbox root.

``LocalBackend`` subclasses ``BaseSandbox`` and implements only the
four abstract members: ``execute`` runs the command in the sandbox dir
(through Git Bash ``sh`` on Windows so the base-class POSIX helpers
keep working), ``upload``/``download`` copy bytes on disk, and ``id``
names the backend. ``read``/``ls``/``grep``/``glob``/``edit`` come
free from the base class (all built on ``execute``).
"""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileData,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    LsResult,
    ReadResult,
)
from deepagents.backends.sandbox import BaseSandbox

from environments.base import BaseSandboxService, EnvConfig, EnvError

_GIT_SH_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Git\bin\sh.exe",
    r"C:\Program Files (x86)\Git\bin\sh.exe",
)

_SANDBOX_HOME_ALIAS = "/home/user"
"""Production layout root the review workers hardcode.

The local backend mounts its temp dir at this path: commands have the
alias rewritten to the temp root, and ``_resolve`` maps the alias back
to the temp dir. Docker/E2B have a real ``/home/user`` and need no
shim.
"""


def _mount(command: str, root: str) -> str:
    """Rewrite the ``/home/user`` prefix to the sandbox temp root."""
    prefix = root.rstrip("/")
    out: list[str] = []
    i = 0
    alias = _SANDBOX_HOME_ALIAS
    while True:
        hit = command.find(alias, i)
        if hit == -1:
            out.append(command[i:])
            break
        after = hit + len(alias)
        boundary = after == len(command) or command[after] in ("/", "'", '"', " ", "\t", "\n")
        if boundary and command[hit:after] == alias:
            out.append(command[i:hit])
            out.append(prefix)
            i = after
        else:
            out.append(command[i:after])
            i = after
    return "".join(out)


def _posix_path(path: Path) -> str:
    text = str(path)
    if os.name != "nt":
        return text
    drive, rest = os.path.splitdrive(text)
    if drive:
        return "/" + drive[0].lower() + rest.replace("\\", "/")
    return text.replace("\\", "/")


def _find_sh() -> str | None:
    if os.name != "nt":
        return None
    for candidate in _GIT_SH_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return shutil.which("sh")


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return ""


class LocalBackend(BaseSandbox):
    """``BaseSandbox`` over a host temp directory."""

    def __init__(self, root: Path, posix_prefix: str, backend_id: str) -> None:
        self._root = root
        self._posix_prefix = posix_prefix.rstrip("/")
        self._backend_id = backend_id
        self._sh = _find_sh()

    @property
    def id(self) -> str:
        return self._backend_id

    def execute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse:
        command = _mount(command, self._posix_prefix or "/home/user")
        try:
            if self._sh is None:
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(self._root),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            else:
                completed = subprocess.run(
                    [self._sh, "-c", command],
                    cwd=str(self._root),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
        except subprocess.TimeoutExpired as exc:
            combined = _as_text(exc.stdout) + _as_text(exc.stderr)
            return ExecuteResponse(output=combined[-8000:], exit_code=124)
        except Exception as exc:
            return ExecuteResponse(
                output=f"execute failed: {type(exc).__name__}: {exc}"[:2000],
                exit_code=-1,
            )
        stdout_text = _as_text(completed.stdout)
        stderr_text = _as_text(completed.stderr)
        output = stdout_text + stderr_text
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
            try:
                dest = self._resolve(raw_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
                responses.append(FileUploadResponse(path=raw_path, error=None))
            except Exception as exc:
                responses.append(
                    FileUploadResponse(
                        path=raw_path,
                        error=f"upload failed: {type(exc).__name__}: {exc}",
                    )
                )
        return responses

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        return await asyncio.to_thread(self.upload_files, files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for raw_path in paths:
            try:
                src = self._resolve(raw_path)
                if not src.is_file():
                    responses.append(
                        FileDownloadResponse(
                            path=raw_path, content=None, error="file_not_found"
                        )
                    )
                    continue
                responses.append(
                    FileDownloadResponse(
                        path=raw_path, content=src.read_bytes(), error=None
                    )
                )
            except Exception as exc:
                responses.append(
                    FileDownloadResponse(
                        path=raw_path,
                        content=None,
                        error=f"download failed: {type(exc).__name__}: {exc}",
                    )
                )
        return responses

    async def adownload_files(
        self, paths: list[str]
    ) -> list[FileDownloadResponse]:
        return await asyncio.to_thread(self.download_files, paths)

    def _resolve(self, raw_path: str) -> Path:
        cleaned = raw_path.strip().replace("\\", "/")
        if self._posix_prefix and cleaned.startswith(self._posix_prefix):
            rel = cleaned[len(self._posix_prefix) :].lstrip("/")
        elif cleaned == _SANDBOX_HOME_ALIAS or cleaned.startswith(
            _SANDBOX_HOME_ALIAS + "/"
        ):
            rel = cleaned[len(_SANDBOX_HOME_ALIAS) :].lstrip("/")
        else:
            rel = cleaned.lstrip("/")
        if not rel:
            return self._root
        return self._root.joinpath(*Path(rel).parts)

    def _posix(self, native: Path) -> str:
        try:
            rel = native.relative_to(self._root).as_posix()
        except ValueError:
            return _posix_path(native)
        if rel == ".":
            return self._posix_prefix
        return self._posix_prefix + "/" + rel

    # Native file helpers: the base class builds POSIX ``python3`` one-liners
    # that a native Windows interpreter cannot resolve, so local reads and
    # listings run in-process instead of through the shell.

    def _read_native(self, path: str, offset: int, limit: int) -> ReadResult:
        src = self._resolve(path)
        if not src.is_file():
            return ReadResult(error=f"File '{path}': file_not_found")
        try:
            raw = src.read_bytes()
        except OSError as exc:
            return ReadResult(error=f"File '{path}': {exc.strerror or exc}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return ReadResult(
                file_data=FileData(
                    content=base64.b64encode(raw[: 500 * 1024]).decode("ascii"),
                    encoding="base64",
                )
            )
        lines = text.splitlines()
        page = lines[max(offset, 0) : max(offset, 0) + max(limit, 0)]
        content = "\n".join(page)
        if len(content.encode("utf-8")) > 500 * 1024:
            content = content[: 500 * 1024]
        return ReadResult(file_data=FileData(content=content, encoding="utf-8"))

    def read(
        self, file_path: str, offset: int = 0, limit: int = 2000
    ) -> ReadResult:
        return self._read_native(file_path, offset, limit)

    async def aread(
        self, file_path: str, offset: int = 0, limit: int = 2000
    ) -> ReadResult:
        return await asyncio.to_thread(self._read_native, file_path, offset, limit)

    def _ls_native(self, path: str) -> LsResult:
        target = self._resolve(path)
        if not target.exists():
            return LsResult(error=f"Path '{path}': path_not_found")
        if target.is_file():
            return LsResult(
                entries=[
                    FileInfo(
                        path=path,
                        is_dir=False,
                        size=target.stat().st_size,
                    )
                ]
            )
        entries: list[FileInfo] = []
        try:
            children = sorted(target.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            return LsResult(error=f"Path '{path}': {exc.strerror or exc}")
        for child in children:
            try:
                entries.append(
                    FileInfo(
                        path=self._posix(child),
                        is_dir=child.is_dir(),
                        size=child.stat().st_size if child.is_file() else 0,
                    )
                )
            except OSError:
                continue
        return LsResult(entries=entries)

    def ls(self, path: str) -> LsResult:
        return self._ls_native(path)

    async def als(self, path: str) -> LsResult:
        return await asyncio.to_thread(self._ls_native, path)

    def _glob_native(self, pattern: str, path: str | None) -> GlobResult:
        base = self._resolve(path or self._posix_prefix)
        if not base.is_dir():
            return GlobResult(error=f"Path '{path}': path_not_found")
        if "**" in pattern:
            hits = [p for p in base.rglob("*") if fnmatch.fnmatch(p.name, pattern.replace("**/", ""))]
        else:
            hits = [
                p
                for p in base.iterdir()
                if p.is_file() and fnmatch.fnmatch(p.name, pattern)
            ]
        return GlobResult(
            matches=[
                FileInfo(
                    path=self._posix(p),
                    is_dir=False,
                    size=p.stat().st_size,
                )
                for p in sorted(hits)
            ]
        )

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        return self._glob_native(pattern, path)

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        return await asyncio.to_thread(self._glob_native, pattern, path)


class LocalService(BaseSandboxService):
    """Create / reconnect / destroy local sandbox dirs."""

    def __init__(self, cfg: EnvConfig) -> None:
        super().__init__(cfg)
        self._root: Path | None = None
        self._posix_root: str | None = None

    @property
    def sandbox_root(self) -> str | None:
        return self._posix_root

    async def create(self) -> LocalBackend | EnvError:
        try:
            base = Path(self.cfg.workdir) if self.cfg.workdir else None
            if base is not None:
                base.mkdir(parents=True, exist_ok=True)
            self._root = Path(
                tempfile.mkdtemp(prefix="sentinel-eval-", dir=str(base) if base else None)
            )
            self._posix_root = _posix_path(self._root)
            backend = LocalBackend(
                self._root,
                self._posix_root,
                backend_id=f"local-{uuid.uuid4().hex[:12]}",
            )
            self._backend = backend
            return backend
        except Exception as exc:
            return EnvError(
                message=f"local create failed: {type(exc).__name__}: {exc}",
                provider="local",
            )

    async def connect(self, sandbox_id: str) -> LocalBackend | EnvError:
        _ = sandbox_id
        return await self.create()

    async def kill(self) -> None | EnvError:
        try:
            if self._root is not None and self._root.exists():
                shutil.rmtree(self._root, ignore_errors=True)
            self._root = None
            self._posix_root = None
            self._backend = None
            return None
        except Exception as exc:
            return EnvError(
                message=f"local kill failed: {type(exc).__name__}: {exc}",
                provider="local",
            )


__all__ = ["LocalBackend", "LocalService"]
