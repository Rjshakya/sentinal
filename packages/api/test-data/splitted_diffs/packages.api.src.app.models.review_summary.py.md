### packages/api/src/app/models/review_summary.py

```diff

index 78e59c5..49fb201 100644
--- a/packages/api/src/app/models/review_summary.py
+++ b/packages/api/src/app/models/review_summary.py
@@ -21,12 +21,6 @@ class ReviewSummary(SQLModel, table=True):
   22    22          sa_column_args=(ForeignKey("pullrequest.id", ondelete="CASCADE"),),
   23    23          nullable=False,
   24    24      )
   25       -    review_id: str | None = Field(
   26       -        default=None,
   27       -        sa_column_args=(ForeignKey("review.id", ondelete="CASCADE"),),
   28       -        sa_column_kwargs={"unique": True},
   29       -        nullable=True,
   30       -    )
   31    25      commit_id: str = Field(nullable=False)
   32    26      github_review_id: str | None = Field(default=None, nullable=True)
   33    27      summary: str = Field(nullable=False)

```
