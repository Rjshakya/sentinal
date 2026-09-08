"""Review agent contract: dataset input, run output, and the result.md format.

``result.md`` is the single artifact of the review stage. It is a fixed
template — rendered by :func:`render_markdown` and parsed back by
:func:`parse_markdown` — so the judge consumes the review output
deterministically. Never edit a result.md by hand; if the template
changes, renderer and parser change together.

The eval runner is now a thin HTTP client: the review stage no longer
runs the production agents locally. It POSTs the dataset input to
``POST /api/review`` (the production ``reviewWorkflow`` exposed as a
synchronous API) and consumes the typed :class:`EvalReviewResponse`
shape. :meth:`ReviewOutput.from_api_response` adapts that shape onto
:class:`ReviewOutput` so the existing ``render_markdown`` helper stays
unchanged. The dataset ``input.json`` schema is the canonical request
body.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, cast

from pydantic import BaseModel, Field, model_validator

from app.utils.branded import CommitId, PRNumber, RepoName, RepoOwner
from app.utils.schema import (
    CodeCommentDraft,
    CommentSeverityStr,
    CommentSideStr,
    ReviewVerdictStr,
)

from type import EvalReviewComment, EvalReviewResponse


class ReviewInput(BaseModel):
    """The dataset ``input.json``: everything the API needs to review one PR.

    Mirrors the production ``EvalReviewRequest`` body. ``user_id`` /
    ``github_repo_id`` / ``github_installation_id`` are the canonical
    identifiers the workflow needs; the route synthesises placeholder
    PR metadata (author / title / branches / status) on the caller's
    behalf.
    """

    user_id: str = Field(
        min_length=1,
        description="Synthetic WorkOS user_id the run is attributed to. "
        "Used as ``repos.user_id`` and ``review.user_id``.",
    )
    github_repo_id: int = Field(
        ge=1,
        description="GitHub repository id (the numeric id from "
        "``GET /repos/{owner}/{name}``). Idempotency key for the local "
        "``repos`` row.",
    )
    github_installation_id: int = Field(
        ge=1,
        description="GitHub App installation id used to mint the "
        "clone token inside the sandbox.",
    )

    github_pr_id: int = Field(ge=1, description="GitHub pr id")

    repo_url: str = Field(
        min_length=1,
        max_length=1024,
        description="Clone URL written to ``repos.clone_url`` for the "
        "synthetic Repo row.",
    )
    repo_owner: str = Field(
        min_length=1,
        description="GitHub repository owner (user or org login).",
    )
    repo_name: str = Field(
        min_length=1,
        description="GitHub repository name.",
    )
    pr_number: int = Field(ge=1, description="PR number on the repo.")

    base_sha: str = Field(
        min_length=7,
        max_length=64,
        description="Base commit SHA (full or abbreviated hex).",
    )

    base_branch: str = Field(description="Base Branch")
    default_branch: str = Field(description="Head Branch")
    head_branch: str = Field(description="Head Branch")

    head_sha: str = Field(
        min_length=7,
        max_length=64,
        description="Head commit SHA (full or abbreviated hex).",
    )

    post_to_github: bool = Field(
        default=False,
        description="When true, the workflow posts the review inline "
        "via the GitHub App. The eval harness always sets this to false.",
    )

    author: str = Field(default="sentinal", description="PR author")
    title: str = Field(default="Eval PR", description="PR title")


class ReviewOutput(BaseModel):
    """The review stage's result: what ``result.md`` renders and the
    judge consumes."""

    verdict: ReviewVerdictStr
    summary: str
    comments: Annotated[list[CodeCommentDraft], Field(default_factory=list)]

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> ReviewOutput:
        """Adapt the ``POST /api/review`` response onto :class:`ReviewOutput`.

        The API response carries ``workflow_id`` and ``usages`` that the
        eval runner passes through as run metadata; only ``verdict`` /
        ``summary`` / ``comments`` map onto the output the judge reads.
        ``data`` is typed as ``dict[str, Any]`` because the response is
        JSON-decoded at the API boundary — pydantic validates the
        adapter's output but not the raw bytes.
        """
        raw_comments = cast(list[Any], data.get("comments") or [])
        comments: list[CodeCommentDraft] = []
        for raw in raw_comments:
            if not isinstance(raw, dict):
                continue
            raw_dict = cast(dict[str, Any], raw)
            comments.append(
                CodeCommentDraft(
                    file_name=str(raw_dict["file_name"]),
                    comment=str(raw_dict["comment"]),
                    severity=cast(CommentSeverityStr, raw_dict["severity"]),
                    from_line=int(raw_dict["from_line"]),
                    to_line=int(raw_dict["to_line"]),
                    side=cast(CommentSideStr, raw_dict.get("side", "RIGHT")),
                    node_type=(
                        str(raw_dict["node_type"])
                        if raw_dict.get("node_type") is not None
                        else None
                    ),
                )
            )
        return cls(
            verdict=cast(ReviewVerdictStr, data["verdict"]),
            summary=str(data.get("summary") or ""),
            comments=comments,
        )


_TOP_RE = re.compile(
    r"^# Review\n\nverdict: (APPROVE|COMMENT|REQUEST_CHANGES)\n\n## Summary\n\n"
)
_COMMENTS_MARKER = "\n\n## Comments\n"
_COMMENT_HEADER_RE = re.compile(
    r"^### C(\d+) — (.+):(\d+)(?:-(\d+))? \((P1_CRITICAL|P2_WARNING|P3_NITPICK)\)$",
    re.MULTILINE,
)


def _location(comment: EvalReviewComment) -> str:
    if comment.from_line == comment.to_line:
        return f"{comment.file_name}:{comment.from_line}"
    return f"{comment.file_name}:{comment.from_line}-{comment.to_line}"


def render_markdown(output: EvalReviewResponse) -> str:
    """Render the review output in the result.md template."""
    sections = [
        f"# Review\n\nverdict: {output.verdict}\n\n## Summary\n\n"
        f"{output.summary.strip()}\n\n## Comments\n"
    ]
    for i, comment in enumerate(output.comments):
        sections.append(
            f"### C{i} — {_location(comment)} ({comment.severity})\n\n"
            f"{comment.comment.strip()}"
        )
    return "\n\n".join(sections)


def parse_markdown(text: str) -> ReviewOutput:
    """Parse a result.md back into a :class:`ReviewOutput`.

    Raises:
        ValueError: the text is not in the review template (missing or
            malformed header, verdict, summary, or comments markers).
    """
    top = _TOP_RE.match(text)
    if top is None:
        raise ValueError(
            "result.md is not in the review template "
            "(missing header, verdict, or summary marker)"
        )
    verdict = cast(ReviewVerdictStr, top.group(1))
    rest = text[top.end() :]

    marker_end = rest.rfind(_COMMENTS_MARKER)
    if marker_end == -1:
        raise ValueError("result.md has no '## Comments' section")
    summary = rest[:marker_end].strip()
    comments_text = rest[marker_end + len(_COMMENTS_MARKER) :]

    for line in comments_text.splitlines():
        if line.startswith("### C") and _COMMENT_HEADER_RE.match(line) is None:
            raise ValueError(f"malformed comment header in result.md: {line!r}")

    comments: list[CodeCommentDraft] = []
    for match in _COMMENT_HEADER_RE.finditer(comments_text):
        idx = int(match.group(1))
        if idx != len(comments):
            raise ValueError(
                f"comment index out of sequence in result.md: C{idx} after C{len(comments)}"
            )
        file_name = match.group(2)
        from_line = int(match.group(3))
        to_line = int(match.group(4)) if match.group(4) is not None else from_line
        severity = cast(CommentSeverityStr, match.group(5))
        body_start = match.end()
        next_match = _COMMENT_HEADER_RE.search(comments_text, body_start)
        body_end = next_match.start() if next_match is not None else len(comments_text)
        comments.append(
            CodeCommentDraft(
                file_name=file_name,
                comment=comments_text[body_start:body_end].strip(),
                severity=severity,
                from_line=from_line,
                to_line=to_line,
            )
        )

    return ReviewOutput(verdict=verdict, summary=summary, comments=comments)


__all__ = [
    "ReviewInput",
    "ReviewOutput",
    "parse_markdown",
    "render_markdown",
]
