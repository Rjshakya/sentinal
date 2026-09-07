"""Sequential eval runner: review (HTTP) → judge → report.

Usage: ``python main.py <pr-id>``

The whole flow, in order:

1. **review** — POST ``input.json`` to the production ``POST /api/review``
   route (gated by ``X-Eval-Token``); consume the typed
   :class:`EvalReviewResponse` and adapt it onto
   :class:`ReviewOutput`; render ``results/<pr-id>/result.md``.
2. **judge** — an isolated structured-output LLM judge scores the
   review against the gold bugs from ``output.json``; writes
   ``report/<pr-id>/report.json`` with per-comment verdicts and derived
   precision / recall / F1 / FP rate.

The runner is a thin HTTP client — it does not run the production
review agents locally. The agents live in the API process; this
process only marshals the request and renders the artefacts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

load_dotenv()

import httpx
import agents.judge.agent as judge_agent
from agents.judge.llm import model_name
from agents.judge.type import GoldOutput, JudgeInput, JudgeReport, compute_metrics
from agents.review.type import ReviewInput, ReviewOutput, render_markdown
from type import EvalReviewResponse

ROOT = Path(__file__).resolve().parent


class EvalAPIError(RuntimeError):
    """``POST /api/review`` returned a non-2xx status.

    The API surfaces typed errors on workflow failure via a 500 with
    ``{workflow_id, error, message}`` — we re-raise that as
    :class:`EvalAPIError` so the runner's generic exception handler
    prints ``error: EvalAPIError: ...`` with the structured detail.
    """

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"eval API returned {status_code}: {json.dumps(detail, default=str)}"
        )


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON in {path}: {exc}") from exc


def _write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stem, suffix = path.stem, path.suffix
        i = 1
        while path.with_name(f"{stem}-{i}{suffix}").exists():
            i += 1
        path = path.with_name(f"{stem}-{i}{suffix}")
    path.write_text(text, encoding="utf-8")
    return path


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is required (set it in the eval process environment)"
        )
    return value


async def _call_review_api(
    *,
    api_url: str,
    api_token: str,
    body: dict[str, Any],
) -> EvalReviewResponse:
    """POST the dataset ``input.json`` to ``POST /api/review`` and
    return the parsed JSON body.

    The eval uses a synchronous ``await handle.get_result()`` style on
    the server side, so the HTTP timeout must outlast the slowest
    workflow run. ``EVAL_REVIEW_TIMEOUT_S`` (seconds, default 1800)
    overrides the default for tight CI loops.
    """

    timeout_s = float(os.environ.get("EVAL_REVIEW_TIMEOUT_S", "5400"))
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            f"{api_url}/review",
            json=body,
            headers={"X-Eval-Token": api_token},
        )

    if response.status_code >= 400:

        try:
            detail = response.json()
        except json.JSONDecodeError:
            detail = response.text

        raise EvalAPIError(response.status_code, detail)

    parsed: EvalReviewResponse = EvalReviewResponse.model_validate(response.json())
    return parsed


async def run_pr(pr_id: str) -> tuple[Path, Path]:
    dataset_dir = ROOT / "dataset" / pr_id
    input_raw = _read_json(dataset_dir / "input.json")
    review_input = ReviewInput.model_validate(input_raw)
    gold = GoldOutput.model_validate(_read_json(dataset_dir / "output.json"))

    api_url = _require_env("EVAL_API_URL")
    api_token = _require_env("EVAL_API_TOKEN")

    review_input.github_installation_id = int(_require_env("GITHUB_INSTALLATION_ID"))
    request_body = review_input.model_dump(mode="json")
    api_response = await _call_review_api(
        api_url=api_url, api_token=api_token, body=request_body
    )

    output = api_response
    result_md = render_markdown(output)
    result_md_path = _write_text(ROOT / "results" / pr_id / "result.md", result_md)

    verdict = await judge_agent.run(JudgeInput(gold=gold, result_md=result_md))

    precision, recall, f1, fp_rate = compute_metrics(verdict, gold)
    report = JudgeReport(
        judge_model=model_name(),
        verdict=verdict,
        precision=precision,
        recall=recall,
        f1=f1,
        fp_rate=fp_rate,
    )

    report_json_path = _write_text(
        ROOT / "report" / pr_id / "report.json",
        report.model_dump_json(indent=2),
    )

    return result_md_path, report_json_path


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Sentinel review-agent eval runner (review → judge)",
    )
    parser.add_argument("pr_id", help="dataset dir name, e.g. code-review-test-pr-2")
    args = parser.parse_args()

    try:
        result_md, report_json = asyncio.run(run_pr(args.pr_id))
    except Exception as exc:  # noqa: BLE001 — the runner fails loudly, nothing to retry
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {result_md} and {report_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
