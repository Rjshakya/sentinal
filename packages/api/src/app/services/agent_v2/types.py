"""Agent-v2 service types: ctx + planner contracts.

This module owns the *contract* of the v2 agent family (the planning
agent and the per-file review agents): the :class:`AgentV2Ctx`
(identity + injected live dependencies) and the serializable planner
payloads (:class:`PlannerContext` / :class:`FileContext`) plus the
host-side join inputs (:class:`ChunkInventory` / :class:`FileReviewJob`).

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.github`,
:mod:`app.services.llm`, and :mod:`app.services.sandbox`. Ids that
are also identifiers (id, ctx) keep their single-word lowercase form.

Design notes:

- :class:`AgentV2Ctx` carries identity plus injected live dependencies (the lane's chat model and
  the sandbox handle), assembled by the ctx factory
  (:func:`app.services.agent_v2.service.createAgentV2Ctx`) at the
  edge. **Not serializable** — it carries a :class:`BaseChatModel`,
  so it never crosses a durable boundary; callers build it per
  run inside their steps.
- :class:`PlannerContext` is the structured planner output, validated
  by the plan-extractor step via ``with_structured_output``. It is
  **enrichment only**: the host fans out over the split chunks (the
  diff truth), never over the planner's file list.
- :class:`ChunkInventory` is the host-side truth (parsed off the
  ``splitted_diffs/`` chunk headers by the list-chunks step).
- :class:`FileReviewJob` is the join of the two: one serializable job
  per file agent, built by the pure
  :func:`app.workflows.review_v2.steps.combine.buildFileReviewJobs`.
- Ids are **branded types** (``NewType`` over ``str`` / ``int`` from
  :mod:`app.utils.branded`): they erase at runtime (Pydantic
  validation is unaffected) but pyright enforces the branding
  statically, so a bare ``str`` cannot accidentally flow into a ctx.
"""

from __future__ import annotations

from typing import Any, TypeAlias

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.services.sandbox.types import SandboxCtx
from app.utils.branded import CommitId, PRNumber, RepoId, RepoName, UserId

DeepAgentGraph: TypeAlias = CompiledStateGraph[Any, Any, Any, Any]
"""The compiled langgraph state graph returned by ``create_deep_agent``.

The four ``Any`` type arguments mirror the graph's
``[StateT, ContextT, InputT, OutputT]`` parameterization; they are
explicit so the alias stays fully typed under strict checking and any
``CompiledStateGraph`` instance is assignable to it.

Re-declared here so the v2 package owns its own graph alias.
"""

_DEFAULT_MODEL_CALL_RUN_LIMIT = 120
_DEFAULT_TOOL_CALL_RUN_LIMIT = 120


class AgentV2Ctx(BaseModel):
    """Everything one v2-agent build needs, as one object.

    The ctx is assembled by
    :func:`app.services.agent_v2.service.createAgentV2Ctx` at the
    edge and consumed by :func:`createPlanningAgent` /
    :func:`createFileReviewAgent`. It carries:

    - the run identity (user, repo, PR, head SHA) — branded,
    - the agent's chat model (injected — the service never builds
      models itself),
    - the sandbox handle the agent's tools read from,
    - the per-run model/tool call limits applied to the middleware
      stack (smaller defaults than the v1 lanes: the planner explores
      with a bounded budget and each file agent sees one chunk).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    userId: UserId
    repoId: RepoId
    repoName: RepoName
    prNumber: PRNumber
    headSha: CommitId
    model: BaseChatModel
    systemPrompt: str
    """The agent's chat model. One instance per agent so each can carry
    its own per-agent callback handler."""
    sandboxCtx: SandboxCtx
    """The run's sandbox handle; the agent's backend reads the PR
    diff artefacts (``overview.md`` / ``splitted_diffs/``) from it."""
    modelCallRunLimit: int = Field(
        default=_DEFAULT_MODEL_CALL_RUN_LIMIT,
        ge=1,
        description="Ceiling on model calls per run (middleware cap).",
    )
    toolCallRunLimit: int = Field(
        default=_DEFAULT_TOOL_CALL_RUN_LIMIT,
        ge=1,
        description="Ceiling on tool executions per run (middleware cap).",
    )


class FileContext(BaseModel):
    """Planner-provided enrichment for one changed file.

    Pure data (durable-serializable). Every field is advisory context for
    the file agent — never a review gate. ``file`` keys the join
    against the host-side chunk inventory by exact match.
    """

    model_config = ConfigDict(frozen=True)

    file: str = Field(
        min_length=1,
        description="Path relative to the repo root, exactly as it "
        "appears in the chunk header (e.g. 'src/app/routers/ai.py').",
    )
    focus: list[str] = Field(
        default_factory=list,
        description="Review lenses the planner suggests for this file "
        "(e.g. 'correctness', 'security', 'blast-radius').",
    )
    crossFileContext: str = Field(
        default="",
        description="Cross-file callers / callees / shared contracts "
        "and flows touching this file (bounded by the join step).",
    )
    relevantSymbols: list[str] = Field(
        default_factory=list,
        description="Symbols the planner flags as relevant "
        "(e.g. 'def:verify_token', 'model:Session').",
    )


class PlannerContext(BaseModel):
    """The structured planner output (extractor-validated).

    Repo-level context (``repoMap`` / ``dataFlows`` /
    ``sharedConcerns``) goes to every file agent; each
    :class:`FileContext` goes only to its file's agent. An empty
    instance (all defaults) is valid — it means the planner degraded
    and file agents review with the diff alone.
    """

    model_config = ConfigDict(frozen=True)

    repoMap: str = Field(
        default="",
        description="Major systems, entrypoints, and public surfaces "
        "of the repo relevant to this PR.",
    )
    dataFlows: str = Field(
        default="",
        description="Representative end-to-end control/data flows "
        "touching the changed files.",
    )
    sharedConcerns: str = Field(
        default="",
        description="Auth / contract / config risks every file agent "
        "must keep in mind.",
    )
    fileContexts: list[FileContext] = Field(
        default_factory=list,
        description="Per-file enrichment, keyed by exact file path.",
    )


class ChunkRef(BaseModel):
    """One observed chunk: the real code path plus its on-disk diff file.

    Pure data (durable-serializable). Both fields are observed in the
    sandbox by the list-chunks step — never recomputed — so dotted-name
    collisions (``a/b.c`` vs ``a.b/c``) and odd paths (spaces, unicode)
    cannot silently point two jobs at one chunk.
    """

    model_config = ConfigDict(frozen=True)

    filePath: str = Field(
        min_length=1,
        description="Real code path under review, exactly as it appears "
        "in the chunk header (e.g. 'src/app/routers/ai.py').",
    )
    diffPath: str = Field(
        min_length=1,
        description="Exact on-disk chunk file name in splitted_diffs/ "
        "(e.g. 'src.app.routers.ai.py.md') — the file whose gutter "
        "line numbers GitHub anchors come from.",
    )


class ChunkInventory(BaseModel):
    """Host-side truth: what the split step actually wrote.

    Parsed off the ``splitted_diffs/`` chunk headers
    (``<chunk file>:### <real path>`` via ``grep -H``) by the
    list-chunks step — the dotted on-disk names are observed, never
    trusted for the real path and never recomputed. ``skippedFiles``
    mirrors the split summary (binary / rename-only sections with no
    chunk).
    """

    model_config = ConfigDict(frozen=True)

    actualFiles: list[str] = Field(
        description="Real paths with a reviewable chunk, sorted.",
    )
    chunks: list[ChunkRef] = Field(
        default_factory=list,
        description="One ref per reviewable chunk: the real code path "
        "plus its exact on-disk diff file. Same order as actualFiles.",
    )
    skippedFiles: list[str] = Field(
        default_factory=list,
        description="Diff paths with no chunk (binary, rename-only).",
    )


class FileReviewJob(BaseModel):
    """One serializable job for one per-file review agent.

    Built by the pure
    :func:`app.workflows.review_v2.steps.combine.buildFileReviewJobs`
    join over the :class:`ChunkInventory` (truth) and the
    :class:`PlannerContext` (enrichment). ``filePath`` is the real code
    path (what the finding block's ``file:`` field must contain);
    ``diffPath`` is the exact on-disk chunk file (where GitHub anchors
    come from). ``hasPlannerContext`` records whether the planner
    actually covered this file, so gaps are visible in logs instead of
    silent.
    """

    model_config = ConfigDict(frozen=True)

    filePath: str = Field(
        min_length=1,
        description="Real code path under review (has a chunk).",
    )
    diffPath: str = Field(
        min_length=1,
        description="Exact on-disk chunk file name in splitted_diffs/ "
        "for this file (observed, never recomputed).",
    )
    focus: list[str] = Field(default_factory=list)
    crossFileContext: str = Field(default="")
    relevantSymbols: list[str] = Field(default_factory=list)
    hasPlannerContext: bool = Field(
        default=False,
        description="True when the planner supplied a FileContext for "
        "this file; False means the file is reviewed with diff alone.",
    )


__all__ = [
    "AgentV2Ctx",
    "ChunkInventory",
    "ChunkRef",
    "DeepAgentGraph",
    "FileContext",
    "FileReviewJob",
    "PlannerContext",
]
