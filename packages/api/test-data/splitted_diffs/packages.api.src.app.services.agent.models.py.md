### packages/api/src/app/services/agent/models.py

```diff

index f8cffec..f299e0c 100644
--- a/packages/api/src/app/services/agent/models.py
+++ b/packages/api/src/app/services/agent/models.py
@@ -49,8 +49,8 @@ class CodeCommentDraft(BaseModel):
   50    50  
   51    51  class ReviewComments(BaseModel):
   52    52      List: list[CodeCommentDraft] = Field(
   53       -        description="All inline comments the agent wants to post, mixed "
   54       -        "severities. Empty list is valid — it means 'looks good, no findings'.",
         53 +        description="List of CodeCommentDraft with mixed severities, This "
         54 +        "Output is Expected From The Comments Agent"
   55    55      )
   56    56  
   57    57  

```
