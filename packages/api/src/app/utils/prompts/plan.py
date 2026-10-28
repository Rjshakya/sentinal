"""Planner prompts: triage the PR for downstream reviewers.

System prompt fixes the role (senior planner, no findings) and the
sandbox layout in generic terms. Session prompt carries the concrete
run: PR intent verbatim, exact read paths, and the exact plan-file
write target plus its JSONL schema.
"""

from __future__ import annotations

from app.utils.branded import CommitId, PRNumber, RepoName
from app.utils.sandbox_fs import (
    getOverviewFile,
    getPlanFile,
    getRepoDir,
    getSplittedDir,
    sentinelRoot,
)


def createPlanSystemPrompt() -> str:
    """Build the static system prompt for the planner agent."""
    return f"""\
You are a senior software engineer acting as the review planner for a GitHub PR.
You review nothing yourself and produce zero findings or comments.
Your job is to explore the repo and the PR changed files, then hand each
downstream reviewer the context it needs.

Sandbox layout (the working directory is already the sentinel root):
- {sentinelRoot()}/{{repo_name}}/ — the PR-head checkout, read-only context.
- {{run_dir}}/diff/overview.md — what changed, read first.
- {{run_dir}}/diff/splitted_diffs/ — one chunk per changed file, read second.
- {{run_dir}}/plan.jsonl — your only output file.

Rules:
- Read with read-only tools. Never write, create, or modify any file
  except the one plan file named in your session message.
- Never invent paths, symbols, or flows. Every claim stays traceable to
  a file you actually opened.
- Cover every changed file. When uncertain, list it thin — never drop it.
"""


def createPlanSessionPrompt(
    *,
    repoName: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
    title: str,
    body: str,
    author: str,
) -> str:
    """Build the run-specific session prompt for the planner agent."""
    name = str(repoName)
    sha = str(headSha)
    repoDir = getRepoDir(name)
    overviewFile = getOverviewFile(sha)
    splittedDir = getSplittedDir(sha)
    planFile = getPlanFile(sha)
    cleanTitle = title.strip() or "(untitled)"
    cleanBody = body.strip() or "(empty)"
    cleanAuthor = author.strip() or "(unknown)"
    return (
        f"Repo: {name}\n"
        f"PR number: {int(prNumber)}\n"
        f"Head SHA: {sha}\n"
        f"PR title: {cleanTitle}\n"
        f"PR author: {cleanAuthor}\n"
        f"PR description:\n{cleanBody}\n"
        f"\n"
        f"Read in this order:\n"
        f"1. {overviewFile} — the PR shape.\n"
        f"2. List {splittedDir}/ — one chunk per changed file.\n"
        f"3. The repo at {repoDir}/ — callers, callees, and shared contracts.\n"
        f"\n"
        f"Write the plan to exactly this file: {planFile}\n"
        f"One JSON object per line, one line per changed file:\n"
        f'{{"file": "<path relative to the repo root>", '
        f'"focus": "<suggested lenses>", '
        f'"symbols": "<relevant symbols>", '
        f'"context": "<callers, callees, shared contracts>"}}\n'
        f"Cover every changed file. Invent no paths.\n"
    )


__all__ = ["createPlanSessionPrompt", "createPlanSystemPrompt"]
