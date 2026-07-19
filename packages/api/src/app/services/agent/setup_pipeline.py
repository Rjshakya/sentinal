"""Setup agent pipeline — Functional Core / Imperative Shell.

Three rings, three ring-boundaries, one outermost ``try / except``:

- **Ring 1 (pure)**       — :func:`build_authenticated_clone_url`,
  :func:`truncate_command_output`, :func:`classify_git_clone_exit_code`,
  :func:`flatten_pipeline_error_to_setup_result`. No I/O, no session,
  no client, no clock. Testable with ``assert f(x) == y``.

- **Ring 2 (orchestration)** — :func:`run_setup_pipeline`. The only
  function that sequences the I/O calls and threads the ``Result``
  value through. Has a single outermost ``try / except`` that catches
  anything escaping the typed pipeline (programmer bugs, unhandled
  SDK errors, ``asyncio.CancelledError``) and converts it to
  ``Err(SetupAgentCrashed(...))``.

- **Ring 3 (shell / I/O)**  — the protocol adapters
  (:class:`E2BInstallTokenMinter`, :class:`E2BSetupAgentRunner`) and
  the :func:`find_installation_for_user` wrapper. Each one is the
  single boundary into an external SDK and is the only place that
  catches the SDK's exceptions and turns them into typed ``Err``
  variants.

No pure function contains a ``try / except``. No I/O function
contains inline decision logic beyond the trivial "None → Err"
policy that turns a missing row into a typed error.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.core.github_app import mint_installation_token
from app.core.llm import LLMProviderStr
from app.core.result import Err, Ok, Result
from app.core.sandbox import BaseSandbox, CommandResult
from app.models.installation import Installation
from app.repositories import Repository
from app.schemas.setup import SetupRepo
from app.services.agent.models import SetupResult
from app.services.agent.setup import run_setup
from app.services.agent.setup_errors import (
    GitCloneFailed,
    InstallationNotFound,
    InstallTokenMintFailed,
    SetupAgentCrashed,
    SetupAgentReturnedNoStructuredResponse,
    SetupPipelineError,
)
from app.utils.util import workspace_path

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Ports                                                                        #
# --------------------------------------------------------------------------- #


class InstallTokenMinter(Protocol):
    """Mint a GitHub installation token.

    Implementations are responsible for catching the underlying SDK's
    exceptions and returning ``Err(InstallTokenMintFailed(...))`` —
    the protocol's return type is a ``Result``, not a bare ``str``.
    """

    async def mint(
        self, github_installation_id: int
    ) -> Result[str, InstallTokenMintFailed]: ...


# --------------------------------------------------------------------------- #
# Concrete adapters (shell — these catch SDK exceptions)                      #
# --------------------------------------------------------------------------- #


class E2BInstallTokenMinter:
    """Production adapter for :class:`InstallTokenMinter`.

    Wraps :func:`app.core.github_app.mint_installation_token` and
    converts any exception into ``Err(InstallTokenMintFailed(...))``.
    """

    async def mint(
        self, github_installation_id: int
    ) -> Result[str, InstallTokenMintFailed]:
        try:
            token: str = await mint_installation_token(github_installation_id)
        except Exception as exc:
            log.exception(
                "mint_installation_token failed: installation_id=%s",
                github_installation_id,
            )
            return Err(InstallTokenMintFailed(cause=f"{type(exc).__name__}: {exc}"))
        return Ok(token)


class SetupAgentRunner:
    """Production adapter for :class:`InstallTokenMinter`.

    Wraps :func:`app.services.agent.setup.run_setup` (the LLM-SDK
    edge) and forwards the result. The agent invocation itself is
    exception-safe; this adapter is a pure pass-through that holds
    the LLM configuration.
    """

    _llm_provider: LLMProviderStr
    _llm_base_url: str | None
    _llm_api_key: str
    _llm_model: str

    def __init__(
        self,
        *,
        llm_provider: LLMProviderStr,
        llm_base_url: str | None,
        llm_api_key: str,
        llm_model: str,
    ) -> None:
        self._llm_provider = llm_provider
        self._llm_base_url = llm_base_url
        self._llm_api_key = llm_api_key
        self._llm_model = llm_model

    async def run(
        self,
        *,
        repo_id: str,
        repo_name: str,
        user_id: str,
        sandbox: BaseSandbox,
    ) -> Result[
        SetupResult,
        SetupAgentCrashed | SetupAgentReturnedNoStructuredResponse,
    ]:
        return await run_setup(
            repo_id=repo_id,
            repo_name=repo_name,
            user_id=user_id,
            sandbox=sandbox.sandbox,  # type: ignore[attr-defined]
            llm_provider=self._llm_provider,
            llm_base_url=self._llm_base_url,
            llm_api_key=self._llm_api_key,
            llm_model=self._llm_model,
        )


# --------------------------------------------------------------------------- #
# Shell helper (DB lookup with typed Result return)                           #
# --------------------------------------------------------------------------- #


async def find_installation_for_user(
    installation_repo: Repository[Installation],
    *,
    user_id: str,
    installation_id: str,
) -> Result[Installation, InstallationNotFound]:
    """Look up the user's :class:`Installation` row.

    Issues a single ``SELECT ... WHERE id = ? AND user_id = ?`` (via
    :meth:`Repository.find_by_fields`). Returns ``Err(InstallationNotFound)``
    if no row matches; the policy "the row's user_id must match the
    caller" is enforced at the DB level, not in code.
    """
    installation = await installation_repo.find_by_fields(
        id=installation_id,
        user_id=user_id,
    )
    if installation is None:
        return Err(
            InstallationNotFound(
                installation_id=installation_id,
                user_id=user_id,
            )
        )
    return Ok(installation)


# --------------------------------------------------------------------------- #
# Ring 1 — pure helpers                                                       #
# --------------------------------------------------------------------------- #


def build_authenticated_clone_url(*, install_token: str, owner: str, name: str) -> str:
    """Build the authenticated HTTPS clone URL.

    GitHub's recommended way to authenticate git operations from CI:
    embed the install token as the basic-auth user
    (``x-access-token:<token>``). Works for both public and private
    repos.
    """
    return f"https://x-access-token:{install_token}@github.com/{owner}/{name}.git"


def truncate_command_output(result: CommandResult, *, max_chars: int = 500) -> str:
    """Take a :class:`CommandResult` and return a string tail.

    Prefers ``stderr`` (which usually has the failure cause), falls
    back to ``stdout``, strips, and truncates to ``max_chars``.
    """
    raw = (result.stderr or result.stdout or "").strip()
    return raw[:max_chars]


def classify_git_clone_exit_code(
    *, exit_code: int, output_tail: str
) -> Result[None, GitCloneFailed]:
    """Map a ``git clone`` exit code to ``Result[None, GitCloneFailed]``."""
    if exit_code == 0:
        return Ok(None)
    return Err(GitCloneFailed(exit_code=exit_code, output_tail=output_tail))


def flatten_pipeline_error_to_setup_result(
    error: SetupPipelineError,
) -> SetupResult:
    """Convert any :class:`SetupPipelineError` variant to an HTTP-shaped
    ``ok=False`` :class:`SetupResult`.

    Pure — single ``match`` over the closed union. The router is the
    only place that calls this; every other layer treats errors as
    ``Result[SetupResult, SetupPipelineError]``.
    """
    match error:
        case InstallationNotFound(installation_id, user_id):
            notes = (
                f"installation_id={installation_id!r} does not "
                f"belong to user_id={user_id!r}"
            )
        case InstallTokenMintFailed(cause):
            notes = f"mint_installation_token failed: {cause}"
        case GitCloneFailed(exit_code, output_tail):
            notes = f"git clone failed (exit_code={exit_code}): {output_tail}"
        case SetupAgentCrashed(cause):
            notes = f"setup pipeline crashed: {cause}"
        case SetupAgentReturnedNoStructuredResponse(message_kinds):
            notes = (
                "setup agent returned no structured_response "
                f"(messages={list(message_kinds)})"
            )
    return SetupResult(
        ok=False,
        ecosystem="none",
        manager=None,
        install_cmd=None,
        duration_s=0.0,
        notes=notes,
        bootstrapped_tools=[],
    )


# --------------------------------------------------------------------------- #
# Ring 2 — orchestrator                                                        #
# --------------------------------------------------------------------------- #


async def run_setup_pipeline(
    *,
    user_id: str,
    input: SetupRepo,
    installation_repo: Repository[Installation],
    install_token_minter: InstallTokenMinter,
    sandbox: BaseSandbox,
    setup_agent_runner: SetupAgentRunner,
    clone_timeout_s: float = 300.0,
) -> Result[SetupResult, SetupPipelineError]:
    """Run the full setup pipeline for a single repo.

    Sequence: lookup installation → mint token → prepare workspace →
    git clone → run LLM agent. Each stage returns a ``Result``; an
    ``Err`` short-circuits to the caller without inspecting later
    stages.

    The single outermost ``try / except`` is the *net* for anything
    that escapes the typed pipeline — a programmer bug, a sandbox
    SDK error that wasn't anticipated, ``asyncio.CancelledError``.
    Real failure modes are encoded as :class:`SetupPipelineError`
    variants and pass through ``return Err(...)`` returns, *not*
    through exceptions.

    The ``sandbox`` argument must be an already-connected
    :class:`BaseSandbox` (the router has called ``await
    sandbox.create()``). The router also owns the matching
    ``sandbox.kill()`` call in its own ``try / finally``.
    """
    try:
        # step 1
        installation_result = await find_installation_for_user(
            installation_repo,
            user_id=user_id,
            installation_id=input.installation_id,
        )
        if isinstance(installation_result, Err):
            return Err(installation_result.error)
        installation: Installation = installation_result.value

        # step 2
        token_result = await install_token_minter.mint(
            installation.github_installation_id
        )
        if isinstance(token_result, Err):
            return Err(token_result.error)
        install_token: str = token_result.value

        # step 3
        await sandbox.fs_create_folder(workspace_path())
        clone = await sandbox.execute(
            f"git clone "
            f"{build_authenticated_clone_url(install_token=install_token, owner=input.owner, name=input.name)} "
            f"{input.name}",
            cwd=workspace_path(),
            timeout=clone_timeout_s,
        )
        clone_check = classify_git_clone_exit_code(
            exit_code=clone.exit_code,
            output_tail=truncate_command_output(clone),
        )
        if isinstance(clone_check, Err):
            return Err(clone_check.error)

        # step 4 : running core agent loop
        return await setup_agent_runner.run(
            repo_id=str(input.id),
            repo_name=input.name,
            user_id=user_id,
            sandbox=sandbox,
        )
    except Exception as exc:
        log.exception(
            "setup pipeline crashed: owner=%s name=%s",
            input.owner,
            input.name,
        )
        return Err(SetupAgentCrashed(cause=f"{type(exc).__name__}: {exc}"))


__all__ = [
    "E2BInstallTokenMinter",
    "InstallTokenMinter",
    "SetupAgentRunner",
    "build_authenticated_clone_url",
    "classify_git_clone_exit_code",
    "find_installation_for_user",
    "flatten_pipeline_error_to_setup_result",
    "run_setup_pipeline",
    "truncate_command_output",
]
