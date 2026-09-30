# sandbox — sandbox ctx assembly + provider map

Builds the serializable run ctx and resolves the provider class
for a ctx's `providerId`. The provider owns the lifecycle
(create / connect / kill); this package owns everything else.

## Layout

- `service.py` — `createSandboxCtx(…)` (settings-driven defaults
  resolved at the edge), `getProvider(providerId)` over the
  `Providers` map (`{"e2b": E2BService}`), `getDefaulSandboxName`.
  `getDefaulProvider` is currently unused (callers pass the
  settings value directly).
- `types.py` — `SandboxCtx` (pure data, crosses the durable boundary),
  `ProviderId` (`"e2b" | "daytona"`), `ProviderMap`,
  `BaseSandboxService`.
- `errors.py` — `SandboxProviderError`.
- `e2b.py` — `E2BService`: create/connect/kill via the E2B SDK
  (template from `settings.e2b_template`).
- `e2b_template.py` — pre-baked template builder:
  `code-interpreter-v1` + `pip install sentinel-codegraph`
  (pin owned here as `CODEGRAPH_PCK_NAME`). Built by
  `scripts/build_e2b_template.py`, locally or in CI
  (`.github/workflows/build-template.yml`, path-filtered to the
  template inputs); the review pipeline picks it up via
  `settings.e2b_template` with no code change. Live tests in
  `tests/sandbox/e2b/` build the template and assert the CLI
  exists, killing the verification sandbox afterwards.

## Notes

- Used by the triggers (ctx resolution) and every review step via
  `getProvider`. Only the sandbox id travels between steps; each
  step reconnects.
- Daytona exists only as a `ProviderId` tag and settings fields —
  no provider class is registered, so `getProvider("daytona")`
  raises (the `daytona` pip dependency was removed).
