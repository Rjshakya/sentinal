# repair_and_publish/steps — the four I/O boundaries

## Steps

- `check_unpublished.py` — `loadUnpublishedReview` /
  `checkUnpublishedReviewExist`: skip (`None`) when no unpublished
  draft exists for the PR.
- `delete_repo.py` — best-effort `rm -rf` of the clone, keeping
  only the diff dir.
- `repair_and_publish.py` — deep-agent harness with the atomic
  `publish_to_github` tool (max 3 calls):
  `repairAndPublish(ToGithub)`, `buildPublishTool`.
- `save_published.py` — write `github_review_id` back, keep posted
  rows, delete leftover unpublished rows
  (`savePublishedReviewStep`).

## Notes

- `__init__.py` is the step hub; sandbox create/clone steps are
  reused from `review_v2` rather than duplicated.
