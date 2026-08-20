### packages/api/src/app/services/review/helpers.py

```diff

index 7bc10c2..f87df87 100644
--- a/packages/api/src/app/services/review/helpers.py
+++ b/packages/api/src/app/services/review/helpers.py
@@ -32,17 +32,16 @@ def get_repo_path(repo_name: str) -> str:
   33    33  def map_drafts_to_comment_rows(
   34    34      *,
   35    35      pr_id: str,
   36       -    review_id: str | None,
   37    36      commit_id: str,
   38    37      comments: Sequence[CodeCommentDraft],
   39    38  ) -> list[CodeComment]:
   40    39      """Translate :class:`CodeCommentDraft` objects into ORM rows.
   41    40  
   42    41      Each draft becomes a :class:`CodeComment` keyed to ``(pr_id,
   43       -    commit_id)`` with ``state=ACTIVE`` and the run's ``review_id``
   44       -    when one exists. The agent's severity / side strings are coerced
   45       -    into the corresponding enums; a bad value raises ``ValueError``
   46       -    here (this is a programmer error, not a pipeline failure mode).
         42 +    commit_id)`` with ``state=ACTIVE``. The agent's severity / side
         43 +    strings are coerced into the corresponding enums; a bad value raises
         44 +    ``ValueError`` here (this is a programmer error, not a pipeline
         45 +    failure mode).
   47    46      """
   48    47      rows: list[CodeComment] = []
   49    48      for draft in comments:
@@ -50,7 +49,6 @@ def map_drafts_to_comment_rows(
   51    50              CodeComment(
   52    51                  id=uuidToStr(),
   53    52                  pr_id=pr_id,
   54       -                review_id=review_id,
   55    53                  commit_id=commit_id,
   56    54                  file_name=draft.file_name,
   57    55                  comment=draft.comment,

```
