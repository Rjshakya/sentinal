### packages/api/src/app/routers/search.py

```diff

index 0e4e51a..f660167 100644
--- a/packages/api/src/app/routers/search.py
+++ b/packages/api/src/app/routers/search.py
@@ -40,7 +40,7 @@ router = APIRouter(prefix="/search", tags=["search"])
   41    41  
   42    42  
   43    43  @router.post(
   44       -    "/",
         44 +    "",
   45    45      status_code=status.HTTP_200_OK,
   46    46      response_model=CodeSearchResponse,
   47    47  )

```
