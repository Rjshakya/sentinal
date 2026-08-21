### packages/api/src/app/models/code_comment.py

```diff

index e7c45b9..5c1cc31 100644
--- a/packages/api/src/app/models/code_comment.py
+++ b/packages/api/src/app/models/code_comment.py
@@ -21,12 +21,6 @@ class CodeComment(SQLModel, table=True):
   22    22          sa_column_args=(ForeignKey("pullrequest.id", ondelete="CASCADE"),),
   23    23          nullable=False,
   24    24      )
   25       -    review_id: str | None = Field(
   26       -        default=None,
   27       -        sa_column_args=(ForeignKey("review.id", ondelete="CASCADE"),),
   28       -        nullable=True,
   29       -        index=True,
   30       -    )
   31    25      commit_id: str = Field(nullable=False)
   32    26      github_comment_id: str | None = Field(default=None, nullable=True)
   33    27      file_name: str = Field(nullable=False)

```
