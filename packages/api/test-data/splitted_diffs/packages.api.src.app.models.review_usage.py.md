### packages/api/src/app/models/review_usage.py

```diff

index 1978efc..2018fb6 100644
--- a/packages/api/src/app/models/review_usage.py
+++ b/packages/api/src/app/models/review_usage.py
@@ -10,11 +10,6 @@ The ``input_token_details`` JSONB column carries the cache_read /
   11    11  cache_creation breakdown (``{"cache_read": int | None,
   12    12  "cache_creation": int | None}``) as reported by the provider; it is
   13    13  optional because not every provider surfaces cache metadata.
   14       -
   15       -The ``llm_model_id`` / ``llm_provider`` / ``llm_base_url`` columns
   16       -snapshot the resolved :class:`app.core.llm.LLMConfig` at run time so
   17       -per-model cost and quality analytics never depend on a config row
   18       -that may later be edited or deleted. All three are nullable.
   19    14  """
   20    15  
   21    16  from __future__ import annotations
@@ -49,12 +44,6 @@ class ReviewUsage(SQLModel, table=True):
   50    45          sa_column_args=(ForeignKey("reviewsummary.id", ondelete="CASCADE"),),
   51    46          nullable=True,
   52    47      )
   53       -    review_id: Optional[str] = Field(
   54       -        default=None,
   55       -        sa_column_args=(ForeignKey("review.id", ondelete="CASCADE"),),
   56       -        nullable=True,
   57       -        index=True,
   58       -    )
   59    48  
   60    49      review_status: ReviewRunStatus = Field(
   61    50          default=ReviewRunStatus.SUCCESS,
@@ -68,10 +57,6 @@ class ReviewUsage(SQLModel, table=True):
   69    58          sa_column=Column(JSONB, nullable=True),
   70    59      )
   71    60  
   72       -    llm_model_id: Optional[str] = Field(default=None, nullable=True)
   73       -    llm_provider: Optional[str] = Field(default=None, nullable=True)
   74       -    llm_base_url: Optional[str] = Field(default=None, nullable=True)
   75       -
   76    61      created_at: datetime = Field(
   77    62          default_factory=lambda: datetime.now(UTC),
   78    63          sa_column=Column(

```
