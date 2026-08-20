### packages/api/src/app/services/setup/_helpers.py

```diff

index c7d22f5..ad99383 100644
--- a/packages/api/src/app/services/setup/_helpers.py
+++ b/packages/api/src/app/services/setup/_helpers.py
@@ -12,6 +12,7 @@ from app.services.setup.errors import (
   13    13      GitCloneTransientError,
   14    14  )
   15    15  
         16 +
   16    17  __all__ = [
   17    18      "build_authenticated_clone_url",
   18    19      "check_git_clone_result",
@@ -19,7 +20,9 @@ __all__ = [
   20    21  ]
   21    22  
   22    23  
   23       -def build_authenticated_clone_url(*, install_token: str, owner: str, name: str) -> str:
         24 +def build_authenticated_clone_url(
         25 +    *, install_token: str, owner: str, name: str
         26 +) -> str:
   24    27      """Build the authenticated HTTPS clone URL.
   25    28  
   26    29      GitHub's recommended way to authenticate ``git`` operations from

```
