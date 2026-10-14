"""Sandbox-phase steps: create, clone, index, diff, split, chunks, destroy.

Each step validates its input first, runs one review_v2 worker, and
returns ``model_dump(mode="json")``. Imports on top. Fail-closed infra
steps let exceptions propagate for SDK retry; the handler marks the run
FAILED when retries exhaust.
"""

from __future__ import annotations

import logging

from async_durable_execution import durable_callable
from langfuse import observe
from pydantic import BaseModel, ConfigDict

from app.services.sandbox.types import SandboxCtx
from app.utils.branded import (
    InstallationId,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)
from app.workflows.review_v2.steps.clone_repo_v2 import cloneRepoV2Step
from app.workflows.review_v2.steps.codegraph_index import installCodeGraphAndIndexRepoStep
from app.workflows.review_v2.steps.create_sandbox import createSandboxStep
from app.workflows.review_v2.steps.fetch_diff import fetchDiffStep
from app.workflows.review_v2.steps.kill_sandbox import killSandboxStep
from app.workflows.review_v2.steps.list_chunks import listChunkFilesStep
from app.workflows.review_v2.steps.split_diff import splitDiffStep
from app.workflows.review_v2.types import ReviewWorkflowInput

log = logging.getLogger(__name__)


@durable_callable
@observe(name="create-sandbox", capture_input=False, capture_output=False)
async def createEphemeralSandbox(*, sandbox: dict) -> dict:
    """Create the run sandbox; returns SandboxCtx dump with sandboxId."""
    sandboxCtx = SandboxCtx.model_validate(sandbox)
    created = await createSandboxStep(sandboxCtx=sandboxCtx)
    return created.model_dump(mode="json")


class CloneInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    workflowInput: ReviewWorkflowInput
    repoId: RepoId
    repoOwner: RepoOwner
    repoName: RepoName
    installationId: InstallationId


@durable_callable
@observe(name="clone-pr-head", capture_input=False, capture_output=False)
async def clonePrHead(*, input: dict) -> dict:
    """Clone + detached-head checkout (fail-closed)."""
    request = CloneInput.model_validate(input)
    parsed = request.workflowInput
    cloned = await cloneRepoV2Step(
        sandboxCtx=request.sandbox,
        userId=UserId(parsed.userId),
        repoId=request.repoId,
        repoOwner=request.repoOwner,
        repoName=request.repoName,
        prNumber=parsed.prNumber,
        headSha=parsed.headSha,
        githubInstallationId=request.installationId,
    )
    return cloned.model_dump(mode="json")


class IndexInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    workflowInput: ReviewWorkflowInput
    repoId: RepoId
    repoName: RepoName


@durable_callable
@observe(name="index-codegraph", capture_input=False, capture_output=False)
async def indexCodegraph(*, input: dict) -> dict:
    """Install codegraph CLI + index the PR tree (fail-closed)."""
    request = IndexInput.model_validate(input)
    parsed = request.workflowInput
    indexed = await installCodeGraphAndIndexRepoStep(
        sandboxCtx=request.sandbox,
        userId=UserId(parsed.userId),
        repoId=request.repoId,
        repoName=request.repoName,
        prNumber=parsed.prNumber,
        headSha=parsed.headSha,
    )
    return indexed.model_dump(mode="json")


class DiffInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    workflowInput: ReviewWorkflowInput
    repoId: RepoId
    repoName: str


@durable_callable
@observe(name="fetch-pr-diff", capture_input=False, capture_output=False)
async def fetchPrDiff(*, input: dict) -> dict:
    """Write file.diff for diffBaseSha-or-baseSha...headSha."""
    request = DiffInput.model_validate(input)
    parsed = request.workflowInput
    fetched = await fetchDiffStep(
        sandboxCtx=request.sandbox,
        repoId=request.repoId,
        repoName=request.repoName,
        prNumber=parsed.prNumber,
        headSha=parsed.headSha,
        baseSha=parsed.baseSha,
        diffBaseSha=parsed.diffBaseSha,
    )
    return fetched.model_dump(mode="json")


class SplitInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    workflowInput: ReviewWorkflowInput
    repoId: RepoId


@durable_callable
@observe(name="split-pr-diff", capture_input=False, capture_output=False)
async def splitPrDiff(*, input: dict) -> dict:
    """Split file.diff into overview.md + per-file chunks."""
    request = SplitInput.model_validate(input)
    parsed = request.workflowInput
    return dict(
        await splitDiffStep(
            sandboxCtx=request.sandbox,
            repoId=request.repoId,
            prNumber=parsed.prNumber,
            headSha=parsed.headSha,
        )
    )


@durable_callable
@observe(name="list-diff-chunks", capture_input=False, capture_output=False)
async def listDiffChunks(*, input: dict) -> dict:
    """Inventory splitted_diffs/ into ChunkInventory (the diff truth)."""
    request = SplitInput.model_validate(input)
    parsed = request.workflowInput
    listed = await listChunkFilesStep(
        sandboxCtx=request.sandbox,
        repoId=request.repoId,
        prNumber=parsed.prNumber,
        headSha=parsed.headSha,
    )
    return listed.model_dump(mode="json")


@durable_callable
@observe(name="destroy-sandbox", capture_input=False, capture_output=False)
async def destroySandbox(*, sandbox: dict) -> dict:
    """Destroy the ephemeral sandbox (best-effort, never raises)."""
    sandboxCtx = SandboxCtx.model_validate(sandbox)
    await killSandboxStep(sandboxCtx=sandboxCtx)
    return {}


__all__ = [
    "clonePrHead",
    "createEphemeralSandbox",
    "destroySandbox",
    "fetchPrDiff",
    "indexCodegraph",
    "listDiffChunks",
    "splitPrDiff",
]
