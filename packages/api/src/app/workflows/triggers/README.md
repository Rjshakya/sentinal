# workflows/triggers — webhook-edge adapters

Translate verified GitHub deliveries into durable dispatches.
Pure adaptation: validate → dispatch. No DB, no GitHub fetch, no LLM
calls, no sandbox access here — all ctx resolution runs as
checkpointed steps inside the durable handlers.

## Layout

- `invoke.py` — `handlePullRequestOpened` (`pull_request.opened`)
  and `handleIssueCommentCreated` (`issue_comment.created`
  mentioning `@<app_slug> review`). Both build a deterministic
  execution name and Invoke their durable function.
- `opened_payload.py` — pure `pull_request` projection onto
  `PRPayload` (`None` when malformed).
- `comment_payload.py` — pure comment gates: `validateCommentPayload`,
  `classifyComment` (`shouldReviewComment`, author/association
  checks), `effectiveDiffBase` — the incremental re-review
  base (last reviewed head) when the head moved since the latest
  successful run — and `isHeadAlreadyPosted` — the same-head skip
  when that run already posted (same head + `githubReviewId` set).
- `repair.py` — `triggerRepairAfterReview`: follow-up dispatch of
  the repair durable when the review post returns `posted=False`.
- `types.py` — `PRPayload`, `CommentTriggerInput`,
  `ClassifyCommentResult`, `LastReviewSnapshot`,
  `ReviewTriggerAck`.

## Notes

- Invoke infra failures raise so GitHub redelivers; business skips
  return an ack with `skip_reason`.
