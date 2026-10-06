"""Prompts for the v2 summary synthesizer: walkthrough + flow tree + files.

Two builders, both pure formatting (no I/O, no LLM):

- :func:`createSummarySystemPrompt` — the static walkthrough contract.
  Takes no arguments: the three-section shape (walkthrough info, ASCII
  data/control-flow tree, important file changes) plus the grounding
  and anti-hallucination rules. Static so the contract is identical
  for every run and unit-testable without fixtures.
- :func:`createSummaryUserPrompt` — the run-specific message built
  from narrow scalars + already-validated structures (inventory paths,
  :class:`PlannerContext`, extracted :class:`ReviewComments`). The diff
  itself is never inlined; findings arrive pre-capped and P1-first so
  token cost stays linear in files.

The synthesizer performs no sandbox reads — every claim it may emit
must already be present in its user message. Anything it cannot trace
to the input is omitted (the flow tree degrades to an explicit
placeholder, never an invented flow).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.agent_v2.prompts.shared import prMetaBlock
from app.services.agent_v2.types import PlannerContext
from app.utils.branded import CommitId, PRNumber, RepoName, UserId
from app.utils.schema import ReviewComments
from app.utils.util import repo_path

_MAX_PLANNER_CHARS = 800
"""Cap on planner free-text characters echoed per field.

Mirrors the join step's ``crossFileContext`` cap so token cost stays
linear. The planner should already write tight context; truncation is
defensive.
"""

_MAX_FINDINGS = 50
"""Cap on findings echoed into the synthesis prompt (P1 first)."""

_MAX_FILES = 100
"""Cap on inventory paths echoed into the synthesis prompt."""


def createSummarySystemPrompt() -> str:
    """Build the static system prompt for the summary synthesizer.

    Pure formatting — no inputs, no I/O, no LLM. The returned contract
    fixes the three-section output shape plus the grounding rules the
    structured-output call enforces through :class:`SummaryResult`.
    """
    return """\
You are the summarizer for a PR-review pipeline. You review no code yourself.
Your input is already-verified context: the PR's claimed intent, the changed-file
inventory, the planner's repoMap / dataFlows / sharedConcerns, and the extracted
findings (file | severity | anchor). The diff itself is not in your input.

Write exactly three sections, in this order — nothing else:

## <one-line imperative title: what changed>

<2-4 plain sentences: what this PR is for and why it probably exists,
from the PR title/description plus the planner dataFlows. Anyone unfamiliar
with the repo must understand it from these sentences alone. Plain language,
no jargon unless the PR itself uses it first. If the motive is genuinely
unclear, say "unclear from the diff alone" rather than inventing a backstory.>

### Flow

```text
<ascii tree of the PR's data/control + code flow, for example:
request → router.list_repos()
            └── service.fetch_repos() [CHANGED]
                  ├── db.query(users)
                  └── NEW: cache.get() → cache.set()>
```

Tree rules:
- Monospaced: `→` marks data flow, `└──` / `├──` mark call nesting.
- Suffix touched nodes with `[NEW]` / `[CHANGED]`; mark uncertain edges with `?`.
- Depth at most 4, at most 15 lines; use repo-relative paths plus `symbol()`
  names exactly as they appear in the input.
- Only flows traceable to the input (planner dataFlows / cross-file context /
  findings). No flow evidence → emit exactly `(no cross-file flow detected)`
  instead of the tree — never hallucinate a flow.

### Important changes

- `path/to/file.py` — one-line what plus why it matters (append the `P1` / `P2`
  marker when the file carries a finding of that severity)
- (rank: files with P1/P2 findings first, then shared contracts such as models,
  auth, API surface, or config, then the rest; skip pure renames, formatting-only,
  lockfiles, and generated files; collapse a mechanical-only remainder into one line)

Global rules:
- The whole summary fits one screen for a normal-sized PR.
- No line-by-line narration ("this line adds..."), no marketing adjectives
  ("elegant", "robust", "powerful").
- Never invent paths, symbols, flows, motivations, or findings — every claim
  stays traceable to the user message.
- If the PR is trivial (docs, formatting, a config bump), keep the walkthrough
  to one line plus the files list — do not stretch it.
- Final message is the markdown only: no JSON, no preamble, no closing remarks
  (the single ```text fence around the tree is the only fenced block).

## Writing Style:
    Write all text in ASD-STE100 Simplified Technical English.

    Rules:
    - One idea per sentence. Max 20 words for instructions, 25 for descriptions.
    - Use active voice and present tense.
    - Use simple verbs. Write "use", not "utilize". Write "start", not "initiate".
    - Use only approved words and one meaning per word. Do not use synonyms for the same thing.
    - Use the same term for the same object every time.
    - Write instructions as commands: "Remove the cover."
    - Start each step with a verb. Put one action in each step.
    - Use "Warning" and "Caution" before dangerous steps, not after.
    - Do not use idioms, slang, or phrasal verbs with unclear meaning.
    - Do not use contractions.
    - Keep articles ("the", "a"). Do not drop them.

    Before you reply, check each sentence against these rules. Rewrite any sentence that breaks one.

"""


def createSummaryUserPrompt(
    *,
    repoName: RepoName,
    userId: UserId,
    prNumber: PRNumber,
    headSha: CommitId,
    title: str,
    body: str,
    author: str,
    actualFiles: Sequence[str],
    skippedFiles: Sequence[str],
    plannerContext: PlannerContext,
    comments: ReviewComments,
) -> str:
    """Build the user message for the summary synthesizer.

    Pure formatting — no I/O, no LLM. Carries the PR intent verbatim,
    the host-side inventory (capped), the planner context (per-field
    truncated), and the extracted findings (P1 first, capped). Takes
    narrow scalars plus validated structures — never a live ctx — so
    the builder stays unit-testable and durable-safe.
    """
    header = (
        f"Repo: {repoName}\n"
        f"User: {userId}\n"
        f"PR number: {prNumber}\n"
        f"Head SHA: {headSha}\n"
        f"Repo root: {repo_path(str(repoName))}\n"
    )
    files_block = (
        "\n".join(f"- {path}" for path in list(actualFiles)[:_MAX_FILES]) or "- (none)"
    )
    skipped_block = ", ".join(skippedFiles) or "(none)"

    severity_rank = {"P1_CRITICAL": 0, "P2_WARNING": 1, "P3_NITPICK": 2}
    ordered = sorted(
        comments.List,
        key=lambda draft: severity_rank.get(draft.severity, len(severity_rank)),
    )
    finding_lines: list[str] = []
    for draft in ordered[:_MAX_FINDINGS]:
        headline = (draft.comment.splitlines() or [""])[0][:120]
        finding_lines.append(
            f"- {draft.file_name} | {draft.severity} "
            f"| L{draft.from_line}-{draft.to_line} | {headline}"
        )
    findings_block = "\n".join(finding_lines) or "- (no findings)"

    return (
        header
        + "\n"
        + prMetaBlock(title=title, body=body, author=author)
        + "\n"
        + f"Changed files with reviewable diffs ({len(list(actualFiles))}):\n"
        + f"{files_block}\n"
        + f"Skipped (no chunk): {skipped_block}\n"
        + "\n"
        + f"Planner repoMap:\n{(plannerContext.repoMap[:_MAX_PLANNER_CHARS] or '(none)')}\n"
        + "\n"
        + f"Planner dataFlows:\n{(plannerContext.dataFlows[:_MAX_PLANNER_CHARS] or '(none)')}\n"
        + "\n"
        + f"Planner sharedConcerns:\n"
        + f"{(plannerContext.sharedConcerns[:_MAX_PLANNER_CHARS] or '(none)')}\n"
        + "\n"
        + f"Findings (severity-ranked, top {_MAX_FINDINGS}):\n"
        + f"{findings_block}\n"
        + "\n"
        + "Write the three-section walkthrough from the contract: "
        + "walkthrough info, ASCII flow tree, important file changes.\n"
    )


__all__ = [
    "createSummarySystemPrompt",
    "createSummaryUserPrompt",
]
