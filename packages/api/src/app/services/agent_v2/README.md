# agent_v2 — planning agent + per-file review agents

The agent layer for `workflows/review_v2`: one planning agent
explores the repo and submits per-file enrichment, then one
deep-agent per changed file reviews its chunk. Delegation is
disabled everywhere — no subagents in v2.

## Layout

- `service.py` — entry points: `createAgentV2Ctx` (live model +
  sandbox deps, never crosses DBOS), `createPlanningAgent` /
  `createFileReviewAgent`, plus the `submit_plan` tool mechanics
  (`buildSubmitPlanTool`, closed over the ctx) and `planFilePath`.
  Owns no prompt wording.
- `types.py` — the contract: `AgentV2Ctx` (live, edge-only) plus
  the serializable `PlannerContext` / `FileContext` /
  `ChunkInventory` / `FileReviewJob` that cross step boundaries.
- `errors.py` — `AgentV2BuildError`, returned as a value; DBOS
  steps translate it into step failures.
- `prompts/` — one function per prompt (`shared`, `planning`,
  `file_review`, `summary`). See its README.
- `_middleware.py` — private: `NoDelegationMiddleware` strips the
  `task` tool per model request (plus the retry/limits stack).
  Underscore = never imported outside this package.

## Planner submission (`submit_plan` → `plan.json`)

The planner never returns its plan as text. Its final act is one
`submit_plan` tool call (`args_schema=PlannerContext`); the tool
validates and overwrites `plan.json` in the sandbox workdir, and
`getPlanStep` reads it back (file read + Pydantic validation, no
model call). Missing/invalid file degrades to an empty
`PlannerContext`. Three rules: closure over the ctx (never agent
state), last-write-wins (retries safe), planner-only (file agents
get backend tools alone).

## Notes

- `create_deep_agent` auto-adds a default subagent even with
  `subagents=[]`; the per-request `task` strip is the actual
  enforcement (process-global opt-out would leak across
  pipelines).
- Model choice is the run's `LLMCtx` everywhere; a cheaper planner
  model is a later optimization.
