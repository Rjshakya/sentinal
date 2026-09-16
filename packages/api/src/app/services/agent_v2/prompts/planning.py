"""Prompts for the v2 planning agent: repo exploration + per-file enrichment.

Two builders, both pure formatting (no I/O, no LLM):

- :func:`createPlanningSystemPrompt` — the exploration rubric. Takes
  narrow scalars (identity + tool budget) so the budget line is baked
  into the wording and the function stays unit-testable without a
  live chat model.
- :func:`createPlanningUserPrompt` — the run-specific message: the
  concrete diff-dir path, the host-side file inventory (so the
  planner spends its budget exploring, not discovering what
  changed), the repo root, and the PR's claimed intent. The diff
  itself is never inlined.
- :data:`SUBMIT_PLAN_TOOL_DESCRIPTION` — the contract text bound to
  the ``submit_plan`` tool at agent build time (field meanings,
  exact-path rule, call-once). Wording lives here; the tool
  mechanics live in :mod:`app.services.agent_v2.service`.

The planner is **enrichment-only**: the host fans out over the
inventory (the diff truth), never over the planner's file list — a
planner miss costs context, never a review.
"""

from __future__ import annotations

from app.services.agent_v2.prompts.shared import (
    getReviewDiffDirPath,
    identityHeader,
    prMetaBlock,
)
from app.services.agent_v2.types import AgentV2Ctx
from app.utils.util import repo_path

SUBMIT_PLAN_TOOL_DESCRIPTION: str = """\
Submit the complete review plan. Call exactly once, as your final act — no text after this call.

- repoMap: major systems, entrypoints, and public surfaces relevant to this PR.
- dataFlows: representative end-to-end control/data flows touching the changed files.
- sharedConcerns: auth / contract / config risks every file reviewer must keep in mind.
- fileContexts: one entry per inventoried file — file copied EXACTLY from the inventory, focus lenses for that file, cross-file callers / callees / shared contracts touching it, relevant symbols. Cover every inventoried file; invent no paths.

Empty sections are allowed ("" or []) — but the call itself is mandatory. A duplicate call simply overwrites.
"""


def createPlanningSystemPrompt(
    *,
    repoName: str,
    userId: str,
    modelCallRunLimit: int,
    toolCallRunLimit: int,
) -> str:
    """Build the system prompt for the planning agent.

    Pure formatting over narrow scalars — no ctx, no live
    dependencies. The budget line carries the run's actual call
    caps so the planner sizes its exploration to them.
    """
    return f"""\

## Planner Agent

You are a senior software engineer acting as the review planner for a GitHub PR.
You review nothing yourself and produce zero findings or comments. Your job is
to explore the repo and the PR's changed files, then hand each per-file
reviewer the context it needs: what its file does, which lenses to apply,
and which cross-file callers, callees, and shared contracts touch it.

You are enrichment-only: the host fans out over its own file inventory, never
over your file list — a file you miss is still reviewed, just with less
context. Be thorough, but a gap costs context, never a review.

Your user message carries the changed-file list (inventory). Explore those
files and the repo around them, then submit one plan covering every
inventoried file.

## Budget

You have at most ~{modelCallRunLimit} model calls and ~{toolCallRunLimit} tool calls for this run. You are not free: every call costs time and money. Spend them exploring, never inventorying: the changed-file list is given, so do not waste calls discovering what changed. Two or three deep reads per relevant area beat ten shallow ones.

Wrap-up rule: reserve your final calls for the `submit_plan` call — never spend your last ~10 tool calls exploring. If the budget runs low, submit what you have: partial context beats no submission, and an unsubmitted plan wastes every call before it.

## Strict context sources

- overview.md in the Diff dir (four buckets: Added / Removed / Renamed / Modified) — start here, it shows the PR's shape in ~30 seconds.
- splitted_diffs/ — one review file per changed file: a `### <real path>` header plus a fenced diff with LEFT/RIGHT gutter line numbers.
- The repo root, through read-only tools (read_file, grep, glob, ls). The `execute` tool, if present, is for read-only inspection only — never write, create, or modify files. NEVER write anywhere.

## Method

1. Manifests first: dependency files, configs, entrypoints — learn how the repo is built, run, and configured.
2. Major systems: top-level directories, public surfaces, module boundaries. Name a system only with evidence — a file or symbol you actually opened.
3. Representative flows touching the changed files: callers → changed code → callees; state or persistence touched; failure handling around it; configuration it reads; operations or integrations involved.
4. Confirm with focused evidence: neighboring implementations, focused tests, callers and callees of the changed symbols.
5. Stop when the major systems touching this PR are evidence-backed. No exhaustive inventory, no generic advice.

## Submission (your final act)

Your run ends with EXACTLY ONE `submit_plan` tool call carrying the complete plan — no text after it. The tool persists your plan for the downstream readers; anything not passed to it is lost. Field meanings are in the `submit_plan` tool description — same sections, submitted as arguments, not prose. Never write output files directly (no `execute` heredocs, no uploads for output) — the host owns the plan location and it is never named in your messages.
"""


def createPlanningUserPrompt(
    ctx: AgentV2Ctx,
    *,
    actualFiles: list[str],
    title: str,
    body: str,
    author: str,
) -> str:
    """Build the user message for the planning agent.

    Pure formatting — no I/O, no LLM. Carries the concrete diff-dir
    path plus the host-side file inventory (so the planner spends its
    budget exploring, not discovering what changed), the repo root,
    and the PR's claimed intent. The diff itself is never inlined.
    """
    diff_dir = getReviewDiffDirPath(
        workDir=ctx.sandboxCtx.rootPath,
        prNumber=ctx.prNumber,
        headSha=ctx.headSha,
    )
    files_block = "\n".join(f"- {path}" for path in actualFiles) or "- (none)"

    return (
        identityHeader(
            repoName=ctx.repoName,
            repoId=ctx.repoId,
            userId=ctx.userId,
            prNumber=ctx.prNumber,
            headSha=ctx.headSha,
            diffDir=diff_dir,
            repoRoot=repo_path(ctx.repoName),
        )
        + f"\n"
        + prMetaBlock(title=title, body=body, author=author)
        + f"\n"
        f"Changed files with reviewable diffs ({len(actualFiles)}):\n"
        f"{files_block}\n"
        f"\n"
        f"The PR diff artefacts live in the Diff dir above. Use "
        f"strictly overview.md and the per-file review files under "
        f"splitted_diffs/ for diff context — nothing else. Review-file "
        f"names flatten the path: `src/app/a.py` → `src.app.a.py.md`. "
        f"`ls splitted_diffs/` to confirm.\n"
        f"\n"
        f"End your run with exactly one submit_plan call carrying the "
        f"complete plan for all {len(actualFiles)} file(s) above.\n"
    )


__all__ = [
    "SUBMIT_PLAN_TOOL_DESCRIPTION",
    "createPlanningSystemPrompt",
    "createPlanningUserPrompt",
]
