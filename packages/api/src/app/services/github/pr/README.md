# github/pr — pull-request reads and review posting

All PR traffic against the GitHub API: state and listings for the
dashboard, review/comment posting for the pipeline.

## Layout

- `service.py` — entry points (see API). `types.py` — `PRCtx`,
  `PRState`, `PRReviewDraft` / `PRCommentDraft` (post payloads),
  list-item projections, `PRVerdict`, `ReactionContent`.
  `errors.py` — `GitHubPRError`.

## API

- `createPRCtx(userId, installationId, owner, repo, prNumber)` —
  ctx factory.
- Reads: `getPrState`, `listPulls`, `listCommits`, `listFiles`,
  `listIssueComments`, `listReviewComments`, `listReviews`.
- Writes: `postReview(ctx, draft)` (inline review with line
  comments), `postComment(ctx, body)` (issue-thread comment),
  `addReaction(ctx, …)` (e.g. the 👀 ack on trigger comments).

## Notes

- Used by `routers/pulls.py` (reads), the comment trigger
  (`addReaction`, `getPrState`), and the review post step
  (`postReviewStep`). Posting failures are values — the pipeline
  decides (retry on 429/5xx, accept `posted=False` on terminal 4xx).
