"""Eval runner: dataset in, production agent stages, one report out.

``runEval`` loads the dataset, builds the production ctxs
(``SandboxCtx`` / ``LLMCtx`` / ``RepoSnapshot`` / ``ReviewWorkflowInput``)
from each ``inputs[i]`` plus ``RunConfig``, runs
:func:`runReviewAgent` (the production agent stages, called directly),
judges each review against ``outputs[i]``, and rolls the per-item
scores into a dataset report. The dataset carries PR facts only;
sandbox, model, and the clone token come from ``RunConfig``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import settings
from app.models.enums import PRStatus
from app.services.llm.types import LLMCtx
from app.services.sandbox.service import createSandboxCtx
from app.services.sandbox.types import SanboxProviderApiKey
from app.utils.branded import (
    ApiKey,
    BaseUrl,
    CommitId,
    PRNumber,
    RepoId,
    RepoName,
    RepoOwner,
    UserId,
)
from app.workflows.review_v2.types import (
    RepoSnapshot,
    ReviewLimits,
    ReviewWorkflowInput,
)
from pydantic import BaseModel, ConfigDict, Field

from agents.base import AgentRunError
from agents.judge import JUDGE_SYSTEM_PROMPT, runJudgeAgent
from agents.review import runReviewAgent
from datasets.loader import DatasetError, loadDataset
from datasets.types import PrInput
from environments.base import EnvKind
from metrics.scoring import (
    DatasetReport,
    ItemScore,
    createMetrics,
    failedItem,
    scoreOne,
)
from providers import registerEvalProviders

log = logging.getLogger(__name__)


class RunConfig(BaseModel):
    """Everything one ``runEval`` needs. Dataset holds PR facts only."""

    model_config = ConfigDict(frozen=True)

    dataset_path: str = Field(min_length=1)
    env: EnvKind = Field(default="local")
    model: str = Field(default="openai:gpt-5-mini", min_length=3)
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    judge_prompt: str = Field(default=JUDGE_SYSTEM_PROMPT, min_length=1)
    out_dir: str = Field(default="report", min_length=1)


class RunError(BaseModel):
    """Runner-level failure, returned as a value (never raised)."""

    model_config = ConfigDict(frozen=True)

    message: str
    phase: str = Field(default="")

    def __str__(self) -> str:
        return self.message


def _build_llm(cfg: RunConfig) -> LLMCtx | RunError:
    if ":" not in cfg.model:
        return RunError(
            message=f"model must be 'provider:model', got {cfg.model!r}",
            phase="config",
        )
    return LLMCtx(
        model=cfg.model,
        origin="system",
        apiKey=ApiKey(cfg.api_key) if cfg.api_key else None,
        baseUrl=BaseUrl(cfg.base_url) if cfg.base_url else None,
        defaultHeaders={},
        maxRetries=3,
        rateLimitRps=0.5,
    )


def _sandbox_api_key(cfg: RunConfig) -> str:
    if cfg.api_key:
        return cfg.api_key
    if cfg.env == "e2b":
        return settings.e2b_api_key
    return ""


def _workflow_input(pr: PrInput) -> ReviewWorkflowInput:
    return ReviewWorkflowInput(
        userId=UserId("eval-user"),
        ghRepoId=0,
        ghPrId=0,
        prNumber=PRNumber(pr.pr_number),
        baseBranch=pr.base_branch,
        defaultBranch=pr.base_branch,
        baseSha=pr.base_sha,
        headSha=CommitId(pr.head_sha),
        headBranch=pr.head_branch or "eval",
        author=pr.author,
        title=pr.title,
        body=pr.body,
        status=PRStatus.OPEN,
        trigger="eval",
        postToGithub=False,
        githubInstallationId=None,
        diffBaseSha=None,
    )


async def runEval(cfg: RunConfig) -> DatasetReport | RunError:
    """Run the full dataset and return the dataset-level report."""
    dataset = loadDataset(cfg.dataset_path)
    if isinstance(dataset, DatasetError):
        return RunError(message=str(dataset), phase="load")

    llm = _build_llm(cfg)
    if isinstance(llm, RunError):
        return llm

    registerEvalProviders()
    limits = ReviewLimits(modelCallRunLimit=120, toolCallRunLimit=120)

    items: list[ItemScore] = []
    reviews: list[dict[str, object]] = []
    for idx, pr in enumerate(dataset.inputs):
        case_id = dataset.ids[idx] if idx < len(dataset.ids) else f"case-{idx}"
        gold = dataset.outputs[idx]
        repo = RepoSnapshot(
            id=RepoId(f"eval-{pr.owner}-{pr.name}-{pr.pr_number}"),
            repoOwner=RepoOwner(pr.owner),
            repoName=RepoName(pr.name),
            defaultBranch=pr.base_branch,
        )
        try:
            sandbox_ctx = createSandboxCtx(
                userId=UserId("eval-user"),
                repoId=repo.id,
                repoName=pr.name,
                providerId=cfg.env,
                apiKey=SanboxProviderApiKey(_sandbox_api_key(cfg)),
                sandboxName=f"eval-{pr.name}-{pr.pr_number}",
                rootPath="/home/user",
            )
        except Exception as exc:
            items.append(failedItem(case_id, reason=f"sandbox ctx: {exc}"))
            continue
        workflow_input = _workflow_input(pr)
        review = await runReviewAgent(
            sandboxCtx=sandbox_ctx,
            llm=llm,
            repo=repo,
            input=workflow_input,
            limits=limits,
        )
        if isinstance(review, AgentRunError):
            log.warning("eval case failed: %s: %s", case_id, review.message)
            items.append(failedItem(case_id, reason=review.message))
            continue
        reviews.append({"case_id": case_id, **review.model_dump(mode="json")})
        verdict = await runJudgeAgent(
            review=review,
            gold=gold,
            llm=llm,
            systemPrompt=cfg.judge_prompt,
        )
        if isinstance(verdict, AgentRunError):
            log.warning("eval judge failed: %s: %s", case_id, verdict.message)
            items.append(failedItem(case_id, reason=verdict.message))
            continue
        items.append(scoreOne(verdict, gold, case_id=case_id))
    report = createMetrics(items)
    saved = _save_report(cfg.out_dir, report, reviews)
    if isinstance(saved, RunError):
        return saved
    log.info("eval complete: %s", report.summary())
    return report


def _save_report(
    out_dir: str, report: DatasetReport, reviews: list[dict[str, object]]
) -> None | RunError:
    try:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        results_dir = out / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        for entry in reviews:
            case_id = str(entry.get("case_id", "case"))
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in case_id)
            (results_dir / f"{safe}.json").write_text(
                json.dumps(entry, indent=2, default=str), encoding="utf-8"
            )
        return None
    except Exception as exc:
        return RunError(
            message=f"save failed: {type(exc).__name__}: {exc}", phase="save"
        )


__all__ = ["RunConfig", "RunError", "runEval"]
