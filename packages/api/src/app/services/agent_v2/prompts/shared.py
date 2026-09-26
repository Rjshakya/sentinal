"""Shared prompt blocks for the v2 agents (planning + per-file review).

Pure formatting — no I/O, no LLM. Everything here is a value or a
small builder the lane modules (:mod:`.planning`,
:mod:`.file_review`) compose into full prompts:

- :data:`COMMENT_BODY_FORMAT` — the comment-body contract (bold
  headline → grounded issue bullets → ``**Fix:**`` line), owned by
  this package: the file-review findings format must match what the
  shared comments extractor enforces.
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

SEARCH_CODEGRAPH_TOOL_DESCRIPTION: str = """\
Explore the indexed code graph of this PR's repo (mirrors the
checked-out head tree: files, classes, functions, methods,
interfaces, types, imports, plus contains/imports/calls edges).

Call this FIRST before opening files: map the major systems, trace
callers/callees of changed symbols (blast radius), and find shared
contracts (auth, config, persistence) touching the PR.

One verb per call:
- files: every indexed file (file ids are plain repo-relative paths).
- search: substring-match a def-name fragment -> rows with node ids.
  Start here when you know a symbol but not its id.
- node: one node's full row, by id (or exact name + optional file).
- callees: what the node calls, in implementation order with
  call-site lines.
- callers: what calls the node (incoming) - the blast-radius verb.
- children: members contained in the node (class methods, file defs).
- imports: one file's imports with target modules.
- overview: index counts by kind/language.

Every call returns JSON {root, verb, count, truncated, items[]} with
stable node ids - feed ids back into node/callees/callers/children.
If truncated is true, narrow with name/file/limit. On graph
unavailability an error string is returned (never a failure) - say so
and continue with grep/reads.
"""


def getReviewDiffDirPath(workDir: str, prNumber: int, headSha: str) -> str:
    """Return the in-sandbox directory holding the PR diff artefacts.

    Layout: ``{workDir}/tmp/{pr_number}/{head_sha}/`` — ``file.diff``
    (the raw unified diff), ``overview.md``, and ``splitted_diffs/``
    (the per-file annotated chunks written by the split step). The
    single definition both the prompt builders and the pipeline steps
    use, so the path can never drift apart.
    """
    return workDir + f"/tmp/{prNumber}/{headSha}"


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
    "getReviewDiffDirPath",
    "identityHeader",
    "prMetaBlock",
]
