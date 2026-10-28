"""Reviewer prompts: findings from the plan plus the diff.

System prompt fixes the reviewer role (one PR in depth), the
anchoring rule, severity discipline, comment shape, and the
false-positive gate. Session prompt carries the concrete run: the
plan path first, then the chunk inputs, then the exact review-file
write target plus its JSON schema.
"""

from __future__ import annotations

from app.utils.branded import CommitId, PRNumber, RepoName
from app.utils.sandbox_fs import (
    getOverviewFile,
    getRepoDir,
    getReviewFile,
    getSplittedDir,
    sentinelRoot,
)
from app.workflows.review_v3.types import PlanFilePath


def createReviewSystemPrompt() -> str:
    """Build the static system prompt for the review agent."""
    return f"""\
You are a senior software engineer reviewing one GitHub PR in depth.
Your session message names a plan file. Read it first and build on it.
Then review the diff chunks against the repo.

Sandbox layout (the working directory is already the sentinel root):
- {sentinelRoot()}/{{repo_name}}/ — the PR-head checkout, context only.
- {{run_dir}}/diff/overview.md — PR shape, optional context.
- {{run_dir}}/diff/splitted_diffs/ — the review chunks with LEFT/RIGHT
  gutter line numbers.
- {{run_dir}}/review.jsonl — your only output file.

Anchoring:
- Anchor every finding only to a gutter-visible line in a chunk file.
- from_line / to_line sit on the same side and copy its gutters.
- RIGHT marks the new side, LEFT marks deleted lines.
- Never invent an anchor. Drop a finding you cannot anchor.

Severity:
- P1_CRITICAL — security flaw or critical correctness bug.
- P2_WARNING — correctness bug you can trace to a wrong outcome.
- P3_NITPICK — rare maintainability note, never style taste.

Comment shape (under 10 lines):
- Bold headline naming the issue.
- Short bullets proving the bug with file:line evidence.
- One **Fix:** line with the concrete change.

False-positive gate:
- Trace input to code path to concrete wrong outcome.
- Verify every claim against the repo. Drop the rest.
- A clean file writes an empty comments array. That is a good answer.
- Read-only tools. Never write any file except the review file.
"""


def createReviewSessionPrompt(
    *,
    repoName: RepoName,
    prNumber: PRNumber,
    headSha: CommitId,
    planPath: PlanFilePath,
    title: str,
    body: str,
    author: str,
) -> str:
    """Build the run-specific session prompt for the review agent."""
    name = str(repoName)
    sha = str(headSha)
    plan = str(planPath)
    repoDir = getRepoDir(name)
    overviewFile = getOverviewFile(sha)
    splittedDir = getSplittedDir(sha)
    reviewFile = getReviewFile(sha)
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
        f"3. {splittedDir}/ — the chunks. Anchor from their gutters only.\n"
        f"4. The repo at {repoDir}/ — confirm each finding.\n"
        f"\n"
        f"Write the findings to exactly this file: {reviewFile}\n"
        f"One JSON object with a comments array:\n"
        f'{{"comments": [{{"file": "<repo-relative path>", '
        f'"fromLine": 42, "toLine": 44, "side": "RIGHT", '
        f'"severity": "P1_CRITICAL", "body": "<comment>"}}]}}\n'
        f"fromLine and toLine are integers of 1 or more. "
        f"side is RIGHT or LEFT. "
        f"severity is P1_CRITICAL, P2_WARNING, or P3_NITPICK. "
        f"A clean PR writes {{\"comments\": []}}.\n"
    )


__all__ = ["createReviewSessionPrompt", "createReviewSystemPrompt"]
