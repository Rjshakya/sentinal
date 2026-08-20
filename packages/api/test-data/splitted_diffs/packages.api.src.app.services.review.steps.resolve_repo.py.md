### packages/api/src/app/services/review/steps/resolve_repo.py

```diff

index 17c2afd..5a9ddd8 100644
--- a/packages/api/src/app/services/review/steps/resolve_repo.py
+++ b/packages/api/src/app/services/review/steps/resolve_repo.py
@@ -66,7 +66,6 @@ async def resolve_repo_tx(gh_repo_id: int) -> RepoSnapshot:
   67    67          id=repo.id,
   68    68          repo_name=repo.repo_name,
   69    69          repo_owner=repo.repo_owner,
   70       -        default_branch=repo.default_branch,
   71    70      )
   72    71  
   73    72  

```
