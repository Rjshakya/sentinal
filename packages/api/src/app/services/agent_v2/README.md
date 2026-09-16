# agent_v2 — planning agent + per-file review agents

The agent layer for the review pipeline (`workflows/review_v2`):
planner + per-file review agents, built on the run's chat model with
the sandbox as backend.

## Intent

Replace the v1 "two big lanes + subagent delegation" shape with:

1. **One planning agent** — explores the repo + split chunks, then
   submits repo-level context and per-file enrichment (focus lenses,
   cross-file callers/callees, relevant symbols) via the
   `submit_plan` tool as its final act — not as free text.
2. **One deep-agent per changed file** — reviews its single chunk,
   scoped by its planner-context slice. Finds bugs or answers
   `NO_FINDINGS`.

Every agent is built with delegation disabled: `subagents=[]` plus
`NoDelegationMiddleware`, which strips the `task` tool from every
model request. No subagents anywhere in v2.

## Why the middleware (not just `subagents=[]`)

`create_deep_agent` auto-adds a default `general-purpose` subagent
even when `subagents=[]`. The only supported opt-out is a
process-global harness-profile registration — which would leak into
the v1 pipeline sharing this process. The per-request `task` strip
is therefore the actual enforcement (per-agent, isolation-safe);
`subagents=[]` documents intent.

## Planner submission (`submit_plan` → `plan.json`)

The planner never returns its plan as text — there is no extractor
LLM. Instead the planner agent carries one custom tool,
`submit_plan` (`args_schema=PlannerContext`), and its final act must
be exactly one call. The tool validates the submission, dumps it as
compact JSON, and overwrites the run's `plan.json` in the sandbox
working dir (`planFilePath`: `{rootPath}/plan.json`). Downstream
(`getPlanStep`) reconnects and reads the file back into a
`PlannerContext` — a file read plus Pydantic validation, no model
call. A missing file (agent never submitted) or an invalid one
degrades to an empty `PlannerContext`, never fails the run.

Three deliberate choices:

- **Closure, not agent state.** The tool is built inside
  `createPlanningAgent`, closed over the ctx's sandbox handle.
  Agent state is checkpointed and must never carry live handles;
  the prompts never name the path, so the agent can only reach it
  through the tool — never via a direct write.
- **Last write wins.** Overwrite (not create-once) semantics, so a
  duplicate submission is harmless and agent retries stay safe.
- **Planner-only.** File-review agents get backend tools alone;
  `submit_plan` exists on exactly one agent.

## Layout

```
services/agent_v2/
├── __init__.py      # Public surface: re-exports the contract
│                    # (ctx, planner payloads, builders, prompt consts).
│                    # Anything not re-exported here is private to the package.
├── types.py         # The contract. Two halves:
│                    #  • AgentV2Ctx — live deps (chat model + sandbox handle).
│                    #    Built per-step at the edge, NEVER crosses DBOS.
│                    #  • PlannerContext / FileContext / ChunkInventory /
│                    #    FileReviewJob — frozen, JSON-serializable data.
│                    #    These DO cross step boundaries (planner output,
│                    #    inventory, per-file jobs).
├── errors.py        # AgentV2BuildError — returned as a VALUE from builders,
│                    # never raised. Callers (DBOS steps) translate it into
│                    # ReviewStepFailure / TransientReviewStepFailure.
├── prompts/       # One function per prompt (never bare constants).
│                    #  • shared.py — v2-owned COMMENT_BODY_FORMAT copy,
│                    #    NO_FINDINGS marker, identity/PR-intent builders.
│                    #  • planning.py — planning system rubric (narrow
│                    #    scalars: identity + tool budget, submission
│                    #    contract) + user builder (ctx + inventory + PR
│                    #    title/body/author) + SUBMIT_PLAN_TOOL_DESCRIPTION.
│                    #  • file_review.py — single-chunk review rubric (no
│                    #    delegation language — v2 strips the task tool)
│                    #    + user builder (ctx + job slice + PR intent).
│                    #  • __init__.py — the package's public surface.
├── service.py       # Entry points (camelCase): ctx factory + the two
│                    # agent builders (system prompts built from ctx
│                    # scalars via the prompts package) + the submit_plan
│                    # tool mechanics (buildSubmitPlanTool, closed over
│                    # the ctx — never agent state) + the host-owned plan
│                    # path (planFilePath). Owns NO prompt wording
│                    # (imports from prompts/) and NO middleware
│                    # assembly (imports from _middleware.py).
└── _middleware.py   # Private: NoDelegationMiddleware (strips `task`
                     # per model-request, sync+async) + buildNoSubMiddleware
                     # (retry + call caps + no-delegation, innermost).
                     # Underscore = not imported outside this package.
```

Data flows one way: `types` ← `prompts` ← `service` ← steps for
agent construction; the invoke steps import the user builders
directly from `prompts`. `_middleware` feeds only into `service.py`.
The workflow layer never touches `_middleware.py` directly.

## What's done

- `types.py` — `AgentV2Ctx` (identity + live model/sandbox deps, never
  crosses DBOS); serializable `PlannerContext` / `FileContext`
  (tool-submitted, file-validated enrichment); `ChunkInventory`
  (host-side diff truth: real paths + observed chunk files via
  `ChunkRef`); `FileReviewJob` (the join result: `filePath` +
  `diffPath`).
- `prompts/` — system builders (exploration rubric with a budget
  line and a submit-plan contract; single-chunk review rubric with
  no delegation language, gutter anchors, and the findings-block
  contract) plus user builders (identity + diff paths +
  inventory/job slice + PR title/body/author).
- `service.py` — `createAgentV2Ctx`, `createPlanningAgent` (plus
  `buildSubmitPlanTool` / `planFilePath`: the submit tool and the
  host-owned plan path), `createFileReviewAgent` (system prompts
  built from ctx scalars via the prompts package).
- `_middleware.py` — `NoDelegationMiddleware` (sync + async hooks,
  name-match filter so backend tools survive) + shared
  retry/limits stack.

## What's left

- Model choice is the run's current `LLMCtx` everywhere (parity
  first; cheaper planner models are a later optimization).
