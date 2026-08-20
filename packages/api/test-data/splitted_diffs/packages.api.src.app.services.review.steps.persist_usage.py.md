### packages/api/src/app/services/review/steps/persist_usage.py

```diff

index b892006..409eaa7 100644
--- a/packages/api/src/app/services/review/steps/persist_usage.py
+++ b/packages/api/src/app/services/review/steps/persist_usage.py
@@ -71,7 +71,6 @@ async def persist_review_usage(
   72    72      session: AsyncSession,
   73    73      *,
   74    74      pr_id: str,
   75       -    review_id: str | None,
   76    75      user_id: str,
   77    76      pr_number: int,
   78    77      repo_id: str,
@@ -81,14 +80,10 @@ async def persist_review_usage(
   82    81      output_tokens: int,
   83    82      total_tokens: int,
   84    83      input_token_details: dict[str, int | None] | None,
   85       -    llm_model_id: str | None,
   86       -    llm_provider: str | None,
   87       -    llm_base_url: str | None,
   88    84  ) -> ReviewUsage:
   89    85      """Insert a single :class:`ReviewUsage` row."""
   90    86      row = ReviewUsage(
   91    87          pr_id=pr_id,
   92       -        review_id=review_id,
   93    88          user_id=user_id,
   94    89          pr_number=pr_number,
   95    90          repo_id=repo_id,
@@ -98,9 +93,6 @@ async def persist_review_usage(
   99    94          output_tokens=output_tokens,
  100    95          total_tokens=total_tokens,
  101    96          input_token_details=input_token_details,
  102       -        llm_model_id=llm_model_id,
  103       -        llm_provider=llm_provider,
  104       -        llm_base_url=llm_base_url,
  105    97      )
  106    98      session.add(row)
  107    99      await session.flush()
@@ -122,7 +114,6 @@ async def persist_review_usage(
  123   115  async def persist_review_usage_tx(
  124   116      *,
  125   117      pr_id: str,
  126       -    review_id: str | None,
  127   118      user_id: str,
  128   119      pr_number: int,
  129   120      repo_id: str,
@@ -132,9 +123,6 @@ async def persist_review_usage_tx(
  133   124      output_tokens: int,
  134   125      total_tokens: int,
  135   126      input_token_details: dict[str, int | None] | None,
  136       -    llm_model_id: str | None,
  137       -    llm_provider: str | None,
  138       -    llm_base_url: str | None,
  139   127  ) -> str:
  140   128      """Durable DBOS transaction: persist the review usage row.
  141   129  
@@ -146,7 +134,6 @@ async def persist_review_usage_tx(
  147   135      row = await persist_review_usage(
  148   136          session,
  149   137          pr_id=pr_id,
  150       -        review_id=review_id,
  151   138          user_id=user_id,
  152   139          pr_number=pr_number,
  153   140          repo_id=repo_id,
@@ -156,9 +143,6 @@ async def persist_review_usage_tx(
  157   144          output_tokens=output_tokens,
  158   145          total_tokens=total_tokens,
  159   146          input_token_details=input_token_details,
  160       -        llm_model_id=llm_model_id,
  161       -        llm_provider=llm_provider,
  162       -        llm_base_url=llm_base_url,
  163   147      )
  164   148      return str(row.id)
  165   149  

```
