# Sentinel Evals

Dataset in, production agent stages, one report out.

## Flow

`python main.py --data dataset --env local --model openai:gpt-5-mini`
runs, in order:

1. **load** — read every `dataset/<case>/{input,output}.json` pair.
   `inputs[i]` maps to `outputs[i]`.
2. **review** — `runReviewAgent` per input: the production agent stages
   called directly (clone, codegraph index, diff, split, chunks,
   planner, file batch, extract, summary, combine). No durable
   execution, no DB rows, no GitHub post.
3. **judge** — `runJudgeAgent` per review against the gold bugs.
4. **metrics** — `scoreOne` per pair plus `createMetrics` over the full
   item list. Writes `report/report.json` plus `report/results/<case>.json`.

## Parts

- `agents/review.py` — `runReviewAgent(...)`: functional port of the
  durable agent phase. Takes `SandboxCtx` + `LLMCtx` + `RepoSnapshot`
  + `ReviewWorkflowInput` + `ReviewLimits`. Absent installation id
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
- `datasets/` — `PrInput` (PR facts only) plus `GoldOutput`, paired by
  index. Sandbox, model, and clone token come from the run config.
- `metrics/` — pure `scoreOne` plus dataset-level `createMetrics`.
- `runner.py` — `runEval(cfg)` wires the four parts.

## Datasets

```
dataset/<case>/
├── input.json     # repo_url, owner, name, pr_number,
│                  # base_sha, head_sha, branches, title/author/body
└── output.json    # gold verdict + bugs[] (id, bug, location, severity)
```

## Run

Host (local env needs git + python3 only):

    cd packages/evals
    uv sync --all-packages
    uv run python main.py --data dataset --env local --model openai:gpt-5-mini

Docker env (isolated Linux; needs the docker CLI):

    uv run python main.py --data dataset --env docker --model openai:gpt-5-mini

E2B env (cloud; key via `--api-key`):

    uv run python main.py --data dataset --env e2b --model openai:gpt-5-mini --api-key ...

Flags: `--model provider:model`, `--base-url`, `--api-key`,
`--out report`. Clones run without auth (repos are assumed public);
a present installation id mints a token as in production.
