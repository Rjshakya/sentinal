### packages/api/src/app/routers/users.py

```diff

index 28fd8c8..fb2aed3 100644
--- a/packages/api/src/app/routers/users.py
+++ b/packages/api/src/app/routers/users.py
@@ -8,6 +8,7 @@ All endpoints are user-scoped: they read ``request.state.user_id`` (set by
    9     9  from __future__ import annotations
   10    10  
   11    11  from datetime import datetime
         12 +from typing import Optional
   12    13  
   13    14  from fastapi import APIRouter, Depends, HTTPException, Query, Request
   14    15  from pydantic import BaseModel
@@ -28,13 +29,12 @@ router = APIRouter(prefix="/users", tags=["users"])
   29    30  class UserRepoOut(BaseModel):
   30    31      id: str
   31    32      user_id: str
   32       -    org_id: str | None = None
         33 +    org_id: Optional[str] = None
   33    34      repo_name: str
   34    35      repo_owner: str
   35       -    url: str | None = None
         36 +    url: Optional[str] = None
   36    37      private: bool
   37       -    default_branch: str | None = None
   38       -    is_indexed: bool
         38 +    default_branch: Optional[str] = None
   39    39      created_at: datetime
   40    40      updated_at: datetime
   41    41  
@@ -58,18 +58,10 @@ async def list_my_repos(
   59    59      session: AsyncSession = Depends(get_session),
   60    60      limit: int = Query(100, ge=1, le=100),
   61    61  ) -> list[UserRepoOut]:
   62       -    """List the caller's indexed repositories.
   63       -
   64       -    Only repos with ``is_indexed = True`` are returned — the endpoint is
   65       -    the source of truth for the dashboard's "indexed repositories" list.
   66       -    """
   67    62      try:
   68    63          stmt = (
   69    64              select(Repo)
   70       -            .where(
   71       -                Repo.user_id == request.state.user_id,
   72       -                Repo.is_indexed == True,
   73       -            )
         65 +            .where(Repo.user_id == request.state.user_id)
   74    66              .order_by(desc(Repo.updated_at))
   75    67              .limit(limit)
   76    68          )
@@ -86,7 +78,6 @@ async def list_my_repos(
   87    79                  url=r.url,
   88    80                  private=r.private,
   89    81                  default_branch=r.default_branch,
   90       -                is_indexed=r.is_indexed or False,
   91    82                  created_at=r.created_at,
   92    83                  updated_at=r.updated_at,
   93    84              )

```
