"""Tests for the v2 plan reader workers.

Covers :func:`app.workflows.review_v2.steps.invoke_planner.readPlanText`
and :func:`app.workflows.review_v2.steps.invoke_planner.parsePlanText`
— the value-returning workers behind the ``getPlanStep`` DBOS edge
(mirroring ``test_list_chunk_files.py``, which tests ``listChunkFiles``
rather than its DBOS step).

Two tiers:

- Offline (no E2B key): ``parsePlanText`` vectors. Pure Pydantic
  validation, no sandbox involved. Runs in CI.
- Live (requires ``E2B_API_KEY``, skips without it): ``readPlanText``
  against one real sandbox built the production way —
  :func:`app.services.sandbox.service.createSandboxCtx` →
  :func:`app.services.sandbox.service.getProvider` → ``create()`` —
  seeded via the backend's own ``aupload_files``. No fakes, no DBOS.
  The sandbox is shared across the whole file (module-scoped fixture,
  one lifetime, killed once at teardown); tests stay isolated through
  unique per-test subdirs.

No multi-page test, deliberately: ``aread`` is *line*-paginated while
``submit_plan`` writes compact single-line JSON, so no realistic
``plan.json`` ever spans pages. The worker is accumulate-until-empty
and the large-plan test locks byte-for-byte accumulation of a multi-KB
submission — that is the accumulation coverage.

Run: cd packages/api && uv run pytest tests/review_v2/test_get_plan.py -v
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from deepagents.backends.sandbox import BaseSandbox

from app.core.config import settings
from app.models.enums import PRStatus
from app.services.agent_v2.service import planFilePath
from app.services.agent_v2.types import FileContext, PlannerContext
from app.services.sandbox.errors import SandboxProviderError
from app.services.sandbox.service import createSandboxCtx, getProvider
from app.services.sandbox.types import SandboxCtx
from app.utils.branded import (
    CommitId,
    PRNumber,
    RepoId,
    SanboxProviderApiKey,
    UserId,
)
from app.workflows.review.types import ReviewWorkflowInput
from app.workflows.review_v2.errors import PlannerStepError
from app.workflows.review_v2.steps.invoke_planner import (
    parsePlanText,
    readPlanText,
)


def _make_input(
    *,
    pr_number: int = 11,
    head_sha: str = "a" * 40,
) -> ReviewWorkflowInput:
    """Minimal valid workflow input carrying the run identity."""
    return ReviewWorkflowInput(
        userId=UserId("get-plan-user"),
        ghRepoId=1,
        ghPrId=2,
        prNumber=PRNumber(pr_number),
        baseBranch="main",
        defaultBranch="main",
        baseSha="b" * 40,
        headBranch="feat",
        headSha=CommitId(head_sha),
        author="alice",
        title="t",
        body="b",
        status=PRStatus.OPEN,
    )


def _make_repo_id() -> RepoId:
    return RepoId("get-plan-repo")


def _sample_plan(*, cross_file_context: str = "calls foo") -> PlannerContext:
    return PlannerContext(
        repoMap="web service",
        dataFlows="req -> handler",
        sharedConcerns="auth",
        fileContexts=[
            FileContext(
                file="src/app/a.py",
                focus=["correctness"],
                crossFileContext=cross_file_context,
                relevantSymbols=["def:handle"],
            )
        ],
    )


# --------------------------------------------------------------------------- #
# parsePlanText (pure, offline)                                                #
# --------------------------------------------------------------------------- #


def test_parse_plan_text_rejects_invalid_json() -> None:
    result = parsePlanText("{not json", input=_make_input(), repoId=_make_repo_id())

    assert isinstance(result, PlannerStepError)
    assert result.phase == "extract"
    assert result.retryable is False
    assert result.message.strip() != ""


def test_parse_plan_text_rejects_schema_invalid_json() -> None:
    result = parsePlanText(
        '{"fileContexts": [{"file": ""}]}',
        input=_make_input(),
        repoId=_make_repo_id(),
    )

    assert isinstance(result, PlannerStepError)
    assert result.phase == "extract"
    assert result.retryable is False


def test_parse_plan_error_carries_run_identity() -> None:
    input = _make_input(pr_number=42, head_sha="c" * 40)
    repo_id = _make_repo_id()

    result = parsePlanText("{bad", input=input, repoId=repo_id)

    assert isinstance(result, PlannerStepError)
    assert result.userId == input.userId
    assert result.repoId == repo_id
    assert result.prNumber == input.prNumber
    assert result.headSha == input.headSha


# --------------------------------------------------------------------------- #
# readPlanText against one shared real sandbox built from SandboxCtx           #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
async def live_plan_backend() -> AsyncGenerator[tuple[SandboxCtx, BaseSandbox], None]:
    """Create one real sandbox via the service layer; kill it at teardown."""
    if not settings.e2b_api_key:
        pytest.skip("E2B_API_KEY is not set; live sandbox test needs it")
    ctx = createSandboxCtx(
        userId=UserId("get-plan-user"),
        repoId=_make_repo_id(),
        repoName="get-plan-repo",
        providerId="e2b",
        apiKey=SanboxProviderApiKey(settings.e2b_api_key),
        sandboxName="get-plan-sandbox",
        rootPath="/home/user",
    )
    provider = getProvider(ctx.providerId)(ctx)
    backend = await provider.create()
    assert not isinstance(
        backend, SandboxProviderError
    ), f"sandbox create failed: {backend}"
    try:
        yield ctx, backend
    finally:
        try:
            await provider.kill()
        except Exception:
            pass  # teardown must never mask the test outcome


def _test_plan_path(ctx: SandboxCtx, name: str) -> str:
    """Unique per-test plan path under the shared sandbox working dir."""
    return f"{ctx.rootPath}/get-plan-{name}/plan.json"


async def _seed_plan(backend: BaseSandbox, plan_path: str, raw: str) -> None:
    """Upload ``plan.json`` bytes via the backend's own upload method."""
    uploads = await backend.aupload_files([(plan_path, raw.encode("utf-8"))])
    assert len(uploads) == 1
    failed = [(u.path, u.error) for u in uploads if u.error is not None]
    assert not failed, f"plan upload failed: {failed}"


async def test_read_plan_text_live_round_trip(
    live_plan_backend: tuple[SandboxCtx, BaseSandbox],
) -> None:
    ctx, backend = live_plan_backend
    # The canonical production path stays locked even though the other
    # tests use per-test subdirs for isolation.
    assert planFilePath(ctx.rootPath) == f"{ctx.rootPath}/plan.json"
    plan = _sample_plan()
    plan_path = _test_plan_path(ctx, "roundtrip")
    await _seed_plan(backend, plan_path, plan.model_dump_json())
    input = _make_input()

    text = await readPlanText(
        backend, planPath=plan_path, input=input, repoId=ctx.repoId
    )

    assert isinstance(text, str)
    assert parsePlanText(text, input=input, repoId=ctx.repoId) == plan


async def test_read_plan_text_live_large_plan_accumulates(
    live_plan_backend: tuple[SandboxCtx, BaseSandbox],
) -> None:
    # Compact JSON is a single line, so the line-paginated backend
    # returns even a multi-KB plan in one page — asserting byte-for-byte
    # equality here is the accumulation coverage (no paging asserts).
    ctx, backend = live_plan_backend
    plan = _sample_plan(cross_file_context="x" * 7000)
    plan_path = _test_plan_path(ctx, "large")
    await _seed_plan(backend, plan_path, plan.model_dump_json())
    input = _make_input()

    text = await readPlanText(
        backend, planPath=plan_path, input=input, repoId=ctx.repoId
    )

    assert isinstance(text, str)
    assert parsePlanText(text, input=input, repoId=ctx.repoId) == plan


async def test_read_plan_text_live_missing_file_is_final(
    live_plan_backend: tuple[SandboxCtx, BaseSandbox],
) -> None:
    ctx, backend = live_plan_backend
    input = _make_input()

    result = await readPlanText(
        backend,
        planPath=_test_plan_path(ctx, "missing"),
        input=input,
        repoId=ctx.repoId,
    )

    assert isinstance(result, PlannerStepError)
    assert result.phase == "research"
    assert result.retryable is False
    assert "never submitted" in result.message
    assert result.userId == input.userId
    assert result.repoId == ctx.repoId
    assert result.prNumber == input.prNumber
    assert result.headSha == input.headSha


async def test_read_plan_text_live_invalid_json_is_extract(
    live_plan_backend: tuple[SandboxCtx, BaseSandbox],
) -> None:
    ctx, backend = live_plan_backend
    plan_path = _test_plan_path(ctx, "invalid")
    await _seed_plan(backend, plan_path, "{not json")
    input = _make_input()

    text = await readPlanText(
        backend, planPath=plan_path, input=input, repoId=ctx.repoId
    )

    assert isinstance(text, str)
    result = parsePlanText(text, input=input, repoId=ctx.repoId)
    assert isinstance(result, PlannerStepError)
    assert result.phase == "extract"
    assert result.retryable is False
