# routers/schemas — HTTP request/response shapes

Pydantic models for the routers' wire contracts, one module per
router. Schemas live next to their consumer (not in a top-level
package) so the route and its contract change together.

## Layout

- `ai.py` — `POST /ai/repo/setup` shapes: `SetupRepo` (one repo to
  configure) / `SetupRequest` (non-empty repo list) /
  `ConfiguredRepo` (per-repo outcome: echoed id, local `repo_id`,
  `skipped`, `error`) / `ConfigureResponse` (the list).
- `llm_config.py` — per-user LLM config shapes:
  `CreateLLMConfigRequest` (provider, model_id, base_url, api_key) /
  `LLMConfigResponse` (stored row with `api_key` omitted) /
  `LLMConfigUpsertResponse` (`{data, success, error, test_result}`)
  / `LLMConfigTestResponse` (same envelope minus `data`) /
  `to_llm_config_response` (the redaction mapper — the single place
  that strips the key, so routers cannot leak it by accident).

## Notes

- Routers that already declare a typed `response_model` need no
  envelope helper; the `{data, success, error}` shape above is the
  contract for the LLM-config endpoints only.
- Unrelated despite the name: `utils/schema.py` holds the review
  agents' structured-output models, not HTTP shapes.
