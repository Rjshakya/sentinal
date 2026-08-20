### packages/api/src/app/services/review/steps/persist_summary.py

```diff

index ece172f..ac0f2ed 100644
--- a/packages/api/src/app/services/review/steps/persist_summary.py
+++ b/packages/api/src/app/services/review/steps/persist_summary.py
@@ -28,14 +28,12 @@ async def persist_review_summary(
   29    29      session: AsyncSession,
   30    30      *,
   31    31      pr_id: str,
   32       -    review_id: str | None,
   33    32      commit_id: str,
   34    33      result: ReviewResult,
   35    34  ) -> ReviewSummary:
   36    35      """Insert a single :class:`ReviewSummary` row."""
   37    36      summary = ReviewSummary(
   38    37          pr_id=pr_id,
   39       -        review_id=review_id,
   40    38          commit_id=commit_id,
   41    39          summary=result.summary,
   42    40          verdict=ReviewVerdict(result.verdict),
@@ -56,7 +54,6 @@ async def persist_review_summary(
   57    55  async def persist_review_summary_tx(
   58    56      *,
   59    57      pr_id: str,
   60       -    review_id: str | None,
   61    58      commit_id: str,
   62    59      result: ReviewResult,
   63    60  ) -> UUID:
@@ -69,7 +66,6 @@ async def persist_review_summary_tx(
   70    67      summary = await persist_review_summary(
   71    68          session,
   72    69          pr_id=pr_id,
   73       -        review_id=review_id,
   74    70          commit_id=commit_id,
   75    71          result=result,
   76    72      )

```
