# agent_v2/prompts — one function per agent prompt

System/user prompt builders for the planning agent, the per-file
review agents, and the summary synthesizer. No bare prompt
constants: wording is assembled from ctx scalars so tests can call
a builder and diff the text.

## Layout

- `shared.py` — blocks every agent uses: `COMMENT_BODY_FORMAT`
  (comment-body contract), `NO_FINDINGS_MARKER`, the
  `SEARCH_CODEGRAPH_TOOL_DESCRIPTION` verb ladder, `identityHeader`
  / `prMetaBlock` (identity + PR-intent blocks),
  `getReviewDiffDirPath`.
- `planning.py` — planning rubric (exploration budget, `submit_plan`
  contract) + `SUBMIT_PLAN_TOOL_DESCRIPTION`;
  `createPlanningSystemPrompt` / `createPlanningUserPrompt`.
- `file_review.py` — single-chunk review rubric (gutter anchors,
  findings-block contract); `createFileReviewSystemPrompt` /
  `createFileReviewUserPrompt`.
- `summary.py` — walkthrough synthesis rubric;
  `createSummarySystemPrompt` / `createSummaryUserPrompt`.

## Notes

- `service.py` owns agent assembly and imports from here; it holds
  no prompt wording itself. The invoke steps import the user
  builders directly.
