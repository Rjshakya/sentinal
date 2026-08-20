### packages/api/src/app/services/review/workflow_types.py

```diff

index 97bc952..f3081d0 100644
--- a/packages/api/src/app/services/review/workflow_types.py
+++ b/packages/api/src/app/services/review/workflow_types.py
@@ -41,7 +41,6 @@ class ReviewWorkflowInput(BaseModel):
   42    42      pr_id: int
   43    43      pr_number: int
   44    44      branch: str
   45       -    default_branch: str | None = None
   46    45      base_sha: str
   47    46      head_sha: str
   48    47      head_branch: str
@@ -49,7 +48,6 @@ class ReviewWorkflowInput(BaseModel):
   50    49      body: str
   51    50      title: str
   52    51      status: PRStatus
   53       -    trigger: str = "opened"
   54    52      llm_config: LLMConfig
   55    53      post_to_github: bool
   56    54      github_installation_id: int | None = None
@@ -99,7 +97,6 @@ class RepoSnapshot(BaseModel):
  100    98      id: str
  101    99      repo_name: str
  102   100      repo_owner: str
  103       -    default_branch: str | None = None
  104   101  
  105   102  
  106   103  class ResolvedSandbox(BaseModel):

```
