# llm — provider-agnostic chat-model factory

Builds LangChain chat models from a frozen `LLMCtx` value object.
The only place in the codebase that calls `init_chat_model`.

## Layout

- `service.py` — entry points (see API). `types.py` — `LLMCtx`
  (model as `"provider:model"`, key, base URL, headers, retries,
  rate limit; `provider` / `modelId` properties). `errors.py` —
  `LLMConfigError` (malformed model string / construction failure;
  subclasses `ValueError` so it can be re-raised),
  `LLMContextError`.
- `config/` — per-user `llm_configs` sub-service. See its README.

## API

- `createDefaultLLMContext()` — settings-driven `LLMCtx`
  (`LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` / headers /
  retries / rate limit). Env validated at startup, so no gate here.
- `createUserLLMContext(session, userId)` — `LLMCtx` from the
  user's stored row (model/key/URL from the row, policy knobs from
  settings); `LLMContextError` when no row exists.
- `createLLMModel(ctx, rateLimiterKey=None)` — `BaseChatModel |
  LLMConfigError`. Uniform knobs (retries, per-call or shared
  `InMemoryRateLimiter`, base URL, headers, `SecretStr` key) plus
  provider extras (OpenAI Responses API, DeepSeek json_object).
- `acquireSharedLimiter` / `releaseSharedLimiter` — one limiter
  per fan-out batch wave, referenced by key (never crosses the
  durable boundary).

## Notes

- Used by the triggers (ctx resolution), every review-agent step,
  and `routers/llm_configs.py` via the `config/` sub-service.
