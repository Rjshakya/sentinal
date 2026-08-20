### AGENTS.md

```diff

index c2f70bd..2875c81 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -259,65 +259,19 @@ them on `SQLModel.metadata`.
  260   260  
  261   261  `src/app/services/`:
  262   262  
  263       -- `agent/` — the review-agent schemas + prompts.
        263 +- `agent/` — the review-agent schemas + prompts + setup pipeline.
  264   264    - `models.py` — `CodeCommentDraft`, `ReviewComments` (mixed severities),
  265   265      `SummaryResult`, `ReviewResult`.
  266   266    - `prompts.py` — `PR_SUMMARY_SYSTEM_PROMPT` (summarizer agent) and
  267   267      `REVIEW_COMMENTS_SYSTEM_PROMPT` (the merged security/correctness/style
  268   268      rubric assigning P1_CRITICAL / P2_WARNING / P3_NITPICK).
  269   269    - `helpers.py` — small prompt/result helpers (`extract_message_kinds`).
  270       -- `setup/` — the durable per-repo setup workflow:
  271       -  `ensure_repo_and_sandbox_step` → `mint_installation_token_step` →
  272       -  `git_clone_step` → (`finally`) `stop_setup_sandbox_step`. Typed errors in
  273       -  `errors.py`, Pydantic surface in `types.py` (`SetupWorkflowInput`,
  274       -  `RepoContext`, `SetupWorkflowResult`), pure helpers in `_helpers.py`.
  275       -  Workflow id `setup:{user_id}:{github_repo_id}`. When
  276       -  `index_after_setup` is true (router sets it from
  277       -  `Settings.indexing_configured`), the workflow fires off `indexRepo`
  278       -  fire-and-forget as its final step.
  279       -- `indexing/` — the full-indexing pipeline: tree-sitter chunking in
  280       -  the sandbox, LanceDB ingest + S3 persistence inside the same
  281       -  sandbox.
  282       -  - `workflow.py` — `indexRepo` (id `index:{owner}:{repo}`): index
  283       -    run row → sandbox create → authenticated clone URL → shallow
  284       -    clone → upload scripts → combined chunking + ingestion
  285       -    (`mode="overwrite"` full rewrite) → success/error mirrors; sandbox
  286       -    killed in `finally`. Lifecycle mirror rows live in `index_runs`.
  287       -  - `helpers.py` — pure helpers (`build_table_uri`, `index_workflow_id`,
  288       -    `parse_index_summary`); `types.py` — frozen workflow input/context;
  289       -    `errors.py` — the `IndexingError` hierarchy + `_should_retry_index`.
  290       -  - `steps/` — `ensureIndexSandbox`, `getRepoUrl` (installation token
  291       -    → authenticated clone URL), `gitCloneToSandbox`,
  292       -    `uploadScriptsToSandbox`, `runIndexPipeline` (`run_index.py`),
  293       -    `index_run_steps.py` (best-effort `index_runs` mirror),
  294       -    `update_repo.py` (best-effort `repos.is_indexed` mirror),
  295       -    `stop_sandbox.py` (finally).
  296       -  - `scripts/` — in-sandbox files uploaded as bytes (never imported
  297       -    on the host): `chunking.py` (tree-sitter generator), `ingestion.py`
  298       -    (LanceDB writer).
  299       -  - `incremental/` — the incremental-indexing pipeline, triggered by
  300       -    GitHub `push` webhooks on the default branch.
  301       -    - `webhook.py` — `handle_push_event` (the push adapter): default
  302       -      branch check → aggregate changed files across all commits →
  303       -      resolve user/repo → gate on `is_indexed` + indexing config →
  304       -      dispatch `incrementalIndexRepo`. Every skip path returns a
  305       -      `PushWebhookAck` with a `skip_reason`.
  306       -    - `workflow.py` — `incrementalIndexRepo` (id
  307       -      `index:{owner}:{repo}:{head_sha[:7]}`): host-side delete of the
  308       -      `removed + modified` chunks → (only when files remain) a fresh
  309       -      index sandbox → clone → upload scripts → append-only in-sandbox
  310       -      ingest. Success mirrors keep `is_indexed = true`; **errors never
  311       -      flip `is_indexed`** (the dataset still exists).
  312       -    - `steps/` — `delete_stale_chunks.py` (host-side
  313       -      `lancedb.connect_async` + `table.delete`, no sandbox),
  314       -      `ensure_sandbox.py` (fresh E2B sandbox per run),
  315       -      `upload_scripts.py` (uploads shared `chunking.py` +
  316       -      incremental `incremental_ingestion.py`),
  317       -      `run_incremental_ingest.py` (the append command).
  318       -    - `scripts/incremental_ingestion.py` — in-sandbox append-only
  319       -      LanceDB writer for the explicit file list + FTS rebuild.
  320       -    - `helpers.py` — pure `push_skip_reason`, `extract_push_files`,
  321       -      `incremental_workflow_id`, `build_delete_predicates`.
        270 +  - `setup_workflow/` — the durable per-repo setup workflow:
        271 +    `ensure_repo_and_sandbox_step` → `mint_installation_token_step` →
        272 +    `git_clone_step` → (`finally`) `stop_setup_sandbox_step`. Typed errors in
        273 +    `errors.py`, Pydantic surface in `types.py` (`SetupWorkflowInput`,
        274 +    `RepoContext`, `SetupWorkflowResult`), pure helpers in `_helpers.py`.
        275 +    Workflow id `setup:{user_id}:{github_repo_id}`.
  322   276  - `review/` — the durable review pipeline.
  323   277    - `workflow.py` — the top-level `review_workflow` DBOS orchestrator (see
  324   278      §3.5).
@@ -352,9 +306,7 @@ them on `SQLModel.metadata`.
  353   307      agent middleware stack (`ModelRetryMiddleware` max 3 retries, 2x
  354   308      backoff, `on_failure="error"`; `ModelCallLimitMiddleware` run cap 50;
  355   309      `ToolCallLimitMiddleware` run cap 200) wired into both review agents.
  356       -  - `errors.py` — typed error variants for the pipeline (incl.
  357       -    `ReviewRunUpdateError`, the transient error raised by the `review`
  358       -    lifecycle steps).
        310 +  - `errors.py` — typed error variants for the pipeline.
  359   311    - `steps/` — one file per I/O boundary, each exposing a pure helper and a
  360   312      DBOS-wrapped variant: `resolve_repo`/`resolve_repo_tx`,
  361   313      `resolve_sandbox`/`resolve_sandbox_step`, `fetch_diff_step`,
@@ -363,10 +315,6 @@ them on `SQLModel.metadata`.
  364   316      `persist_summary`/
  365   317      `persist_review_summary_tx`, `persist_comments`/
  366   318      `persist_code_comments_tx`, `persist_usage`/`persist_review_usage_tx`,
  367       -    `review_run_steps` (`mark_review_is_running_step` /
  368       -    `mark_review_is_stopped_step` / `mark_review_is_errored_step` +
  369       -    `build_error_context` — the durable `review` lifecycle-row steps,
  370       -    retried 3x on `ReviewRunUpdateError`),
  371   319      `stop_sandbox_step`.
  372   320  - `pr_issue_comment/` — the comment-trigger path.
  373   321    - `workflow.py` — `trigger_issue_comment_workflow` (id
@@ -414,7 +362,7 @@ to the provider's native env var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  415   363  
  416   364  ### 3.4 Domain model
  417   365  
  418       -Nine tables; UUID (string, `uuidToStr()`) primary keys, timestamps are
        366 +Eight tables; UUID (string, `uuidToStr()`) primary keys, timestamps are
  419   367  `TIMESTAMP(timezone=True)` with `now()` server defaults, CASCADE deletes at
  420   368  the DB layer with `passive_deletes=True` on relationships.
  421   369  
@@ -475,32 +423,8 @@ pull_requests
  476   424  ├── head_branch / head_sha
  477   425  └── created_at / updated_at
  478   426  
  479       -review                       (per-run lifecycle row; one row per review_workflow run)
  480       -├── id                str  PK
  481       -├── user_id           str  index
  482       -├── repo_id           str  → repos.id  CASCADE
  483       -├── gh_repo_id        bigint
  484       -├── pr_id             str  → pull_requests.id  CASCADE
  485       -├── pr_number         int
  486       -├── commit_id         str            (head sha; no FK)
  487       -├── base_sha          str?
  488       -├── workflow_id       str  UNIQUE index  (the deterministic
  489       -│                                       `review:{repo_id}:{pr}:{head_sha[:7]}` id)
  490       -├── trigger           str            ('opened' | 'comment')
  491       -├── state             STARTING | RUNNING | SUCCESS | FAILED  index
  492       -├── comment_count     int?
  493       -├── github_review_id  bigint?        (back-link to the GitHub PR review)
  494       -├── error_name / error_message  str?
  495       -├── error_context     jsonb?         (agent failure context; see build_error_context)
  496       -├── sandbox_id        str?
  497       -├── llm_provider / llm_model / llm_base_url  str?  (snapshot of the
  498       -│                                        resolved LLMConfig at run time)
  499       -├── started_at / completed_at  timestamptz?
  500       -└── created_at / updated_at
  501       -
  502   427  code_comments
  503   428  ├── pr_id             str  → pull_requests.id  CASCADE
  504       -├── review_id         str? → review.id  CASCADE    (lifecycle row of the run)
  505   429  ├── commit_id         str            (head sha; no FK — commit_snapshots was dropped)
  506   430  ├── github_comment_id bigint?        (back-link to the comment posted on GitHub)
  507   431  ├── file_name         str(1024)
@@ -515,7 +439,6 @@ code_comments
  516   440  
  517   441  review_summaries
  518   442  ├── pr_id             str  → pull_requests.id  CASCADE
  519       -├── review_id         str? → review.id  CASCADE    UNIQUE (lifecycle row of the run)
  520   443  ├── commit_id         str            UNIQUE (head sha; no FK)
  521   444  ├── github_review_id  bigint?        (back-link to the GitHub PR review)
  522   445  ├── summary           text
@@ -526,24 +449,20 @@ review_usages
  527   450  ├── id                str  PK
  528   451  ├── user_id           str  index
  529   452  ├── pr_id             str  → pull_requests.id  CASCADE
  530       -├── review_id         str? → review.id  CASCADE    (lifecycle row of the run)
  531   453  ├── pr_number         int
  532   454  ├── repo_id           str  → repos.id  CASCADE
  533   455  ├── review_summary_id uuid? → review_summaries.id  CASCADE
  534   456  ├── review_status     SUCCESS | FAILED
  535   457  ├── input_tokens / output_tokens / total_tokens  int
  536   458  ├── input_token_details  jsonb?     (cache_read / cache_creation)
  537       -├── llm_model_id / llm_provider / llm_base_url  str?  (snapshot of the
  538       -│                                        resolved LLMConfig at run time)
  539   459  └── created_at / updated_at
  540   460  ```
  541   461  
  542   462  Enums (Python and DB-checked): `PRStatus`, `CommentSeverity`,
  543   463  `CommentSide`, `CommentState`, `ReviewVerdict`, `SandboxState`,
  544       -`ReviewRunStatus`, `ReviewState`. The relationship graph: `Repo` 1—N
  545       -`PullRequest`, `PullRequest` 1—N `CodeComment` and 1—1 `ReviewSummary`
  546       -(per commit), 1—N `ReviewUsage`; `Review` (the per-run lifecycle row)
  547       -1—N `CodeComment`, 1—1 `ReviewSummary` (per run) and 1—N `ReviewUsage`.
        464 +`ReviewRunStatus`. The relationship graph: `Repo` 1—N `PullRequest`,
        465 +`PullRequest` 1—N `CodeComment` and 1—1 `ReviewSummary` (per commit),
        466 +1—N `ReviewUsage`.
  548   467  
  549   468  ### 3.5 Request lifecycles
  550   469  
@@ -585,18 +504,15 @@ toggle `suspended_at`; `installation_repositories.added` → upsert one
  586   505  `removed` → delete rows; `pull_request.opened` → `handle_pull_request_opened`
  587   506  (dispatches `review_workflow`); `issue_comment.created` →
  588   507  `handle_issue_comment_created` (dispatches `trigger_issue_comment_workflow`);
  589       -`push` → `handle_push_event` (dispatches the incremental indexing
  590       -workflow for default-branch pushes — see the indexing pipeline below);
  591   508  everything else → 202 with a log line.
  592   509  
  593   510  **Setup pipeline.** `POST /ai/repo/setup` (202) dispatches one
  594   511  `setup_workflow` per new repo: `ensure_repo_and_sandbox_step` (writes the
  595   512  `repos` + `sandboxes` rows) → `mint_installation_token_step` (GitHub
  596       -installation token, embedded in the authenticated clone URL for the
        513 +installation token, passed into the sandbox as `GITHUB_TOKEN` for the
  597   514  clone) → `git_clone_step` → `stop_setup_sandbox_step` in `finally`. The
  598   515  router's GET endpoint polls DBOS status. When `index_after_setup=True`
  599       -(router sets it from `Settings.indexing_configured`) and indexing is
  600       -configured, the workflow fires off
        516 +and `Settings.indexing_configured` is true, the workflow fires off
  601   517  `app.services.indexing.workflow.indexRepo` with the deterministic id
  602   518  `index:{owner}:{repo}` and passes `local_repo_id=ctx.repo_id` so the
  603   519  indexing run can flip the parent `repos.is_indexed` mirror.
@@ -618,33 +534,6 @@ public `/github/repos` endpoint reads `Repo.is_indexed` alongside
  619   535  the dashboard's "Index" button only renders when
  620   536  `is_configured && !is_indexed`.
  621   537  
  622       -**Incremental indexing pipeline.** GitHub `push` deliveries on the
  623       -repo's default branch dispatch `incrementalIndexRepo` under the
  624       -deterministic id `index:{owner}:{repo}:{head_sha[:7]}` (duplicate
  625       -deliveries of the same head SHA dedupe; distinct commits get distinct
  626       -runs). The adapter (`app.services.indexing.incremental.webhook`)
  627       -aggregates `added` / `removed` / `modified` across **all** commits in
  628       -the payload, skips when the repo has never completed a full index
  629       -(`is_indexed` falsy — the full index owns the bootstrap), and skips
  630       -`deleted` / `created` / non-default-branch pushes. The workflow then:
  631       -
  632       -1. `deleteStaleChunksStep` — host-side LanceDB delete of the
  633       -   `removed + modified` files' chunks (no sandbox; `table.delete`
  634       -   with `file_name IN (...)` predicates chunked at 100 names).
  635       -2. When `added + modified` is non-empty — a **fresh** index sandbox,
  636       -   authenticated clone URL → shallow clone → upload scripts →
  637       -   `incremental_ingestion.py` appends chunks for the explicit file
  638       -   list (never `mode="overwrite"`) and rebuilds the FTS index
  639       -   (`create_fts_index(replace=True)`).
  640       -3. `SUCCESS` mirrors keep `is_indexed = true` with
  641       -   `indexed_run_id` back-pointed; **`ERROR` mirrors never flip
  642       -   `is_indexed`** — the dataset still exists and remains searchable,
  643       -   only a few files are stale until the next successful push.
  644       -
  645       -Both the full and incremental runs record one row in `index_runs`
  646       -(each `workflow_id` is unique), so the dashboard lists them
  647       -indistinguishably.
  648       -
  649   538  **Review pipeline.** Two triggers dispatch `review_workflow`:
  650   539  
  651   540  1. GitHub `pull_request` `opened` webhook →
@@ -662,19 +551,13 @@ the same head SHA do not re-run the agent. `review_workflow` then runs:
  663   552  2. `resolve_sandbox_step` — look up the active `Sandbox` row and connect to
  664   553     the E2B sandbox (`@DBOS.step`). Only the sandbox **id** travels onward;
  665   554     each step reconnects.
  666       -3. `upsert_pull_request_tx` — insert/update the `PullRequest` row.
  667       -4. `mark_review_is_running_step` — create (or reset on restart) the
  668       -   `review` lifecycle row in `RUNNING`, keyed by the deterministic
  669       -   `workflow_id` (unique index), with the PR link, sandbox, and LLM
  670       -   snapshot; returns the row id. The step is **durable**: retried 3x on
  671       -   transient DB failures and raises `ReviewRunUpdateError` otherwise.
  672       -5. `update_repo_step` — refresh the sandbox repo to the default branch.
  673       -6. `fetch_diff_step` — `git diff base_sha...head_sha` written to the
        555 +3. `fetch_diff_step` — `git diff base_sha...head_sha` written to the
  674   556     sandbox (`file.diff`).
  675       -7. `parse_diff_step` — parse the diff into a `HunkMap` and write
        557 +4. `parse_diff_step` — parse the diff into a `HunkMap` and write
  676   558     `diff.json` alongside it. The `HunkMap` is the source of truth for which
  677   559     `(file, line, side)` anchors GitHub will accept.
  678       -8. `invoke_summary_agent_step` / `invoke_comments_agent_step` — the
        560 +5. `upsert_pull_request_tx` — insert/update the `PullRequest` row.
        561 +6. `invoke_summary_agent_step` / `invoke_comments_agent_step` — the
  679   562     **two parallel agent steps**, started concurrently from the workflow
  680   563     body via `asyncio.gather(return_exceptions=True)` (the documented DBOS
  681   564     parallel-steps pattern; deterministic start order). Each
@@ -693,30 +576,13 @@ the same head SHA do not re-run the agent. `review_workflow` then runs:
  694   577     comment lists) with a warning log, and the review completes with the
  695   578     successful lanes' output; token usage is aggregated per model from
  696   579     successful lanes only.
  697       -9. `filter_drafts(review, hunk_map)` — pure server-side backstop that drops
        580 +7. `filter_drafts(review, hunk_map)` — pure server-side backstop that drops
  698   581     any draft whose anchor is not in the `HunkMap`.
  699       -10. `persist_review_summary_tx` + `persist_code_comments_tx` — one
  700       -    `ReviewSummary` row and one `CodeComment` row per surviving draft,
  701       -    each carrying the run's `review_id` (the lifecycle row).
  702       -11. `persist_review_usage_tx` — one `ReviewUsage` row with aggregated token
  703       -    counts (success path; `review_status=SUCCESS`), carrying `review_id`.
  704       -12. `mark_review_is_stopped_step` — flip the `review` row to `SUCCESS`
  705       -    with the surviving comment count and the GitHub review id (from the
  706       -    awaited post workflow). Durable like the running step.
  707       -13. `stop_sandbox_step` — always, in a `finally`.
  708       -
  709       -Steps 3–4 run **inside** the `try`, so the `finally` sandbox stop also
  710       -covers a raising `upsert_pull_request_tx` / running step. The `except`
  711       -block flips the `review` row to `FAILED` via
  712       -`mark_review_is_errored_step` (guarded by its own try/except so a
  713       -failure while recording the error never masks the original exception —
  714       -which is then re-raised) and re-raises. All three `mark_*` steps are
  715       -durable (`@DBOS.step`, `retries_allowed=True`, `max_attempts=3`,
  716       -`should_retry=_SHOULD_RETRY_TRANSIENT`) and raise
  717       -`ReviewRunUpdateError` on failure, so a persistent lifecycle-row
  718       -failure marks the workflow ERROR instead of silently leaving the row
  719       -stuck in `RUNNING`; the running step's find-or-create semantics keep
  720       -retries idempotent via the unique `workflow_id`.
        582 +8. `persist_review_summary_tx` + `persist_code_comments_tx` — one
        583 +   `ReviewSummary` row and one `CodeComment` row per surviving draft.
        584 +9. `persist_review_usage_tx` — one `ReviewUsage` row with aggregated token
        585 +   counts (success path; `review_status=SUCCESS`).
        586 +10. `stop_sandbox_step` — always, in a `finally`.
  721   587  
  722   588  The summary in `review_summaries.summary` is the `summarizer` agent's
  723   589  markdown output (from its `SummaryResult` structured response), and the verdict is
@@ -858,9 +724,7 @@ corresponding route file does not exist yet.
  859   725    dispatch; workflows checkpoint every I/O step, and transient errors are
  860   726    retried per-step via `should_retry` predicates.
  861   727  - **Workflow ids are deterministic and encode the domain**
  862       -  (`setup:{user_id}:{gh_repo_id}`, `index:{owner}:{repo}` for full
  863       -  indexing, `index:{owner}:{repo}:{head_sha[:7]}` for incremental
  864       -  indexing, `review:{repo_id}:{pr}:{head_sha[:7]}`,
        728 +  (`setup:{user_id}:{gh_repo_id}`, `review:{repo_id}:{pr}:{head_sha[:7]}`,
  865   729    `post:{…}`, `trigger_issue_comment:{comment_id}`) so duplicate deliveries
  866   730    dedupe and restarts are safe.
  867   731  - **Workflow inputs declare canonical identifiers explicitly.**
@@ -939,8 +803,7 @@ corresponding route file does not exist yet.
  940   804  - Review pipeline (workflow + steps + agent fan-out) → `packages/api/src/app/services/review/`
  941   805  - Comment-trigger workflow → `packages/api/src/app/services/pr_issue_comment/`
  942   806  - GitHub post workflow → `packages/api/src/app/services/github/`
  943       -- Setup workflow → `packages/api/src/app/services/setup/`
  944       -- Indexing pipeline (full + incremental) → `packages/api/src/app/services/indexing/`
        807 +- Setup workflow → `packages/api/src/app/services/agent/setup_workflow/`
  945   808  - Per-user LLM config service + routes → `packages/api/src/app/services/llm_config/`, `packages/api/src/app/routers/llm_configs.py`
  946   809  - Webhook receiver → `packages/api/src/app/routers/webhooks.py`
  947   810  - Route tree → `web/src/routeTree.gen.ts` (generated)

```
