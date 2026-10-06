"""Deterministic durable execution names (pure, no I/O).

Lambda DurableExecutionName allows only ``[a-zA-Z0-9-_]+`` (max 64 chars),
so names are dash-joined and sanitized. Over-length tails (delivery ids)
are raw-truncated to fit.
"""

from __future__ import annotations

import re

_ALLOWED = re.compile(r"[^a-zA-Z0-9-_]")
MAX_LEN = 64


def _sanitize(name: str) -> str:
    """Enforce [a-zA-Z0-9-_]+ and <=64 chars via raw truncation."""
    return _ALLOWED.sub("-", name)[:MAX_LEN]


def createOpenedExecutionName(*, ghRepoId: int, prNumber: int, headSha: str) -> str:
    """Build review-v2-{ghRepoId}-{pr}-{sha7} for pull_request opened."""
    return _sanitize(f"review-v2-{ghRepoId}-{prNumber}-{headSha[:7]}")


def createCommentExecutionName(*, ghRepoId: int, prNumber: int, delivery: str) -> str:
    """Fallback name for comment path (head SHA unknown without a fetch)."""
    return _sanitize(f"review-v2-{ghRepoId}-{prNumber}-{delivery}")


def createDurableRepairExecutionName(
    *, pr_number: int, commit_id: str, delivery: str
) -> str:
    return _sanitize(f"repair-{pr_number}-{commit_id[:7]}-{delivery}")


def createRepairExecutionName(*, prNumber: int, commitId: str) -> str:
    """Deterministic repair name: one repair per review commit."""
    return _sanitize(f"repair-{prNumber}-{commitId[:7]}")


__all__ = [
    "createCommentExecutionName",
    "createDurableRepairExecutionName",
    "createOpenedExecutionName",
    "createRepairExecutionName",
]
