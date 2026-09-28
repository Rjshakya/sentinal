# workflows/triggers — webhook-edge adapters

Translate verified GitHub deliveries into workflow dispatches.
Pure adaptation: validate → resolve user/repo → gate on config →
dispatch. No LLM calls, no sandbox access here.

## Layout

- `review.py` — `handlePullRequestOpened` (`pull_request.opened`)
  and `handleIssueCommentCreated` (`issue_comment.created`
  mentioning `@<app_slug> review`). Both resolve the run
  environment and dispatch `reviewWorkflowV2` via `dispatchReview`.
- `comment.py` — pure comment gates: `validateCommentPayload`,
  `classifyComment` (`shouldReviewComment`, author/association
  checks), and `effectiveDiffBase` — the incremental re-review
  base (last reviewed head) when the head moved since the latest
  successful run.
- `repair.py` — `triggerRepairAfterReview`: follow-up dispatch of
  `repairAndPublishReviewWorkflow` on the comment-mention path.
- `_common.py` — shared resolvers: run LLM ctx
  (`resolveLlmCtx`), sandbox ctx (`buildSandboxCtx`), and
  installation → user/repo rows (`getUserIdFromInstallation`,
  `getRepoRecord`).
- `types.py` — `PRPayload`, `CommentTriggerInput`,
  `ClassifyCommentResult`, `LastReviewSnapshot`,
  `ReviewTriggerAck`.

## Notes

- Both review adapters dispatch under the same deterministic id;
  the comment path adds a best-effort 👀 reaction first.
