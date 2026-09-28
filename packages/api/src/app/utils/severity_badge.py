"""Severity badge for GitHub inline review comments.

The review agents produce :class:`app.utils.schema.CodeCommentDraft`
items whose ``comment`` body follows the comment-body contract
(headline → bullets → fix) with no severity indicator. This module owns
the deterministic, post-extractor presentation step: prefixing the
severity badge image on top of the body.

Badges are hosted PNGs (80x80, transparent) referenced as an ``<img>``
tag — GitHub renders it from the markdown body of the review comment.
DB rows and GitHub bodies both store the prefixed text; the ``severity``
enum column stays the queryable source of truth.
"""

from __future__ import annotations

from app.utils.schema import CommentSeverityStr

SEVERITY_BADGE_URL: dict[CommentSeverityStr, str] = {
    "P1_CRITICAL": "https://templates-assets.nastro.xyz/sentinal-pr-badges/p1.png",
    "P2_WARNING": "https://templates-assets.nastro.xyz/sentinal-pr-badges/p2.png",
    "P3_NITPICK": "https://templates-assets.nastro.xyz/sentinal-pr-badges/p3.png",
}
"""Badge image URL per severity."""

SEVERITY_BADGE_ALT: dict[CommentSeverityStr, str] = {
    "P1_CRITICAL": "P1 Critical",
    "P2_WARNING": "P2 Warning",
    "P3_NITPICK": "P3 Nitpick",
}
"""Alt text per severity (accessibility + broken-image fallback)."""

_BADGE_HEIGHT = 20
"""Display height in px; the 80px source stays crisp on retina."""

_BADGE_MARKER = "sentinal-pr-badges"
"""URL fragment identifying our badge line (idempotency guard)."""


def badgeLine(severity: CommentSeverityStr) -> str:
    """Build the badge ``<img>`` line for a severity."""
    return (
        f'<img src="{SEVERITY_BADGE_URL[severity]}" '
        f'height="{_BADGE_HEIGHT}" alt="{SEVERITY_BADGE_ALT[severity]}">'
    )


def withSeverityBadge(severity: CommentSeverityStr, body: str) -> str:
    """Prefix the severity badge line on top of a comment body.

    Idempotent: bodies already carrying a badge line are returned
    unchanged, so re-running a converter over a prefixed body (e.g. a
    DB row read back) never double-prefixes.
    """
    stripped = body.lstrip()
    if stripped.startswith("<img"):
        first_line = stripped.splitlines()[0] if stripped.splitlines() else ""
        if _BADGE_MARKER in first_line:
            return body
    return f"{badgeLine(severity)}\n\n{body.strip()}"


__all__ = [
    "SEVERITY_BADGE_ALT",
    "SEVERITY_BADGE_URL",
    "badgeLine",
    "withSeverityBadge",
]
