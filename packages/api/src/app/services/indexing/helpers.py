"""Pure helpers for the indexing pipeline.

No I/O, no session, no clock, no settings reads — every function here
is testable with ``assert f(x) == y``. Derived from
:mod:`app.services.agent.setup_workflow._helpers`, which establishes
this convention for the setup pipeline.
"""

from __future__ import annotations

from app.core.sandbox.types import CommandResult
from app.services.indexing.errors import InvalidRepoUrlError

__all__ = [
    "build_table_uri",
    "command_output_tail",
    "index_workflow_id",
    "parse_index_summary",
    "parse_repo_url",
]


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Return ``(owner, repo)`` from a repo URL or bare ``owner/repo``.

    Accepts ``https://github.com/owner/repo``, ``git@github.com:owner/repo.git``,
    ``https://any-host/owner/repo``, and the bare ``owner/repo`` form.
    Anything that does not resolve to exactly two path segments raises
    :class:`InvalidRepoUrlError`.

    Note: the indexing pipeline no longer calls this in production.
    The router (``POST /indexing/repo``) and the workflow both
    consume ``IndexWorkflowInput.repo_owner`` + ``IndexWorkflowInput.repo_name``
    (client-supplied, Pydantic-validated). This helper remains as a
    pure utility for tests and one-off URL parsing outside the
    workflow path.

    Raises:
        InvalidRepoUrlError: the URL cannot be parsed. Final — the
            caller passes it straight through to the workflow result.
    """
    url = repo_url.strip().rstrip("/")
    if not url:
        raise InvalidRepoUrlError(repo_url=repo_url, reason="url is empty")

    # Strip the scheme (https://, git://, ssh://, ...).
    if "://" in url:
        url = url.split("://", 1)[1]
    # Strip `user@host` for scp-style URLs (git@github.com:owner/repo).
    if ":" in url and "/" not in url.split(":", 1)[0]:
        url = url.split(":", 1)[1]
    # Drop query / fragment.
    url = url.split("?", 1)[0].split("#", 1)[0]
    # Drop the trailing .git suffix.
    url = url.removesuffix(".git")

    parts = [part for part in url.split("/") if part]
    if len(parts) < 2:
        raise InvalidRepoUrlError(
            repo_url=repo_url,
            reason="expected owner/repo after the host",
        )
    owner, repo = parts[-2], parts[-1]
    if not owner or not repo:
        raise InvalidRepoUrlError(repo_url=repo_url, reason="empty owner or repo")
    return owner, repo


def index_workflow_id(owner: str, repo: str) -> str:
    """The deterministic DBOS workflow id for an index run.

    Idempotency: a second dispatch for the same ``owner/repo`` reuses
    the running workflow (or returns the cached result), so concurrent
    re-indexes dedupe. The router dispatches with this id.
    """
    return f"index:{owner}:{repo}"


def build_table_uri(bucket: str, prefix: str, owner: str, repo: str) -> str:
    """S3 URI for the repo's LanceDB dataset (one dataset per repo)."""
    clean_prefix = prefix.strip("/")
    return f"s3://{bucket}/{clean_prefix}/{owner}/{repo}"


def command_output_tail(result: CommandResult, *, max_chars: int = 500) -> str:
    """Short stderr-first tail of a :class:`CommandResult`, for error messages.

    Falls back to the runner-level ``error`` field (e.g. the E2B SDK's
    ``InvalidArgumentException`` for a bad cwd), which ``stderr`` /
    ``stdout`` leave empty on transport failures.
    """
    raw = (result.stderr or result.stdout or result.error or "").strip()
    return raw[:max_chars]


def parse_index_summary(line: str) -> tuple[int, int] | None:
    """Parse the in-sandbox ingestion script's stdout summary line.

    Expects ``indexed {N} chunks from {M} files``; returns
    ``(chunk_count, file_count)`` on a match and ``None`` otherwise.
    Pure / testable.
    """
    line = line.strip()
    if not line.startswith("indexed "):
        return None
    try:
        head, _, tail = line.partition(" chunks from ")
        chunks_part = head.removeprefix("indexed ")
        file_part, _, _ = tail.partition(" files")
        return int(chunks_part), int(file_part)
    except (ValueError, AttributeError):
        return None
