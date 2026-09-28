# models — SQLModel tables + enums

The source of truth for the database schema. `__init__.py` re-exports
every table and enum so `alembic/env.py` registers them on
`SQLModel.metadata`. UUID-string primary keys, `TIMESTAMP(timezone=True)`
timestamps, CASCADE deletes at the DB layer.

## Tables

- `repo.py` — `Repo`: one row per user-configured GitHub repo.
- `installation.py` — `Installation`: one row per
  `(user, github_installation_id)`.
- `pull_request.py` — `PullRequest`: one row per `(repo_id, number)`.
- `review.py` — `Review` (+ `ReviewState`): one lifecycle row per
  review workflow run, keyed by the deterministic workflow id.
  `STARTING → RUNNING → (SUCCESS | FAILED)`.
- `code_comment.py` — `CodeComment`: one row per review finding,
  anchored to `(file, from_line/to_line, side)`.
- `review_summary.py` — `ReviewSummary`: walkthrough markdown +
  verdict per run.
- `review_usage.py` — `ReviewUsage`: aggregated token counts per run.
- `llm_config.py` — `LLMConfigRecord`: per-user LLM credentials
  (api key stored plain; redacted at the router boundary).
- `sandbox.py` — `Sandbox`: sandbox lifecycle mirror.
- `enums.py` — `PRStatus`, `CommentSeverity/Side/State`,
  `ReviewVerdict`, `ReviewRunStatus`, `SandboxState`.

## Notes

- Relationships: `Repo` 1—N `PullRequest`; `PullRequest` 1—N
  `CodeComment` / 1—N `ReviewUsage`; each `Review` run links its own
  comments, summary, and usage rows.
- Schema changes go through Alembic (`alembic/versions/`); the
  lifespan `create_all` is dev convenience, not a substitute.
