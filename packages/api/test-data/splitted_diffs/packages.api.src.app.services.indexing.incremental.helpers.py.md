### packages/api/src/app/services/indexing/incremental/helpers.py

```diff

deleted file mode 100644
index 70297ee..0000000
--- a/packages/api/src/app/services/indexing/incremental/helpers.py
+++ /dev/null
@@ -1,155 +0,0 @@
    2       -"""Pure helpers for the incremental indexing pipeline.
    3       -
    4       -No I/O, no session, no clock, no settings reads — every function here
    5       -is testable with ``assert f(x) == y``. Derived from
    6       -:mod:`app.services.indexing.helpers`, which establishes this
    7       -convention for the full-index pipeline.
    8       -
    9       -The push payload is treated as untrusted: every accessor validates
   10       -the shape it reads and degrades to ``None`` / empty lists / ``False``
   11       -on anything malformed.
   12       -"""
   13       -
   14       -from __future__ import annotations
   15       -
   16       -from typing import Any
   17       -
   18       -from app.services.indexing.incremental.types import PushFileSet
   19       -
   20       -__all__ = [
   21       -    "DELETE_BATCH_SIZE",
   22       -    "build_delete_query",
   23       -    "extract_push_files",
   24       -    "incremental_workflow_id",
   25       -    "is_default_branch_push",
   26       -    "push_skip_reason",
   27       -]
   28       -
   29       -DELETE_BATCH_SIZE: int = 100
   30       -"""Upper bound on file names per ``table.delete`` predicate.
   31       -
   32       -LanceDB predicates can hit length limits with very large ``IN (...)``
   33       -lists (a push touching thousands of files); the delete step chunks
   34       -the file set at this size.
   35       -"""
   36       -
   37       -
   38       -def is_default_branch_push(payload: dict[str, Any]) -> bool:
   39       -    """Return ``True`` iff ``payload["ref"]`` points at the default branch.
   40       -
   41       -    Compares ``ref`` against ``refs/heads/<repository.default_branch>``.
   42       -    Deliberately ignores the ``deleted`` / ``created`` flags — those
   43       -    are surfaced separately by :func:`push_skip_reason` so the webhook
   44       -    adapter can emit granular skip reasons.
   45       -    """
   46       -    repo = payload.get("repository")
   47       -    if not isinstance(repo, dict):
   48       -        return False
   49       -    ref = payload.get("ref")
   50       -    default_branch = repo.get("default_branch")
   51       -    if not isinstance(ref, str) or not isinstance(default_branch, str):
   52       -        return False
   53       -    return ref == f"refs/heads/{default_branch}"
   54       -
   55       -
   56       -def push_skip_reason(payload: dict[str, Any]) -> str | None:
   57       -    """Return a skip reason for a push payload, or ``None`` when eligible.
   58       -
   59       -    Order of checks:
   60       -
   61       -    1. ``malformed_payload`` — ``ref`` or ``repository.default_branch``
   62       -       missing / wrong type.
   63       -    2. ``not_default_branch`` — the ref is a feature branch / tag; only
   64       -       default-branch pushes reconcile the indexed dataset.
   65       -    3. ``deleted_push`` — a branch deletion (``head_commit`` is null
   66       -       anyway, but the flag is authoritative).
   67       -    4. ``created_push`` — the branch's very first push; the LanceDB
   68       -       dataset cannot exist yet (the full index owns the bootstrap).
   69       -
   70       -    Returns ``None`` when the push is eligible for incremental indexing.
   71       -    """
   72       -    repo = payload.get("repository")
   73       -    if not isinstance(repo, dict):
   74       -        return "malformed_payload"
   75       -    ref = payload.get("ref")
   76       -    default_branch = repo.get("default_branch")
   77       -    if not isinstance(ref, str) or not isinstance(default_branch, str):
   78       -        return "malformed_payload"
   79       -    if ref != f"refs/heads/{default_branch}":
   80       -        return "not_default_branch"
   81       -    if payload.get("deleted"):
   82       -        return "deleted_push"
   83       -    if payload.get("created"):
   84       -        return "created_push"
   85       -    return None
   86       -
   87       -
   88       -def extract_push_files(payload: dict[str, Any]) -> PushFileSet | None:
   89       -    """Aggregate the push's changed-file lists into a :class:`PushFileSet`.
   90       -
   91       -    Unions ``added`` / ``removed`` / ``modified`` across **every**
   92       -    commit in ``payload["commits"]`` (head_commit alone misses files
   93       -    changed by earlier commits in a multi-commit push), dropping
   94       -    non-string entries. Each list is sorted + deduped.
   95       -
   96       -    Returns ``None`` on a missing / malformed ``head_commit`` (tag
   97       -    pushes and branch deletions have ``head_commit: null``).
   98       -    """
   99       -    head_commit = payload.get("head_commit")
  100       -    if not isinstance(head_commit, dict):
  101       -        return None
  102       -    head_sha = head_commit.get("id")
  103       -    if not isinstance(head_sha, str) or not head_sha:
  104       -        return None
  105       -
  106       -    added: set[str] = set()
  107       -    removed: set[str] = set()
  108       -    modified: set[str] = set()
  109       -
  110       -    commits = payload.get("commits")
  111       -    if isinstance(commits, list):
  112       -        for commit in commits:
  113       -            if not isinstance(commit, dict):
  114       -                continue
  115       -            for key, bucket in (
  116       -                ("added", added),
  117       -                ("removed", removed),
  118       -                ("modified", modified),
  119       -            ):
  120       -                commit_file_list = commit.get(key)
  121       -                if isinstance(commit_file_list, list):
  122       -                    bucket.update(f for f in commit_file_list if isinstance(f, str))
  123       -
  124       -    return PushFileSet(
  125       -        head_sha=head_sha,
  126       -        added=sorted(added),
  127       -        removed=sorted(removed),
  128       -        modified=sorted(modified),
  129       -    )
  130       -
  131       -
  132       -def incremental_workflow_id(owner: str, repo: str, head_sha: str) -> str:
  133       -    """The deterministic DBOS workflow id for one incremental run.
  134       -
  135       -    ``index:{owner}:{repo}:{head_sha[:7]}`` — duplicate webhook
  136       -    deliveries for the same head SHA dedupe, while distinct commits
  137       -    get distinct runs (unlike the full index's ``index:{owner}:{repo}``,
  138       -    which must remain a single idempotent full rewrite).
  139       -    """
  140       -    return f"index:{owner}:{repo}:{head_sha[:7]}"
  141       -
  142       -
  143       -def build_delete_query(files: list[str]) -> str:
  144       -    """Chunk a file list into LanceDB ``file_name IN (...)`` predicates.
  145       -
  146       -    Chunks at :data:`DELETE_BATCH_SIZE` names per predicate to stay
  147       -    under LanceDB's predicate length limits, and SQL-escapes every
  148       -    value. Pure / testable — the delete step just executes each
  149       -    predicate in order.
  150       -    """
  151       -    if not len(files):
  152       -        return ""
  153       -
  154       -    valid_files = sorted({f.strip() for f in files if f and f.strip()})
  155       -    q = ", ".join(f"'{f}'" for f in valid_files)
  156       -    return f"file_name IN ({q})"

```
