# services — domain services behind a shared contract

One subpackage per domain. Every service follows the same rules:
ctx-object dependency injection, errors returned as values (never
raised), no logging, I/O at the edge. `__init__.py` is an empty
marker; each subpackage owns its public surface.

## Layout

- `agent_v2/` — review-agent layer: planning agent + per-file review
  agents over LangChain/deepagents. See its README.
- `github/` — the only way to talk to GitHub: App client factory
  plus `installation` / `repo` / `pr` / `webhook` sub-services.
- `llm/` — provider-agnostic chat-model factory (`LLMCtx` in,
  `BaseChatModel` out) plus the per-user `config/` sub-service.
- `sandbox/` — sandbox ctx assembly + provider map (E2B live).

## The contract

- **Ctx carries the dependency.** Identity + the injected client
  (e.g. the installation-scoped githubkit client) live on the ctx.
  The ctx factory (`createRepoCtx`, `createInstallationCtx`, …) is
   the I/O boundary. Live-client ctxs never cross the durable
   boundary; serializable ctxs (`SandboxCtx`, `LLMCtx`) do.
- **Errors are values.** Expected failures return typed error
  models (`GitHubRepoError`, `LLMConfigError`, …); callers
  discriminate with `isinstance`. Raising is reserved for
  programmer/config errors.
- **No logging, no retries inside.** Those belong to the edge
  (routers, webhook receivers, durable steps).
- **camelCase entry points** (`listInstallationRepos`,
  `createLLMModel`) — the deliberate convention island.
