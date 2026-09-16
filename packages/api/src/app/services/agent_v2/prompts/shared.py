"""Shared prompt blocks for the v2 agents (planning + per-file review).

Pure formatting — no I/O, no LLM. Everything here is a value or a
small builder the lane modules (:mod:`.planning`,
:mod:`.file_review`) compose into full prompts:

- :data:`COMMENT_BODY_FORMAT` — the comment-body contract (bold
  headline → grounded issue bullets → ``**Fix:**`` line). This is a
  v2-owned **copy** of the v1 contract in
  :mod:`app.services.agent.prompts`: the file-review findings format
  must match what the shared comments extractor enforces, and the
  copy keeps ``agent_v2`` isolated from the v1 package. If the v1
  wording changes, update this copy in the same commit.
- :data:`NO_FINDINGS_MARKER` — the exact marker a file agent emits
  when its file is clean (the combine step treats it as a
  successful empty outcome).
- :func:`identityHeader` / :func:`prMetaBlock` — the shared
  run-identity and PR-intent blocks every user prompt starts with,
  so the lanes cannot drift apart.
"""

from __future__ import annotations

from app.utils.branded import CommitId, PRNumber, RepoId, UserId

COMMENT_BODY_FORMAT: str = """\
Comment body format (GitHub renders markdown):

1. **Headline** — one bold line naming the issue, e.g.
   `**Unquoted install token in git clone argv**`. Never start with "This
   line...", "I noticed...", or a file name.
2. **Issue** — 2-4 short bullets proving the bug or risk. Each bullet is
   grounded in a diff / filePath / repo line or symbol, using backticked
   `file:line` or symbol references. No prose paragraphs.
3. **Fix** — one short line starting with `**Fix:**` describing the
   concrete change.

Rules:
- Whole body under ~10 lines; one blank line between sections.
- No preamble ("This comment is about...", "I noticed that..."), no closing
  remarks ("Please fix this", "Let me know what you think").
- No evaluative adjectives ("bad", "dangerous", "nice", "clean").
- Never invent facts, features, or line numbers — every claim stays
  traceable to the diff, filePath, or the repo.
"""

NO_FINDINGS_MARKER: str = "NO_FINDINGS"
"""Exact marker a file agent emits when its file is clean.

The combine step treats it as a successful empty outcome (no
extractor call for that file's text beyond the shared merge).
"""


def identityHeader(
    *,
    repoName: str,
    repoId: RepoId,
    userId: UserId,
    prNumber: PRNumber,
    headSha: CommitId,
    diffDir: str,
    repoRoot: str,
) -> str:
    """Build the run-identity block every v2 user prompt starts with."""
    return (
        f"Repo: {repoName} (id={repoId})\n"
        f"User: {userId}\n"
        f"PR number: {prNumber}\n"
        f"Head SHA: {headSha}\n"
        f"Diff dir: {diffDir}/\n"
        f"Repo root: {repoRoot}\n"
    )


def prMetaBlock(*, title: str, body: str, author: str) -> str:
    """Build the PR-intent block: what the PR claims to do.

    The agents judge the code against this claim (a diff that
    silently does something else is itself a finding), so every user
    prompt carries it verbatim — never summarized, never omitted.
    """
    return (
        f"PR title: {title.strip() or '(untitled)'}\n"
        f"PR author: {author}\n"
        f"PR description:\n"
        f"{body.strip() or '(empty)'}\n"
    )


__all__ = [
    "COMMENT_BODY_FORMAT",
    "NO_FINDINGS_MARKER",
    "identityHeader",
    "prMetaBlock",
]
