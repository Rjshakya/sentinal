"""Deterministic durable execution names (pure, no I/O)."""

from __future__ import annotations


def createOpenedExecutionName(*, ghRepoId: int, prNumber: int, headSha: str) -> str:
    """Build review-v2:{ghRepoId}:{pr}:{sha7} for pull_request opened."""
    return f"review-v2:{ghRepoId}:{prNumber}:{headSha[:7]}"


def createCommentExecutionName(*, ghRepoId: int, prNumber: int, delivery: str) -> str:
    """Fallback name for comment path (head SHA unknown without a fetch)."""
    return f"review-v2:{ghRepoId}:{prNumber}:{delivery}"


def createDurableRepairExecutionName(
    *, pr_number: int, commit_id: str, delivery: str
) -> str:
    return f"repair:{pr_number}:{commit_id[:7]}:{delivery}"


def createRepairExecutionName(*, prNumber: int, commitId: str) -> str:
    """Deterministic repair name: one repair per review commit."""
    return f"repair:{prNumber}:{commitId[:7]}"


__all__ = [
    "createCommentExecutionName",
    "createDurableRepairExecutionName",
    "createOpenedExecutionName",
    "createRepairExecutionName",
]
