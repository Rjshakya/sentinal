### packages/api/src/app/services/review/steps/persist_comments.py

```diff

index 46475d9..fc692d8 100644
--- a/packages/api/src/app/services/review/steps/persist_comments.py
+++ b/packages/api/src/app/services/review/steps/persist_comments.py
@@ -29,13 +29,12 @@ async def persist_code_comments(
   30    30      session: AsyncSession,
   31    31      *,
   32    32      pr_id: str,
   33       -    review_id: str | None,
   34    33      commit_id: str,
   35    34      comments: Sequence[CodeCommentDraft],
   36    35  ) -> list[CodeComment]:
   37    36      """Insert one :class:`CodeComment` row per draft finding."""
   38    37      rows = map_drafts_to_comment_rows(
   39       -        pr_id=pr_id, review_id=review_id, commit_id=commit_id, comments=comments
         38 +        pr_id=pr_id, commit_id=commit_id, comments=comments
   40    39      )
   41    40  
   42    41      if not rows:
@@ -60,7 +59,6 @@ async def persist_code_comments(
   61    60  async def persist_code_comments_tx(
   62    61      *,
   63    62      pr_id: str,
   64       -    review_id: str | None,
   65    63      commit_id: str,
   66    64      comments: list[dict[str, Any]],
   67    65  ) -> list[str]:
@@ -73,9 +71,7 @@ async def persist_code_comments_tx(
   74    72      """
   75    73      session = dbos_datasource.sql_session()
   76    74      drafts = [CodeCommentDraft.model_validate(c) for c in comments]
   77       -    rows = map_drafts_to_comment_rows(
   78       -        pr_id=pr_id, review_id=review_id, commit_id=commit_id, comments=drafts
   79       -    )
         75 +    rows = map_drafts_to_comment_rows(pr_id=pr_id, commit_id=commit_id, comments=drafts)
   80    76      if not rows:
   81    77          return []
   82    78      session.add_all(rows)

```
