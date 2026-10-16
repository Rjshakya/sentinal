"""PR URL resolver: parse the URL then fetch PR facts from GitHub.

Public PRs need no token. An optional token raises the rate limit.
All failures return PrResolverError values, never raised exceptions.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
from typing import Any

from datasetLoader.types import PrContext, PrResolverError, PrUrlParts
from pydantic import BaseModel, ConfigDict, Field

prUrlPattern = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<number>\d+)(?:[/?#].*)?$"
)

githubApiBase = "https://api.github.com"
requestTimeoutSeconds = 30


class PrApiPayload(BaseModel):
    """Validated subset of the GitHub pull-request API response."""

    model_config = ConfigDict(frozen=True)

    baseSha: str = Field(min_length=7)
    headSha: str = Field(min_length=7)
    baseBranch: str = Field(min_length=1)
    headBranch: str = Field(min_length=1)
    author: str = Field(default="")
    fetchedTitle: str = Field(default="")
    fetchedBody: str = Field(default="")
    cloneUrl: str = Field(min_length=1)


def normalizeRepoName(rawRepo: str) -> str:
    repoName = rawRepo.strip()
    if repoName.endswith(".git"):
        repoName = repoName[: -len(".git")]
    return repoName


def parsePrUrlParts(prUrl: str) -> PrUrlParts | PrResolverError:
    cleanedUrl = prUrl.strip()
    match = prUrlPattern.match(cleanedUrl)
    if match is None:
        return PrResolverError(
            message=f"invalid GitHub PR URL: {prUrl!r}. Expected https://github.com/<owner>/<repo>/pull/<number>",
            prUrl=prUrl,
            retryable=False,
        )
    owner = match.group("owner").strip()
    repo = normalizeRepoName(match.group("repo"))
    numberText = match.group("number")
    if not owner or not repo:
        return PrResolverError(
            message=f"invalid GitHub PR URL (empty owner or repo): {prUrl!r}",
            prUrl=prUrl,
            retryable=False,
        )
    try:
        prNumber = int(numberText)
    except ValueError:
        return PrResolverError(
            message=f"invalid PR number in URL: {prUrl!r}",
            prUrl=prUrl,
            retryable=False,
        )
    if prNumber < 1:
        return PrResolverError(
            message=f"PR number must be >= 1 in URL: {prUrl!r}",
            prUrl=prUrl,
            retryable=False,
        )
    return PrUrlParts(owner=owner, repo=repo, prNumber=prNumber)


def buildPrApiUrl(urlParts: PrUrlParts) -> str:
    return f"{githubApiBase}/repos/{urlParts.owner}/{urlParts.repo}/pulls/{urlParts.prNumber}"


def buildApiHeaders(githubToken: str | None) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "sentinel-evals",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    cleanedToken = (githubToken or "").strip()
    if cleanedToken:
        headers["Authorization"] = f"Bearer {cleanedToken}"
    return headers


def extractTextField(payload: dict[str, Any], fieldName: str) -> str:
    value = payload.get(fieldName)
    if isinstance(value, str):
        return value
    return ""


def extractNestedSha(branchPayload: object) -> str:
    if not isinstance(branchPayload, dict):
        return ""
    shaValue = branchPayload.get("sha")
    return shaValue if isinstance(shaValue, str) else ""


def extractNestedRef(branchPayload: object) -> str:
    if not isinstance(branchPayload, dict):
        return ""
    refValue = branchPayload.get("ref")
    return refValue if isinstance(refValue, str) else ""


def parsePrApiPayload(rawPayload: object, urlParts: PrUrlParts) -> PrApiPayload | PrResolverError:
    if not isinstance(rawPayload, dict):
        return PrResolverError(
            message=f"unexpected GitHub API shape for {urlParts.owner}/{urlParts.repo}#{urlParts.prNumber}",
            prUrl=f"https://github.com/{urlParts.owner}/{urlParts.repo}/pull/{urlParts.prNumber}",
            retryable=False,
        )
    basePayload = rawPayload.get("base")
    headPayload = rawPayload.get("head")
    baseSha = extractNestedSha(basePayload)
    headSha = extractNestedSha(headPayload)
    baseBranch = extractNestedRef(basePayload)
    headBranch = extractNestedRef(headPayload)
    if not baseSha or not headSha or not baseBranch or not headBranch:
        return PrResolverError(
            message=f"GitHub API response misses base/head SHAs for {urlParts.owner}/{urlParts.repo}#{urlParts.prNumber}",
            prUrl=f"https://github.com/{urlParts.owner}/{urlParts.repo}/pull/{urlParts.prNumber}",
            retryable=True,
        )
    userPayload = rawPayload.get("user")
    author = ""
    if isinstance(userPayload, dict):
        loginValue = userPayload.get("login")
        author = loginValue if isinstance(loginValue, str) else ""
    headRepoUrl = ""
    if isinstance(headPayload, dict):
        headRepo = headPayload.get("repo")
        if isinstance(headRepo, dict):
            cloneValue = headRepo.get("clone_url")
            if isinstance(cloneValue, str) and cloneValue:
                headRepoUrl = cloneValue
    cloneUrl = headRepoUrl or f"https://github.com/{urlParts.owner}/{urlParts.repo}.git"
    try:
        return PrApiPayload(
            baseSha=baseSha,
            headSha=headSha,
            baseBranch=baseBranch,
            headBranch=headBranch,
            author=author,
            fetchedTitle=extractTextField(rawPayload, "title"),
            fetchedBody=extractTextField(rawPayload, "body"),
            cloneUrl=cloneUrl,
        )
    except Exception as caughtError:
        return PrResolverError(
            message=f"invalid GitHub API payload: {type(caughtError).__name__}: {caughtError}",
            prUrl=f"https://github.com/{urlParts.owner}/{urlParts.repo}/pull/{urlParts.prNumber}",
            retryable=False,
        )


def requestApiJson(apiUrl: str, headers: dict[str, str]) -> object | PrResolverError:
    request = urllib.request.Request(apiUrl, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=requestTimeoutSeconds) as response:
            statusCode: int = int(getattr(response, "status", 200))
            if statusCode == 404:
                return PrResolverError(
                    message=f"PR not found (404): {apiUrl}",
                    prUrl=apiUrl,
                    retryable=False,
                )
            if statusCode == 401 or statusCode == 403:
                return PrResolverError(
                    message=f"GitHub API refused access ({statusCode}): {apiUrl}. Rate limit or bad token.",
                    prUrl=apiUrl,
                    retryable=statusCode == 403,
                )
            if statusCode < 200 or statusCode >= 300:
                return PrResolverError(
                    message=f"GitHub API returned {statusCode}: {apiUrl}",
                    prUrl=apiUrl,
                    retryable=statusCode >= 500,
                )
            rawBody = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as caughtError:
        if caughtError.code == 404:
            return PrResolverError(
                message=f"PR not found (404): {apiUrl}",
                prUrl=apiUrl,
                retryable=False,
            )
        if caughtError.code == 401:
            return PrResolverError(
                message=f"GitHub API unauthorized (401): {apiUrl}",
                prUrl=apiUrl,
                retryable=False,
            )
        if caughtError.code == 403:
            return PrResolverError(
                message=f"GitHub API rate limited or forbidden (403): {apiUrl}",
                prUrl=apiUrl,
                retryable=True,
            )
        return PrResolverError(
            message=f"GitHub API HTTP {caughtError.code}: {apiUrl}",
            prUrl=apiUrl,
            retryable=caughtError.code >= 500,
        )
    except Exception as caughtError:
        return PrResolverError(
            message=f"GitHub request failed: {type(caughtError).__name__}: {caughtError}",
            prUrl=apiUrl,
            retryable=True,
        )
    try:
        return json.loads(rawBody)
    except json.JSONDecodeError as caughtError:
        return PrResolverError(
            message=f"invalid GitHub API JSON: {caughtError}",
            prUrl=apiUrl,
            retryable=True,
        )


async def fetchResolvedPrContext(
    urlParts: PrUrlParts, githubToken: str | None = None
) -> PrContext | PrResolverError:
    apiUrl = buildPrApiUrl(urlParts)
    headers = buildApiHeaders(githubToken)
    rawPayload = await asyncio.to_thread(requestApiJson, apiUrl, headers)
    if isinstance(rawPayload, PrResolverError):
        return rawPayload
    parsedPayload = parsePrApiPayload(rawPayload, urlParts)
    if isinstance(parsedPayload, PrResolverError):
        return parsedPayload
    return PrContext(
        owner=urlParts.owner,
        repoName=urlParts.repo,
        prNumber=urlParts.prNumber,
        repoUrl=f"https://github.com/{urlParts.owner}/{urlParts.repo}",
        cloneUrl=parsedPayload.cloneUrl,
        baseSha=parsedPayload.baseSha,
        headSha=parsedPayload.headSha,
        baseBranch=parsedPayload.baseBranch,
        headBranch=parsedPayload.headBranch,
        author=parsedPayload.author,
        fetchedTitle=parsedPayload.fetchedTitle,
        fetchedBody=parsedPayload.fetchedBody,
    )


async def resolvePrUrl(prUrl: str, githubToken: str | None = None) -> PrContext | PrResolverError:
    """Parse a PR URL then fetch its context from the GitHub API."""
    urlParts = parsePrUrlParts(prUrl)
    if isinstance(urlParts, PrResolverError):
        return urlParts
    return await fetchResolvedPrContext(urlParts, githubToken)


__all__ = [
    "fetchResolvedPrContext",
    "parsePrUrlParts",
    "resolvePrUrl",
]
