# Diff overview

PR #45 — commit abc12346

## Files Added

---

packages/api/src/app/services/agent/setup_workflow/__init__.py
packages/api/src/app/services/agent/setup_workflow/_helpers.py
packages/api/src/app/services/agent/setup_workflow/errors.py
packages/api/src/app/services/agent/setup_workflow/steps/__init__.py
packages/api/src/app/services/agent/setup_workflow/steps/ensure_repo_and_sandbox.py
packages/api/src/app/services/agent/setup_workflow/steps/git_clone.py
packages/api/src/app/services/agent/setup_workflow/steps/mint_installation_token.py
packages/api/src/app/services/agent/setup_workflow/steps/stop_sandbox.py
packages/api/src/app/services/agent/setup_workflow/types.py
packages/api/src/app/services/agent/setup_workflow/workflow.py

---

## Files Removed

---

.opencode/opencode.json
packages/api/alembic/versions/86d7ae9f650b_.py
packages/api/alembic/versions/dc8dcc7ea22e_.py
packages/api/alembic/versions/ec54a29f7fe5_.py
packages/api/src/app/models/review.py
packages/api/src/app/services/indexing/incremental/__init__.py
packages/api/src/app/services/indexing/incremental/errors.py
packages/api/src/app/services/indexing/incremental/helpers.py
packages/api/src/app/services/indexing/incremental/scripts/__init__.py
packages/api/src/app/services/indexing/incremental/scripts/incremental_ingestion.py
packages/api/src/app/services/indexing/incremental/steps/__init__.py
packages/api/src/app/services/indexing/incremental/steps/delete_stale_chunks.py
packages/api/src/app/services/indexing/incremental/steps/ensure_sandbox.py
packages/api/src/app/services/indexing/incremental/steps/run_incremental_ingest.py
packages/api/src/app/services/indexing/incremental/steps/upload_scripts.py
packages/api/src/app/services/indexing/incremental/types.py
packages/api/src/app/services/indexing/incremental/webhook.py
packages/api/src/app/services/indexing/incremental/workflow.py
packages/api/src/app/services/indexing/steps/get_repo_url.py
packages/api/src/app/services/review/steps/review_run_steps.py
packages/api/src/app/services/review/steps/update_repo.py
packages/api/tests/test_incremental_indexing.py
packages/api/tests/test_prompts.py
web/src/components/theme-provider.tsx
web/src/routes/dashboard/search/$owner/$name/-components/code-block.tsx
web/src/routes/dashboard/search/$owner/$name/-components/search-results.tsx

---

## Files Modified

---

AGENTS.md
packages/api/src/app/core/llm.py
packages/api/src/app/core/middleware.py
packages/api/src/app/models/__init__.py
packages/api/src/app/models/code_comment.py
packages/api/src/app/models/review_summary.py
packages/api/src/app/models/review_usage.py
packages/api/src/app/routers/ai.py
packages/api/src/app/routers/search.py
packages/api/src/app/routers/users.py
packages/api/src/app/routers/webhooks.py
packages/api/src/app/schemas/setup.py
packages/api/src/app/services/agent/models.py
packages/api/src/app/services/agent/prompts.py
packages/api/src/app/services/indexing/errors.py
packages/api/src/app/services/indexing/helpers.py
packages/api/src/app/services/indexing/steps/__init__.py
packages/api/src/app/services/indexing/steps/git_clone.py
packages/api/src/app/services/indexing/steps/index_run_steps.py
packages/api/src/app/services/indexing/types.py
packages/api/src/app/services/indexing/workflow.py
packages/api/src/app/services/llm_config/__init__.py
packages/api/src/app/services/pr_issue_comment/helpers.py
packages/api/src/app/services/pr_issue_comment/types.py
packages/api/src/app/services/review/errors.py
packages/api/src/app/services/review/helpers.py
packages/api/src/app/services/review/steps/__init__.py
packages/api/src/app/services/review/steps/invoke_agent.py
packages/api/src/app/services/review/steps/persist_comments.py
packages/api/src/app/services/review/steps/persist_summary.py
packages/api/src/app/services/review/steps/persist_usage.py
packages/api/src/app/services/review/steps/resolve_repo.py
packages/api/src/app/services/review/webhook.py
packages/api/src/app/services/review/workflow.py
packages/api/src/app/services/review/workflow_types.py
packages/api/src/app/services/search/service.py
packages/api/src/app/services/setup/_helpers.py
packages/api/src/app/services/setup/workflow.py
web/package.json
web/pnpm-lock.yaml
web/src/components/ThemeToggle.tsx
web/src/components/ui/input.tsx
web/src/lib/api.ts
web/src/routes/__root.tsx
web/src/routes/dashboard/_components/-indexed-repos-card.tsx
web/src/routes/dashboard/index.tsx
web/src/routes/dashboard/repositories/_components/-code-search.tsx
web/src/routes/dashboard/search/$owner/$name/route.tsx
web/src/routes/dashboard/settings/_components/-llm-config-card.tsx
web/src/routes/login.tsx

---

## Files Renamed

---


---
