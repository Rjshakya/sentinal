"""Pure v2 combine helpers: trivial filter, context join, merge.

No I/O, no DBOS, no logging, no raising — every function returns a
value. The DBOS workflow calls them between durable steps:

- :func:`isTrivialFile` — host-side mechanical-file filter. Replaces
  the planner as the skip authority: lockfiles, minified assets,
  snapshots, and build/vendor output are never worth an agent run,
  and the rule is transparent and unit-testable (no LLM judgment).
- :func:`buildFileReviewJobs` — the **context join** (not a
  reconciliation gate): the :class:`ChunkInventory` (diff truth)
  drives the fan-out; the :class:`PlannerContext` (enrichment) only
  attaches context. A planner miss costs context, never a review —
  the file is still reviewed with an empty slice. Unknown planner
  entries (typos / hallucinations) are reported back for logging and
  ignored.
- :func:`concatFileReports` — merge the successful per-file raw
  reports into one extractor input, skipping empty / ``NO_FINDINGS``
  texts.
- :func:`chunkedJobs` — split the job list into batches of
  :data:`V2_FANOUT_BATCH_SIZE` for the workflow's sequential-batch
  fan-out.
- :func:`coerceFileLaneError` — fold a batch-gather failure into a
  :class:`FileLaneError` for the workflow's failure accounting.
- :func:`combineV2Reports` — build the merged :class:`ReviewResult`
  (via the shared verdict/combine rules) plus the per-run usage
  envelope from the planner + file research + summary usages.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from langchain_core.messages import UsageMetadata
from pydantic import BaseModel, ConfigDict

from app.services.agent_v2.prompts import NO_FINDINGS_MARKER
from app.services.agent_v2.types import (
    ChunkInventory,
    FileReviewJob,
    PlannerContext,
)
from app.utils.branded import CommitId, PRNumber, RepoId, UserId
from app.utils.schema import (
    CodeCommentDraft,
    ReviewComments,
    ReviewResult,
    ReviewVerdictStr,
)
from app.workflows.review_v2.types import (
    InputTokenDetails,
    TotalUsages,
    TotalUsagesPerPR,
)
from app.workflows.review_v2.errors import FileLaneError, ReviewStepError

V2_FANOUT_BATCH_SIZE = 25
"""Max per-file agents started concurrently (one ``asyncio.gather`` batch).

Bounds concurrent sandbox reconnects and keeps traces readable; the
client-side LLM rate limiter still queues model calls inside each
agent, so batching caps connections, not LLM throughput.
"""

_MAX_CONTEXT_CHARS = 800
"""Cap on ``crossFileContext`` characters attached to one job.

Keeps token cost linear in files. The planner should already write
tight context; the join truncates defensively (no prompt change
needed when the real planner prompt lands).
"""

_TRIVIAL_SUFFIXES: tuple[str, ...] = (
    ".min.js",
    ".min.css",
    ".map",
    ".snap",
    ".lock",
)
"""Filename suffixes that are never worth an agent run."""

_TRIVIAL_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "Cargo.lock",
        "poetry.lock",
        "Pipfile.lock",
        "Gemfile.lock",
        "composer.lock",
    }
)
"""Exact basenames that are never worth an agent run."""

_TRIVIAL_DIR_PREFIXES: tuple[str, ...] = (
    "dist/",
    "build/",
    "vendor/",
    "generated/",
    "__snapshots__/",
    "node_modules/",
)
"""Directory prefixes (repo-relative, posix) excluded from review."""


def isTrivialFile(path: str) -> bool:
    """Return ``True`` iff ``path`` is mechanical output, not reviewable code.

    Pure path match — no I/O. Case-sensitive (paths are matched
    exactly as they appear in the chunk inventory).
    """
    normalized = path.strip().replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    if basename in _TRIVIAL_EXACT_NAMES:
        return True
    if normalized.startswith(_TRIVIAL_DIR_PREFIXES):
        return True
    return normalized.endswith(_TRIVIAL_SUFFIXES)


class BuiltJobs(BaseModel):
    """Outcome of :func:`buildFileReviewJobs`."""

    model_config = ConfigDict(frozen=True)

    jobs: list[FileReviewJob]
    """One job per non-trivial inventory file, sorted by path."""

    ignoredPlannerFiles: list[str]
    """Planner entries with no matching inventory file (typos /
    hallucinations) — ignored, reported for logging."""

    skippedUnpairedFiles: list[str]
    """Inventory files with no observed chunk file — skipped, reported
    for logging. Impossible when the inventory comes from the
    list-chunks step (it always pairs them); a non-empty list means a
    hand-built inventory or a parser regression."""


def buildFileReviewJobs(
    *,
    inventory: ChunkInventory,
    plannerContext: PlannerContext,
) -> BuiltJobs:
    """Join the chunk inventory (truth) with the planner context (enrichment).

    Deterministic: jobs are sorted by path; planner lookup is by exact
    file match. Trivial files are dropped. Every job carries both the
    real code path (``filePath``) and its observed on-disk chunk file
    (``diffPath``) — the chunk name is looked up, never recomputed.
    Inventory files the planner never mentioned still get a job (empty
    context slice, ``hasPlannerContext=False``). Planner entries without
    an inventory file land in ``ignoredPlannerFiles``.
    """
    byFile = {entry.file: entry for entry in plannerContext.fileContexts}
    chunkByFile = {ref.filePath: ref.diffPath for ref in inventory.chunks}
    inventoryFiles = set(inventory.actualFiles)

    jobs: list[FileReviewJob] = []
    unpaired: list[str] = []
    for path in sorted(inventoryFiles):
        if isTrivialFile(path):
            continue
        diffPath = chunkByFile.get(path)
        if diffPath is None:
            # No observed chunk file for this path (older inventory
            # shape) — skip rather than guess a file name. The
            # list-chunks step always pairs them; this branch is
            # defence-in-depth, not a fallback mapping.
            unpaired.append(path)
            continue
        entry = byFile.get(path)

        if entry is None:
            jobs.append(FileReviewJob(filePath=path, diffPath=diffPath))
            continue
        jobs.append(
            FileReviewJob(
                filePath=path,
                diffPath=diffPath,
                focus=list(entry.focus),
                crossFileContext=entry.crossFileContext[:_MAX_CONTEXT_CHARS],
                relevantSymbols=list(entry.relevantSymbols),
                hasPlannerContext=True,
            )
        )

    ignored = sorted(
        path
        for path in byFile
        if path not in inventoryFiles and not isTrivialFile(path)
    )
    return BuiltJobs(
        jobs=jobs,
        ignoredPlannerFiles=ignored,
        skippedUnpairedFiles=sorted(unpaired),
    )


def concatFileReports(reportsByFile: Mapping[str, str]) -> str:
    """Merge per-file raw reports into one extractor input.

    Skips blank texts and bare ``NO_FINDINGS`` markers. Each surviving
    report is headed by a ``--- FILE: <path> ---`` separator so the
    extractor can attribute anchors. Deterministic file order.
    """
    parts: list[str] = []
    for path in sorted(reportsByFile):
        text = (reportsByFile[path] or "").strip()
        if not text or text == NO_FINDINGS_MARKER:
            continue
        parts.append(f"--- FILE: {path} ---\n\n{text}")
    return "\n\n".join(parts)


def chunkedJobs(
    jobs: Sequence[FileReviewJob],
    *,
    batchSize: int = V2_FANOUT_BATCH_SIZE,
) -> list[list[FileReviewJob]]:
    """Split ``jobs`` into consecutive batches of at most ``batchSize``.

    Pure; preserves order so the workflow's gather order stays
    deterministic.
    """
    return [list(jobs[i : i + batchSize]) for i in range(0, len(jobs), batchSize)]


def coerceFileLaneError(failure: BaseException, file: str) -> FileLaneError:
    """Coerce a file-lane failure into a :class:`FileLaneError`.

    Unwraps the raised step failures (:attr:`ReviewStepFailure.error`)
    and folds any unrecognised exception into a fresh lane error.
    Public so the workflow body can record per-batch failures the
    gather surface returns.
    """
    err = getattr(failure, "error", None)
    if isinstance(err, FileLaneError):
        return err
    if isinstance(err, ReviewStepError):
        return FileLaneError(
            message=err.message,
            file=file,
            userId=err.userId,
            repoId=err.repoId,
            prNumber=err.prNumber,
            headSha=err.headSha,
            retryable=err.retryable,
        )
    return FileLaneError(message=str(failure), file=file)


class CombinedReview(BaseModel):
    """The merged review payload plus the per-run usage envelope."""

    review: ReviewResult
    usages: TotalUsagesPerPR


_SEVERITY_RANK: dict[str, int] = {
    "P1_CRITICAL": 0,
    "P2_WARNING": 1,
    "P3_NITPICK": 2,
}


def verdictFor(comments: Sequence[CodeCommentDraft]) -> ReviewVerdictStr:
    """Return the review verdict implied by ``comments``.

    Pure rule:

    - any ``P1_CRITICAL`` → ``REQUEST_CHANGES``
    - else any ``P2_WARNING`` / ``P3_NITPICK`` → ``COMMENT``
    - else → ``APPROVE``
    """
    for draft in comments:
        if draft.severity == "P1_CRITICAL":
            return "REQUEST_CHANGES"
    for draft in comments:
        if draft.severity in ("P2_WARNING", "P3_NITPICK"):
            return "COMMENT"
    return "APPROVE"


def combineReviewResults(
    *,
    summaryMarkdown: str,
    comments: ReviewComments,
) -> ReviewResult:
    """Merge the agent outputs into one :class:`ReviewResult`.

    Comments are sorted in severity order (P1 → P2 → P3) so the
    GitHub review renders with the most important findings first. The
    summary is the synthesizer's markdown verbatim. The verdict is
    computed from the merged comments by :func:`verdictFor`.

    No dedup: each file agent is asked not to repeat itself, and the
    extractor already drops anchor-less findings.
    """
    return ReviewResult(
        comments=sorted(
            comments.List,
            key=lambda draft: _SEVERITY_RANK.get(draft.severity, len(_SEVERITY_RANK)),
        ),
        summary=summaryMarkdown,
        verdict=verdictFor(comments.List),
    )


def combineV2Reports(
    *,
    comments: ReviewComments,
    summaryMarkdown: str = "",
    researchUsages: Mapping[str, dict[str, UsageMetadata]],
    plannerUsage: Mapping[str, UsageMetadata] | None,
    summaryUsage: Mapping[str, UsageMetadata] | None = None,
    prNumber: PRNumber,
    headSha: CommitId,
    repoId: RepoId,
    userId: UserId,
) -> CombinedReview:
    """Build the run's merged review plus the per-run usage envelope.

    ``comments`` is the extractor output over the concatenated file
    reports (or an empty list when every file reported ``NO_FINDINGS``).
    ``summaryMarkdown`` is the synthesizer's walkthrough (``""`` when
    synthesis degraded — the review still completes). Token usage
    aggregates the planner's research usage, every successful file
    lane's research usage, and the summary synthesis usage; extractor
    calls' own tokens are not counted (same convention as the v1
    pipeline).
    """
    totalUsagesPerPr = TotalUsagesPerPR(
        pr_number=prNumber,
        head_sha=headSha,
        repo_id=repoId,
        user_id=userId,
        usages={},
    )

    if plannerUsage:
        _accumulateV2Usage(totalUsagesPerPr["usages"], dict(plannerUsage))
    for path in sorted(researchUsages):
        _accumulateV2Usage(totalUsagesPerPr["usages"], researchUsages[path])
    if summaryUsage:
        _accumulateV2Usage(totalUsagesPerPr["usages"], dict(summaryUsage))

    return CombinedReview(
        review=combineReviewResults(
            summaryMarkdown=summaryMarkdown,
            comments=comments,
        ),
        usages=totalUsagesPerPr,
    )


def _accumulateV2Usage(
    buckets: dict[str, TotalUsages],
    usage: dict[str, UsageMetadata],
) -> None:
    """Accumulate one lane's per-model usage into the run's buckets.

    ``buckets`` is the ``usages`` map of a :class:`TotalUsagesPerPR`
    envelope; each model gets a :class:`TotalUsages` counter with the
    input / output / total token counts and the cache details merged.
    Mirrors the v1 accumulator (kept local so v2 never imports v1
    privates).
    """
    for modelName, perModel in usage.items():
        bucket = buckets.setdefault(
            modelName,
            TotalUsages(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                input_token_details=InputTokenDetails(
                    cache_read=0,
                    cache_creation=0,
                ),
            ),
        )
        bucket["input_tokens"] += perModel.get("input_tokens", 0)
        bucket["output_tokens"] += perModel.get("output_tokens", 0)
        bucket["total_tokens"] += perModel.get("total_tokens", 0)
        details = perModel.get("input_token_details") or {}
        prevCacheRead = bucket["input_token_details"].get("cache_read")
        prevCacheCreation = bucket["input_token_details"].get("cache_creation")
        bucket["input_token_details"]["cache_read"] = (
            prevCacheRead if prevCacheRead is not None else 0
        ) + (details.get("cache_read") or 0)
        bucket["input_token_details"]["cache_creation"] = (
            prevCacheCreation if prevCacheCreation is not None else 0
        ) + (details.get("cache_creation") or 0)


__all__ = [
    "BuiltJobs",
    "CombinedReview",
    "V2_FANOUT_BATCH_SIZE",
    "buildFileReviewJobs",
    "chunkedJobs",
    "coerceFileLaneError",
    "combineReviewResults",
    "combineV2Reports",
    "concatFileReports",
    "isTrivialFile",
    "verdictFor",
]
