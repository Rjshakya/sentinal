"""Dataset loader contract: PR entries with golden comments.

Dataset shape is a JSON list:
[{"title": ..., "pr_url": ..., "description": ..., "comments": [...] }]
Each golden comment holds only a comment body plus a severity label.
PR facts (owner, SHAs, branches) come from the PR URL via the resolver.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

GoldenSeverity = Literal["P1_CRITICAL", "P2_WARNING", "P3_NITPICK"]


class GoldenComment(BaseModel):
    """One ground-truth comment. Body plus severity only, no file or line."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    body: str = Field(
        min_length=1,
        validation_alias=AliasChoices("body", "comment", "commentBody", "text"),
        description="Golden comment text describing the underlying issue.",
    )
    severity: GoldenSeverity = Field(
        validation_alias=AliasChoices("severity", "severityLabel", "label"),
        description="Severity label for the golden comment.",
    )


class DatasetEntry(BaseModel):
    """One dataset row: PR identity plus golden comments."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    title: str = Field(min_length=1, description="PR title from the dataset.")
    prUrl: str = Field(
        min_length=1,
        validation_alias=AliasChoices("prUrl", "pr_url", "url"),
        serialization_alias="pr_url",
        description="Public GitHub PR URL, e.g. https://github.com/owner/repo/pull/123.",
    )
    description: str = Field(
        default="",
        validation_alias=AliasChoices("description", "body", "prBody"),
        description="PR description from the dataset.",
    )
    comments: list[GoldenComment] = Field(
        default_factory=list,
        description="Golden comments for this PR.",
    )


class PrUrlParts(BaseModel):
    """Parsed PR URL: owner, repo, and PR number."""

    model_config = ConfigDict(frozen=True)

    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    prNumber: int = Field(ge=1)


class PrContext(BaseModel):
    """PR facts fetched from GitHub for one PR URL."""

    model_config = ConfigDict(frozen=True)

    owner: str = Field(min_length=1)
    repoName: str = Field(min_length=1)
    prNumber: int = Field(ge=1)
    repoUrl: str = Field(min_length=1)
    cloneUrl: str = Field(min_length=1)
    baseSha: str = Field(min_length=7, max_length=64)
    headSha: str = Field(min_length=7, max_length=64)
    baseBranch: str = Field(min_length=1)
    headBranch: str = Field(min_length=1)
    author: str = Field(default="")
    fetchedTitle: str = Field(default="")
    fetchedBody: str = Field(default="")


class DatasetLoaderError(BaseModel):
    """Loader failure, returned as a value (never raised)."""

    model_config = ConfigDict(frozen=True)

    message: str
    path: str | None = None

    def __str__(self) -> str:
        return self.message


class PrResolverError(BaseModel):
    """PR URL parse or GitHub fetch failure, returned as a value."""

    model_config = ConfigDict(frozen=True)

    message: str
    prUrl: str = Field(default="")
    retryable: bool = Field(default=False)

    def __str__(self) -> str:
        return self.message


__all__ = [
    "DatasetEntry",
    "DatasetLoaderError",
    "GoldenComment",
    "GoldenSeverity",
    "PrContext",
    "PrResolverError",
    "PrUrlParts",
]
