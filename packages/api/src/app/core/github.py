"""Thin GitHubKit factory: mints a WorkOS-vended GitHub token, returns a typed client."""

from __future__ import annotations

from githubkit import GitHub

from app.core.workos import get_github_access_token


async def github_client_for(user_id: str) -> GitHub:
    token = await get_github_access_token(user_id)
    return GitHub(token)
