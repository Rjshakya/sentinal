# llm/config — per-user LLM configuration rows

Owns the `llm_configs` table: probing a candidate config with a
structured-output deep-agent call, then upserting it. The probe
path never raises — it returns the outcome.

## Layout

- `service.py` — entry points (see API). `types.py` —
  `LLMConfigProbeResult` / `LLMConfigTestResult` (internal) /
  `LLMConfigTestResultPublic` (the `{response, exception}` shape
  the router returns). `errors.py` — `LLMConfigStoreError`.

## API

- `testLLMConfig(candidate)` — run the probe; returns the public
  test result (response on success, exception chain on failure).
- `saveUserLLMConfig(session, userId, candidate)` — probe, then
  upsert the row on success.
- `listUserLLMConfigs(session, userId)` — stored rows for the
  redacted `GET` listing.

## Notes

- Used only by `routers/llm_configs.py`. The probe exercises the
  same structured-output path the review agents use, so a passing
  probe means the model works for reviews.
