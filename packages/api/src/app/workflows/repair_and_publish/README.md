# repair_and_publish — repair + publish follow-up pipeline

Recovers an unpublished review draft: checks one exists, rebuilds
a sandbox + clone, strips the tree down to the diff, runs the
repair agent (which publishes via a capped tool), and saves the
posted ids back to the local rows.

## Layout

- `workflow.py` — `repairAndPublishReviewWorkflow` (check →
  sandbox/clone/diff → delete → split → agent publish → save)
  plus `dispatchRepairAndPublishWorkflow`.
- `types.py` — `RepairAndPublishWorkflowCtx/Input`, `CommentRow`,
  `UnpublishedReview`, `PublishedReview`,
  `RepairAndPublishResult/Reason`.
- `helpers.py` — workflow-id builder, repair prompts, draft →
  GitHub-comment conversion (`toGithubComments`).
- `errors.py` — value-errors per phase plus step exceptions and
  `shouldRetry`.
- `steps/` — the four I/O boundaries. See its README.

## Notes

- Dispatched only from `triggers/repair.py` (comment-mention
  path), never from `pull_request.opened`. Reuses the review_v2
  sandbox steps for parity.
