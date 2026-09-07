# Sentinel Evals

Two-stage harness that evaluates the production review agents (see
AGENTS.md §3.8) against authored PR datasets.

## Flow

`python main.py <pr-id>` runs, sequentially:

1. **review** — POST the dataset `input.json` to
   `POST /api/review` on the production API (gated by the
   `X-Eval-Token` header). The API runs the full production
   `reviewWorkflow` — sandbox create, clone, diff split, the two
   research-agent lanes, the extractor steps, persistence — and
   returns the typed review output synchronously. The eval runner
   adapts the response onto a `ReviewOutput` and renders
   `results/<pr-id>/result.md`.
2. **judge** — an isolated structured-output LLM judge scores the
   review against the gold bugs in `output.json`. Writes
   `report/<pr-id>/report.json` with per-comment verdicts and
   derived precision / recall / F1 / FP rate.

The eval no longer runs the production agents in-process — it drives
the same pipeline the production webhook does, end-to-end, so the
results reflect the real review behaviour (DBOS steps, sandbox
lifecycle, partial-failure degradation, etc.).

## Datasets

```
dataset/<pr-id>/
├── input.json     # user_id, github_repo_id, github_installation_id,
│                  # repo_url, repo_owner, repo_name, pr_number,
│                  # base_sha, head_sha
└── output.json    # gold verdict + bugs[] (id, bug, location, severity)
```

`<pr-id>` is `{repo}-pr-{n}` (e.g. `code-review-test-pr-2`) — unique
per PR, so runs and artefacts stay idempotent. Severities are the
prod enum: `P1_CRITICAL` / `P2_WARNING` / `P3_NITPICK`. `location`
is `path/to/file:line` or `path/to/file:from-to`.

## result.md

The review output is a fixed template (verdict / summary / comments
with severity + anchors). The judge parses it deterministically —
never edit a result.md by hand.

## Run

The eval needs:

- A reachable production API (`EVAL_API_URL`) with the review
  pipeline configured (LLM + sandbox + GitHub App).
- A matching `EVAL_API_TOKEN` (the API rejects with 401 on mismatch).
- The GitHub App installed on the test repo (the workflow uses the
  installation token to clone).

Host:

    export EVAL_API_URL=http://localhost:8000/api
    export EVAL_API_TOKEN=<must match the API's EVAL_API_TOKEN>
    cd packages/evals
    uv sync
    uv run python main.py code-review-test-pr-2

The runner blocks for as long as the workflow takes (~3-8 min per
PR end-to-end). Override via `EVAL_REVIEW_TIMEOUT_S` (seconds,
default 1800). When `EVAL_API_URL` or `EVAL_API_TOKEN` is unset the
runner exits 1 with a clear error.

Docker:

    docker build -f packages/evals/Dockerfile.eval -t sentinel-evals .
    docker run --rm -it \
      -e EVAL_API_URL=http://host.docker.internal:8000/api \
      -e EVAL_API_TOKEN=<token> \
      sentinel-evals code-review-test-pr-2
