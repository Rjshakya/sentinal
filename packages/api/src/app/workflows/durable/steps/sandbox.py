"""Sandbox-phase steps: create, clone, index, diff, split, chunks, destroy.

Each step validates its input first, runs one review_v2 worker via
``asyncio.run``, and returns ``model_dump(mode="json")``. Imports on top.
Fail-closed infra steps let exceptions propagate for SDK retry; the
handler marks the run FAILED when retries exhaust.
"""

from __future__ import annotations

import asyncio
import logging

from aws_durable_execution_sdk_python import durable_step
from aws_durable_execution_sdk_python.types import StepContext
from pydantic import BaseModel, ConfigDict

from app.services.sandbox.types import SandboxCtx
from app.utils.branded import (
    CommitId,
    InstallationId,
    PRNumber,
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


@durable_step
def createEphemeralSandbox(_ctx: StepContext, *, sandbox: dict) -> dict:
    """Create the run sandbox; returns SandboxCtx dump with sandboxId."""
    sandboxCtx = SandboxCtx.model_validate(sandbox)
    return asyncio.run(createSandboxStep(sandboxCtx=sandboxCtx)).model_dump(mode="json")


class CloneInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    workflowInput: ReviewWorkflowInput
    repoId: RepoId
    repoOwner: RepoOwner
    repoName: RepoName
    installationId: InstallationId


@durable_step
def clonePrHead(_ctx: StepContext, *, input: dict) -> dict:
    """Clone + detached-head checkout (fail-closed)."""
    request = CloneInput.model_validate(input)
    parsed = request.workflowInput
    return asyncio.run(
        cloneRepoV2Step(
            sandboxCtx=request.sandbox,
            userId=UserId(parsed.userId),
            repoId=request.repoId,
            repoOwner=request.repoOwner,
            repoName=request.repoName,
            prNumber=parsed.prNumber,
            headSha=parsed.headSha,
            githubInstallationId=request.installationId,
        )
    ).model_dump(mode="json")


class IndexInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    workflowInput: ReviewWorkflowInput
    repoId: RepoId
    repoName: RepoName


@durable_step
def indexCodegraph(_ctx: StepContext, *, input: dict) -> dict:
    """Install codegraph CLI + index the PR tree (fail-closed)."""
    request = IndexInput.model_validate(input)
    parsed = request.workflowInput
    return asyncio.run(
        installCodeGraphAndIndexRepoStep(
            sandboxCtx=request.sandbox,
            userId=UserId(parsed.userId),
            repoId=request.repoId,
            repoName=request.repoName,
            prNumber=parsed.prNumber,
            headSha=parsed.headSha,
        )
    ).model_dump(mode="json")


class DiffInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    workflowInput: ReviewWorkflowInput
    repoId: RepoId
    repoName: str


@durable_step
def fetchPrDiff(_ctx: StepContext, *, input: dict) -> dict:
    """Write file.diff for diffBaseSha-or-baseSha...headSha."""
    request = DiffInput.model_validate(input)
    parsed = request.workflowInput
    return asyncio.run(
        fetchDiffStep(
            sandboxCtx=request.sandbox,
            repoId=request.repoId,
            repoName=request.repoName,
            prNumber=parsed.prNumber,
            headSha=parsed.headSha,
            baseSha=parsed.baseSha,
            diffBaseSha=parsed.diffBaseSha,
        )
    ).model_dump(mode="json")


class SplitInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox: SandboxCtx
    workflowInput: ReviewWorkflowInput
    repoId: RepoId


@durable_step
def splitPrDiff(_ctx: StepContext, *, input: dict) -> dict:
    """Split file.diff into overview.md + per-file chunks."""
    request = SplitInput.model_validate(input)
    parsed = request.workflowInput
    return dict(
        asyncio.run(
            splitDiffStep(
                sandboxCtx=request.sandbox,
                repoId=request.repoId,
                prNumber=parsed.prNumber,
                headSha=parsed.headSha,
            )
        )
    )


@durable_step
def listDiffChunks(_ctx: StepContext, *, input: dict) -> dict:
    """Inventory splitted_diffs/ into ChunkInventory (the diff truth)."""
    request = SplitInput.model_validate(input)
    parsed = request.workflowInput
    return asyncio.run(
        listChunkFilesStep(
            sandboxCtx=request.sandbox,
            repoId=request.repoId,
            prNumber=parsed.prNumber,
            headSha=parsed.headSha,
        )
    ).model_dump(mode="json")


@durable_step
def destroySandbox(_ctx: StepContext, *, sandbox: dict) -> dict:
    """Destroy the ephemeral sandbox (best-effort, never raises)."""
    sandboxCtx = SandboxCtx.model_validate(sandbox)
    asyncio.run(killSandboxStep(sandboxCtx=sandboxCtx))
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
