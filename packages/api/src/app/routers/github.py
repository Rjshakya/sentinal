"""GitHub routes: list the authenticated user's repos via GitHubKit."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.github import github_client_for

router = APIRouter(prefix="/github", tags=["github"])


class RepoOut(BaseModel):
    id: int
    name: str
    full_name: str
    owner: str | None
    private: bool
    description: str | None
    default_branch: str
    html_url: str
    stargazers_count: int
    language: str | None
    updated_at: datetime | None


@router.get("/repos", response_model=list[RepoOut])
async def list_repos(request: Request) -> list[RepoOut]:
    try:
        gh = await github_client_for(request.state.user_id)
        resp = await gh.rest.repos.async_list_for_authenticated_user(
            per_page=30,
            sort="updated",
        )
        repos = resp.parsed_data or []

        return [
            RepoOut(
                id=r.id,
                name=r.name,
                full_name=r.full_name,
                owner=r.owner.login if r.owner is not None else "",
                private=r.private,
                description=r.description,
                default_branch=r.default_branch,
                html_url=r.html_url,
                stargazers_count=r.stargazers_count,
                language=r.language,
                updated_at=r.updated_at,
            )
            for r in repos
        ]

    except Exception as e:
        print(f"github list_repos: {e}")
        raise HTTPException(status_code=502, detail="Failed to list GitHub repos")
