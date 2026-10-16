"""Environment contract: lifecycle over a LangChain ``BaseSandbox`` backend.

The service owns the lifecycle (``create`` / ``connect`` / ``kill``);
the backend owns the commands. New sandbox kinds only add a service
plus a ``BaseSandbox`` child that implements ``execute``,
``upload_files``, ``download_files`` and ``id`` -- every other helper
(``read``, ``ls``, ``grep``, ``glob``, ``edit``, ``write``) comes free
from the base class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from deepagents.backends.sandbox import BaseSandbox
from pydantic import BaseModel, ConfigDict, Field

EnvKind = Literal["e2b", "docker", "local"]


class EnvConfig(BaseModel):
    """Everything one environment run needs, as pure serializable data."""

    model_config = ConfigDict(frozen=True)

    kind: EnvKind = Field(default="local")
    root_path: str = Field(default="/home/user")
    image: str = Field(default="")
    api_key: str = Field(default="")
    template: str = Field(default="")
    timeout_s: int = Field(default=1200, ge=1)
    workdir: str = Field(default="")


class EnvError(BaseModel):
    """Provider-level failure, returned as a value (never raised)."""

    model_config = ConfigDict(frozen=True)

    message: str
    provider: str = Field(default="")
    id: str = Field(default="/evals/environments")

    def __str__(self) -> str:
        return self.message


class BaseSandboxService(ABC):
    """Lifecycle for one sandbox kind."""

    def __init__(self, cfg: EnvConfig) -> None:
        self.cfg: EnvConfig = cfg
        self._backend: BaseSandbox | None = None

    @property
    def backend(self) -> BaseSandbox | None:
        return self._backend

    @property
    def sandbox_root(self) -> str | None:
        """In-sandbox absolute root agents must build paths from."""
        return None

    @abstractmethod
    async def create(self) -> BaseSandbox | EnvError:
        """Make a fresh sandbox and hold it. Writes nothing else."""

    @abstractmethod
    async def connect(self, sandbox_id: str) -> BaseSandbox | EnvError:
        """Resume a sandbox by id and hold it."""

    @abstractmethod
    async def kill(self) -> None | EnvError:
        """Destroy the held sandbox. Best-effort; never raises."""


def createEnvironment(kind: EnvKind, cfg: EnvConfig) -> BaseSandboxService:
    """Build the service for ``kind``. Raises for unknown kinds only."""
    # Local imports keep provider SDKs out of the import graph until used.
    if kind == "local":
        from environments.local import LocalService

        return LocalService(cfg)
    if kind == "docker":
        from environments.docker import DockerService

        return DockerService(cfg)
    if kind == "e2b":
        from environments.e2b import E2BService

        return E2BService(cfg)
    raise ValueError(f"unknown environment kind: {kind!r}")


__all__ = [
    "BaseSandboxService",
    "EnvConfig",
    "EnvError",
    "EnvKind",
    "createEnvironment",
]
