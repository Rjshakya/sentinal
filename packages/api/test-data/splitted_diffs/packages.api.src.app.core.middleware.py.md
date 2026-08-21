### packages/api/src/app/core/middleware.py

```diff

index df02afe..9246aff 100644
--- a/packages/api/src/app/core/middleware.py
+++ b/packages/api/src/app/core/middleware.py
@@ -30,7 +30,6 @@ class AuthMiddleware(BaseHTTPMiddleware):
   31    31          "/api/users",
   32    32          "/api/llm_config",
   33    33          "/api/indexing",
   34       -        "/api/search",
   35    34      )
   36    35  
   37    36      BYPASS_PREFIXES: tuple[str, ...] = ("/api/github/setup",)

```
