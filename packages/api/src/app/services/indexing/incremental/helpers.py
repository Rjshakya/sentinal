"""Pure helpers for the incremental indexing pipeline.

No I/O, no session, no clock, no settings reads — every function here
is testable with ``assert f(x) == y``. Derived from
:mod:`app.services.indexing.helpers`, which establishes this
convention for the full-index pipeline.

The push payload is treated as untrusted: every accessor validates
the shape it reads and degrades to ``None`` / empty lists / ``False``
on anything malformed.
"""

from __future__ import annotations

from typing import Any

from app.services.indexing.incremental.types import PushFileSet

__all__ = [
    "DELETE_BATCH_SIZE",
    "build_delete_query",
    "extract_push_files",
    "incremental_workflow_id",
    "is_default_branch_push",
    "push_skip_reason",
]

DELETE_BATCH_SIZE: int = 100
"""Upper bound on file names per ``table.delete`` predicate.

LanceDB predicates can hit length limits with very large ``IN (...)``
lists (a push touching thousands of files); the delete step chunks
the file set at this size.
"""


def is_default_branch_push(payload: dict[str, Any]) -> bool:
    """Return ``True`` iff ``payload["ref"]`` points at the default branch.

    Compares ``ref`` against ``refs/heads/<repository.default_branch>``.
    Deliberately ignores the ``deleted`` / ``created`` flags — those
    are surfaced separately by :func:`push_skip_reason` so the webhook
    adapter can emit granular skip reasons.
    """
    repo = payload.get("repository")
    if not isinstance(repo, dict):
        return False
    ref = payload.get("ref")
    default_branch = repo.get("default_branch")
    if not isinstance(ref, str) or not isinstance(default_branch, str):
        return False
    return ref == f"refs/heads/{default_branch}"


def push_skip_reason(payload: dict[str, Any]) -> str | None:
    """Return a skip reason for a push payload, or ``None`` when eligible.

    Order of checks:

    1. ``malformed_payload`` — ``ref`` or ``repository.default_branch``
       missing / wrong type.
    2. ``not_default_branch`` — the ref is a feature branch / tag; only
       default-branch pushes reconcile the indexed dataset.
    3. ``deleted_push`` — a branch deletion (``head_commit`` is null
       anyway, but the flag is authoritative).
    4. ``created_push`` — the branch's very first push; the LanceDB
       dataset cannot exist yet (the full index owns the bootstrap).

    Returns ``None`` when the push is eligible for incremental indexing.
    """
    repo = payload.get("repository")
    if not isinstance(repo, dict):
        return "malformed_payload"
    ref = payload.get("ref")
    default_branch = repo.get("default_branch")
    if not isinstance(ref, str) or not isinstance(default_branch, str):
        return "malformed_payload"
    if ref != f"refs/heads/{default_branch}":
        return "not_default_branch"
    if payload.get("deleted"):
        return "deleted_push"
    if payload.get("created"):
        return "created_push"
    return None


def extract_push_files(payload: dict[str, Any]) -> PushFileSet | None:
    """Aggregate the push's changed-file lists into a :class:`PushFileSet`.

    Unions ``added`` / ``removed`` / ``modified`` across **every**
    commit in ``payload["commits"]`` (head_commit alone misses files
    changed by earlier commits in a multi-commit push), dropping
    non-string entries. Each list is sorted + deduped.

    Returns ``None`` on a missing / malformed ``head_commit`` (tag
    pushes and branch deletions have ``head_commit: null``).
    """
    head_commit = payload.get("head_commit")
    if not isinstance(head_commit, dict):
        return None
    head_sha = head_commit.get("id")
    if not isinstance(head_sha, str) or not head_sha:
        return None

    added: set[str] = set()
    removed: set[str] = set()
    modified: set[str] = set()

    commits = payload.get("commits")
    if isinstance(commits, list):
        for commit in commits:
            if not isinstance(commit, dict):
                continue
            for key, bucket in (
                ("added", added),
                ("removed", removed),
                ("modified", modified),
            ):
                commit_file_list = commit.get(key)
                if isinstance(commit_file_list, list):
                    bucket.update(f for f in commit_file_list if isinstance(f, str))

    return PushFileSet(
        head_sha=head_sha,
        added=sorted(added),
        removed=sorted(removed),
        modified=sorted(modified),
    )


def incremental_workflow_id(owner: str, repo: str, head_sha: str) -> str:
    """The deterministic DBOS workflow id for one incremental run.

    ``index:{owner}:{repo}:{head_sha[:7]}`` — duplicate webhook
    deliveries for the same head SHA dedupe, while distinct commits
    get distinct runs (unlike the full index's ``index:{owner}:{repo}``,
    which must remain a single idempotent full rewrite).
    """
    return f"index:{owner}:{repo}:{head_sha[:7]}"


def build_delete_query(files: list[str]) -> str:
    """Chunk a file list into LanceDB ``file_name IN (...)`` predicates.

    Chunks at :data:`DELETE_BATCH_SIZE` names per predicate to stay
    under LanceDB's predicate length limits, and SQL-escapes every
    value. Pure / testable — the delete step just executes each
    predicate in order.
    """
    if not len(files):
        return ""

    valid_files = sorted({f.strip() for f in files if f and f.strip()})
    q = ", ".join(f"'{f}'" for f in valid_files)
    return f"file_name IN ({q})"
