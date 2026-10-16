# Sentinel Evals

Dataset list in, production agent stages, stored evaluations out.

## Flow

`python main.py --data dataset/example.json --env local --model openai:gpt-5-mini`
runs, in order:

1. **load** — read a JSON file or directory of JSON files. Each file holds
   a list of `DatasetEntry` rows (`title`, `pr_url`, `description`,
   `comments[]` with `body` plus `severity`).
2. **resolve** — parse each `pr_url` (`owner`, `repo`, `prNumber`) and fetch
   live PR facts from the GitHub API (`baseSha`, `headSha`, branches,
   author, clone URL). Public PRs need no token.
3. **review** — `runReviewAgent` per entry: the production agent stages
   called directly (clone, codegraph index, diff, split, chunks,
   planner, file batch, extract, summary, combine). No durable
   execution, no DB rows, no GitHub post.
4. **judge** — `runJudgeAgent` per review: golden comments plus generated
   comments in, `JudgeResult` out (`confidence` 0-1, `matchedCount` out of
   `totalGoldenCount`, `falsePositiveCount`, match details). Substance
   match wins over wording.
5. **metrics** — `scoreSingleResult` per PR plus `createDatasetMetrics`
   over the full list. Prints per-PR lines plus a dataset summary.
6. **store** — writes `results/{modelId}/evaluations.json` (`createdAt`,
   `datasetPath`, `env`, `datasetMetrics`, per-PR `evaluations[]` with
   score, judge verdict, generated vs golden comments, resolved SHAs).
   `{modelId}` is the part after `:` in `--model` (`openai:gpt-5-mini`
   becomes `gpt-5-mini`).

## Parts

- `datasetLoader/types.py` — `DatasetEntry` plus `GoldenComment` (body plus
  severity only), `PrUrlParts`, `PrContext`, error values.
- `datasetLoader/loader.py` — `loadDatasetEntries(...)`: file or directory
  of JSON lists into `LoadedDataset`.
- `datasetLoader/prResolver.py` — `parsePrUrlParts(...)` plus
  `resolvePrUrl(...)` (GitHub API fetch, token optional).
- `agents/review.py` — `runReviewAgent(...)`: functional port of the
  durable agent phase. Takes `SandboxCtx` plus `LLMCtx` plus `RepoSnapshot`
  plus `ReviewWorkflowInput` plus `ReviewLimits`. Absent installation id
  means a public clone.
- `agents/judge.py` — `runJudgeAgent(...)`: structured LLM verdict.
- `agents/base.py` — shared `ReviewOutput` / `AgentRunError`.
- `environments/` — `LocalBackend` / `DockerBackend` (`BaseSandbox`
  children: only `execute`, `upload`, `download`, `id` are bespoke).
  The local backend mounts its temp dir at `/home/user`, which the
  production workers hardcode.
- `providers/` — `LocalProvider` / `DockerProvider` adapt the backends
  to the production provider contract; `registerEvalProviders()` puts
  them in the production provider map at eval runtime.
- `metrics/` — pure `scoreSingleResult` plus dataset-level
  `createDatasetMetrics`.
- `runner.py` — `runEval(...)` wires the parts, prints results, stores
  `results/{modelId}/evaluations.json` via `resultStore/` (`Path`-based).
- `resultStore/` — `EvaluationsFile` plus `PrEvaluation` types,
  `buildModelDirName` plus `buildEvaluationsFilePath` plus
  `saveEvaluationsFile` (`pathlib.Path` only, errors as values).

## Dataset shape

```json
[
  {
    "title": "Add endpoints",
    "pr_url": "https://github.com/owner/repo/pull/123",
    "description": "PR body from the dataset",
    "comments": [
      {"body": "Pagination skips the first page", "severity": "P1_CRITICAL"}
    ]
  }
]
```

## Run

Host (local env needs git + python3 only):

    cd packages/evals
    uv sync --all-packages
    uv run python main.py --data dataset/example.json --env local --model openai:gpt-5-mini

Docker env (isolated Linux; needs the docker CLI):

    uv run python main.py --data dataset/example.json --env docker --model openai:gpt-5-mini

E2B env (cloud; key via `--api-key`):

    uv run python main.py --data dataset/example.json --env e2b --model openai:gpt-5-mini --api-key ...

Flags: `--model provider:model`, `--base-url`, `--api-key`,
`--github-token` (or `GITHUB_TOKEN` env), `--results-dir` (default
`results`). Clones run without auth
(repos are assumed public); a present installation id mints a token
as in production.
