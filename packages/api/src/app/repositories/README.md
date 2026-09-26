# repositories — async data access, one subclass per table

Thin query layer over SQLModel. Routers, triggers, and workflow steps
never write SQL inline; they go through these classes with a
caller-owned `AsyncSession`.

## Layout

- `base.py` — `BaseRepository[T]`: generic `get` / `find` / `count` /
  `exists` / `add` / `update` / `upsert` / `delete` bound to one
  table (`OrderByArg` for ordering). `__init__.py` re-exports only
  this base; subclasses are imported by full path.
- `repo.py` — `RepoRepository`: `find_by_github_repo_id`,
  `find_by_owner_name`.
- `installation.py` — `InstallationRepository`:
  `find_by_github_installation_id`, `find_by_user`,
  `find_by_user_and_login`.
- `pull_request.py` — `PullRequestRepository`:
  `find_by_repo_and_number`.
- `review.py` — `ReviewRepository`: `find_by_workflow_id`,
  `find_latest_success` (backs incremental re-reviews).
- `code_comment.py` — `CodeCommentRepository`: `find_by_review_id`,
  `find_by_ids`, `count_for_user`, `count_p1_for_user` (bugs-caught
  stat).
- `review_summary.py` — `ReviewSummaryRepository`:
  `find_by_review_id`, `count_for_user`.
- `review_usage.py` — `ReviewUsageRepository`: base-only, no custom
  queries.
- `llm_config.py` — `LLMConfigRecordRepository`: `find_by_user`.
- `sandbox.py` — `SandboxRepository`: base-only, no custom queries.

## Notes

- Every method takes `session` explicitly; transactions and commits
  belong to the caller (router / DBOS step), never the repository.
