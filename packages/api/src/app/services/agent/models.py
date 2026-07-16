"""Pydantic models the review agent emits.

These are the structured-output schemas passed to
``create_deep_agent(response_format=...)``. They deliberately mirror
the shape of the DB tables (:class:`app.models.code_comment.CodeComment`
and :class:`app.models.review_summary.ReviewSummary`) but stay
independent: the DB layer maps ``commit_id`` / ``pr_id`` onto the
caller's choice, and the enums here are the agent's vocabulary, not
the ORM's.

If the two ever drift, the persistence layer is the one that has to
translate — never the agent, never the schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CommentSeverityStr = Literal["P1_CRITICAL", "P2_WARNING", "P3_NITPICK"]
CommentSideStr = Literal["RIGHT", "LEFT"]
ReviewVerdictStr = Literal["APPROVE", "COMMENT", "REQUEST_CHANGES"]


class CodeCommentDraft(BaseModel):
    """One inline review comment, as the agent wants to post it."""

    file_name: str = Field(
        description="Path of the file relative to the repo root, exactly "
        "as it appears in the diff header (e.g. 'src/app/routers/ai.py').",
    )
    comment: str = Field(
        description="The review comment body. Plain text; markdown is fine.",
    )
    severity: CommentSeverityStr
    from_line: int = Field(ge=1, description="First line of the comment range.")
    to_line: int = Field(ge=1, description="Last line of the comment range.")
    side: CommentSideStr = Field(
        default="RIGHT",
        description="'RIGHT' for the new side of the diff, 'LEFT' for the old.",
    )
    node_type: str | None = Field(
        default=None,
        description="Optional free-form label for the function/class/symbol "
        "the comment is anchored to (e.g. 'def:create_deep_agent').",
    )


class ReviewResult(BaseModel):
    """The full review payload the agent must return."""

    comments: list[CodeCommentDraft] = Field(
        default_factory=list,
        description="All inline comments the agent wants to post. Empty "
        "list is valid — it means 'looks good, no findings'.",
    )
    summary: str = Field(
        description="Short prose review (a few sentences). Surfaced as the "
        "GitHub PR review body by the dashboard.",
    )
    verdict: ReviewVerdictStr = Field(
        description="Overall review verdict. 'APPROVE' = ship it, "
        "'COMMENT' = ship if you address the nits, "
        "'REQUEST_CHANGES' = block on at least one P1_CRITICAL.",
    )


EcosystemStr = Literal["node", "python", "rust", "go", "ruby", "mixed", "none"]


class SetupResult(BaseModel):
    """Structured output of the setup deep-agent.

    Emitted as a single object (not a list) — the setup agent is a
    one-shot run, not a multi-finding sweep. The router turns this into
    a per-repo entry inside :class:`SetupAck`.
    """

    ok: bool = Field(
        description="True only when dependencies are installed and a "
        "post-install verification command exited 0. False on any "
        "failure (no manifest, install error, verification error)."
    )
    ecosystem: EcosystemStr = Field(
        default="none",
        description="Primary ecosystem of the repo, inferred from "
        "manifests. 'mixed' is reserved for repos that legitimately "
        "contain manifests from more than one ecosystem "
        "(e.g. a Python project with a JS frontend).",
    )
    manager: str | None = Field(
        default=None,
        description="Concrete package manager used for the install "
        "(e.g. 'pnpm', 'uv', 'cargo'). Must be one of the values in "
        "SETUP_AGENT_MANAGER_ALLOWLIST when ok=true.",
    )
    install_cmd: str | None = Field(
        default=None,
        description="The exact command that was run to install "
        "dependencies (e.g. 'pnpm install --frozen-lockfile').",
    )
    duration_s: float = Field(
        description="Wall-clock seconds the install took, measured on "
        "the host (between agent invocation and structured_response).",
    )
    notes: str = Field(
        description="Short human-readable summary of what happened. "
        "Empty when ok=true. On failure, names the failing step.",
    )
    bootstrapped_tools: list[str] = Field(
        default_factory=list,
        description="Tooling the agent had to install on demand "
        "(e.g. ['node', 'pnpm']). The base E2B image is python3-only; "
        "everything else is bootstrapped by the agent.",
    )
