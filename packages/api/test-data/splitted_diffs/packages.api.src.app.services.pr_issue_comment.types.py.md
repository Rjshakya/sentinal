### packages/api/src/app/services/pr_issue_comment/types.py

```diff

index 5a970b2..b7523c6 100644
--- a/packages/api/src/app/services/pr_issue_comment/types.py
+++ b/packages/api/src/app/services/pr_issue_comment/types.py
@@ -48,7 +48,6 @@ class IssueCommentTriggerInput(BaseModel):
   49    49      repo_owner: str
   50    50      repo_name: str
   51    51      gh_repo_id: int
   52       -    default_branch: str | None = None
   53    52      pr_number: int
   54    53      pr_author_login: str
   55    54      commenter_login: str

```
