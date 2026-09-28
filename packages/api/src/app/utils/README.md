# utils — shared value types and pure helpers

Small dependency-free modules imported across routers, services, and
workflows. No I/O, no settings reads.

## Layout

- `branded.py` — `NewType` ids/keys (`UserId`, `InstallationId`,
  `RepoOwner`, `RepoName`, `CommitId`, `AccessToken`, …). Erase at
  runtime, enforced statically by pyright: a bare `str`/`int` cannot
  flow into a ctx-typed parameter by accident.
- `util.py` — in-sandbox layout constants (`SANDBOX_HOME`,
  `WORKSPACE_NAME`, `GRAPH_DB_NAME`, `SCRIPT_FILES`, …) plus the
  path builders (`workspace_path`, `repo_path`, `graph_db_path`, …)
  and `uuidToStr()`.
- `schema.py` — agent structured-output models: `CodeCommentDraft`,
  `ReviewComments`, `SummaryResult`, `ReviewResult` (with the
  `CommentSeverityStr` / `CommentSideStr` / `ReviewVerdictStr`
  literals).
- `severity_badge.py` — `badgeLine` / `withSeverityBadge`: embeds the
  severity badge image into GitHub comment bodies.
- `api_response.py` — `api_response(data, success, error)` envelope
  helper. Currently no callers; routers use typed Pydantic
  `response_model`s instead.

## Notes

- `utils/schema.py` (agent output shapes) is unrelated to
  `routers/schemas/` (HTTP request/response shapes) despite the
  similar name.
