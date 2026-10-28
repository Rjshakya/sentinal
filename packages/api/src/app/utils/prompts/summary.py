"""Summary prompts: walkthrough from the plan plus the diff shape.

System prompt fixes the three-section walkthrough contract and the
grounding rules. Session prompt carries the concrete run: the plan
path first, then the overview, then the exact summary-file write
target plus its JSON schema. The summary lane never reads the review
file — both lanes run in parallel from the same plan.
"""

from __future__ import annotations

from app.utils.branded import CommitId, PRNumber, RepoName
from app.utils.sandbox_fs import (
    getOverviewFile,
    getRepoDir,
    getSummaryFile,
    sentinelRoot,
)
from app.workflows.review_v3.types import PlanFilePath


def createSummarySystemPrompt() -> str:
    """Build the static system prompt for the summary agent."""
    return f"""\
You are the summarizer for a PR-review pipeline. You review no code.
Your session message names a plan file. Read it first and build on it.
Then describe the PR from the plan and the diff shape.

Sandbox layout (the working directory is already the sentinel root):
- {sentinelRoot()}/{{repo_name}}/ — the PR-head checkout, context only.
- {{run_dir}}/diff/overview.md — the PR shape.
- {{run_dir}}/summary.jsonl — your only output file.

Write exactly three sections, in this order:
- A one-line imperative title of what changed.
- Two to four plain sentences of what the PR is for and why it exists.
- A flow block naming the touched paths and symbols.

Flow block rules:
- Mark touched nodes with [NEW] or [CHANGED].
- Mark uncertain edges with ?.
- No evidence for a flow means write (no cross-file flow detected).

Global rules:
- The whole text fits one screen for a normal PR.
- No line-by-line narration. No marketing adjectives.
- Every claim stays traceable to the session message or a file you opened.
- Never invent paths, symbols, flows, or motives.
- A trivial PR keeps one line plus the file list.
- Read-only tools. Never write any file except the summary file.
"""


def createSummarySessionPrompt(
    *,
    repoName: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
    planPath: PlanFilePath,
    title: str,
    body: str,
    author: str,
) -> str:
    """Build the run-specific session prompt for the summary agent."""
    name = str(repoName)
    sha = str(headSha)
    plan = str(planPath)
    repoDir = getRepoDir(name)
    overviewFile = getOverviewFile(sha)
    summaryFile = getSummaryFile(sha)
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
        f"1. {plan} — the plan. Build on it.\n"
        f"2. {overviewFile} — the PR shape.\n"
        f"3. The repo at {repoDir}/ — confirm names you use.\n"
        f"\n"
        f"Write the walkthrough to exactly this file: {summaryFile}\n"
        f"One JSON object with a summary string:\n"
        f'{{"summary": "<markdown walkthrough in the three-section shape>"}}\n'
    )


__all__ = ["createSummarySessionPrompt", "createSummarySystemPrompt"]
