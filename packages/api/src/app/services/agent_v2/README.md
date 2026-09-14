# agent_v2 — planning agent + per-file review agents

Isolated successor of `services/agent` for the v2 review flow.
Not yet dispatched by any trigger; the v1 pipeline keeps serving traffic.

## Intent

Replace the v1 "two big lanes + subagent delegation" shape with:

1. **One planning agent** — explores the repo + split chunks, emits
   repo-level context and per-file enrichment (focus lenses,
   cross-file callers/callees, relevant symbols).
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
├── prompts.py       # Prompt constants — currently " " placeholders.
│                    # Plus NO_FINDINGS_MARKER, the file agent's clean verdict.
├── service.py       # Entry points (camelCase): ctx factory, the two agent
│                    # builders, pure user-prompt formatters, chunk-name helper.
│                    # Owns NO prompt wording (imports from prompts.py) and
│                    # NO middleware assembly (imports from _middleware.py).
└── _middleware.py   # Private: NoDelegationMiddleware (strips `task`
                     # per model-request, sync+async) + buildNoSubMiddleware
                     # (retry + call caps + no-delegation, innermost).
                     # Underscore = not imported outside this package.
```

Data flows one way: `types` ← `service` ← steps; `prompts` and
`_middleware` feed only into `service.py`. The workflow layer never
touches `_middleware.py` directly.

## What's done

- `types.py` — `AgentV2Ctx` (identity + live model/sandbox deps, never
  crosses DBOS); serializable `PlannerContext` / `FileContext`
  (extractor-validated enrichment); `ChunkInventory` (host-side diff
  truth); `FileReviewJob` (the join result).
- `service.py` — `createAgentV2Ctx`, `createPlanningAgent`,
  `createFileReviewAgent`, pure user-prompt builders
  (`createPlanningUserPrompt` gets the inventory file list;
  `createFileReviewUserPrompt` pins one chunk + one context slice),
  `chunkFileForPath`. Errors returned as values (`AgentV2BuildError`),
  never raised.
- `_middleware.py` — `NoDelegationMiddleware` (sync + async hooks,
  name-match filter so backend tools survive) + shared
  retry/limits stack.
- `prompts.py` — constants only (see below).

## What's left

- **Prompt session**: `PLANNING_SYSTEM_PROMPT`,
  `FILE_REVIEW_SYSTEM_PROMPT`, and `PLAN_EXTRACTION_SYSTEM_PROMPT`
  are all `" "` placeholders. Wording lands in a dedicated session;
  no code changes needed when it does.
- Model choice is the run's current `LLMCtx` everywhere (parity
  first; cheaper planner/extractor models are a later optimization).
