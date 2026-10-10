"""Tracing service types: serializable Langfuse trace identity.

This module owns the contract of the tracing service: the pure-data
:class:`ReviewTraceCtx` (everything needed to attribute Langfuse
observations to one review run). It carries no live dependencies, so it
can be built inside durable steps from already-available run data and
never crosses a durable boundary itself.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.github`,
:mod:`app.services.llm`, and :mod:`app.services.sandbox`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReviewTraceCtx(BaseModel):
    """Trace identity for one review run (pure serializable data).

    Built per step from the run data the step already holds
    (``ReviewWorkflowInput`` + repo snapshot). ``sessionId`` groups all
    lanes of a run (planner + file lanes + extractor + summary) into
    one Langfuse session; ``userId`` becomes the Langfuse user.
    """

    model_config = ConfigDict(frozen=True)

    userId: str = Field(min_length=1, description="WorkOS user id (Langfuse user).")
    sessionId: str = Field(
        min_length=1,
        description="Stable per-run session id (Langfuse session).",
    )
    trigger: str = Field(
        default="opened", description="Run trigger ('opened' | 'comment' | 'repair')."
    )
    delivery: str | None = Field(
        default=None, description="GitHub delivery id, when the caller holds it."
    )
    repoId: str | None = Field(default=None, description="Local repos.id.")
    repoName: str | None = Field(default=None, description="Repo name (owner/name).")
    prNumber: int | None = Field(default=None, ge=1, description="PR number.")
    headSha: str | None = Field(default=None, description="PR head SHA.")
    baseSha: str | None = Field(default=None, description="PR base SHA.")
    llmModel: str | None = Field(
        default=None, description="Active 'provider:model' string, when known."
    )
    llmOrigin: str | None = Field(
        default=None, description="LLM config source ('system' | 'user')."
    )

    def tags(self) -> list[str]:
        """Low-cardinality tags for the run (no SHAs, no delivery ids)."""
        tags: list[str] = [f"trigger:{self.trigger}"]
        if self.repoName:
            tags.append(f"repo:{self.repoName}")
        if self.prNumber is not None:
            tags.append(f"pr:{self.prNumber}")
        return tags

    def metadata(self) -> dict[str, str | int | bool]:
        """Full run ids for the observation metadata (no secrets)."""
        metadata: dict[str, str | int | bool] = {}
        if self.delivery is not None:
            metadata["delivery"] = self.delivery
        if self.repoId is not None:
            metadata["repo_id"] = self.repoId
        if self.repoName is not None:
            metadata["repo_name"] = self.repoName
        if self.prNumber is not None:
            metadata["pr_number"] = self.prNumber
        if self.headSha is not None:
            metadata["head_sha"] = self.headSha
        if self.baseSha is not None:
            metadata["base_sha"] = self.baseSha
        if self.llmModel is not None:
            metadata["llm_model"] = self.llmModel
        if self.llmOrigin is not None:
            metadata["llm_origin"] = self.llmOrigin
        metadata["trigger"] = self.trigger
        return metadata


__all__ = ["ReviewTraceCtx"]
