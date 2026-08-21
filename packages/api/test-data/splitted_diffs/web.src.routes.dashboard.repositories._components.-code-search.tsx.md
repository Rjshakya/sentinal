### web/src/routes/dashboard/repositories/_components/-code-search.tsx

```diff

index 5736ed5..6ce68fd 100644
--- a/web/src/routes/dashboard/repositories/_components/-code-search.tsx
+++ b/web/src/routes/dashboard/repositories/_components/-code-search.tsx
@@ -41,8 +41,8 @@ export function CodeSearch({ repos }: Props) {
   42    42      if (!selectedRepo || !canSearch) return;
   43    43      search.mutate(
   44    44        {
   45       -        owner: selectedRepo.repo_owner,
   46       -        repo: selectedRepo.repo_name,
         45 +        repo_id: selectedRepo.id,
         46 +        repo_name: selectedRepo.repo_name,
   47    47          query: query.trim(),
   48    48        },
   49    49        {
@@ -114,7 +114,7 @@ export function CodeSearch({ repos }: Props) {
  115   115            <SearchResults
  116   116              results={sortedResults}
  117   117              query={search.data.query ?? query}
  118       -            repoName={search.data.repo ?? selectedRepo?.repo_name ?? ""}
        118 +            repoName={search.data.repo_name ?? selectedRepo?.repo_name ?? ""}
  119   119            />
  120   120          )}
  121   121          {!search.data && !search.isPending && !search.isError && (

```
