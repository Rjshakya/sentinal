"""Pure-helper tests for the incremental indexing pipeline.

No DB, no DBOS, no sandbox — only the Ring-1 helpers and the frozen
Pydantic shapes from :mod:`app.services.indexing.incremental`.

Run: cd packages/api && uv run pytest tests/test_incremental_indexing.py -v
"""

from __future__ import annotations

from app.services.indexing.incremental.helpers import (
    build_delete_query,
    extract_push_files,
    incremental_workflow_id,
    is_default_branch_push,
    push_skip_reason,
)
from app.services.indexing.incremental.types import (
    IncrementalIndexContext,
    IncrementalIndexWorkflowInput,
    PushFileSet,
)
from app.services.indexing.types import IndexContext

_MISSING = object()


def _push_payload(
    *,
    ref: str = "refs/heads/main",
    default_branch: str = "main",
    head_commit: dict | None = _MISSING,  # type: ignore[assignment]
    commits: list[dict] | None = _MISSING,  # type: ignore[assignment]
    deleted: bool = False,
    created: bool = False,
) -> dict:
    if head_commit is _MISSING:
        head_commit = {"id": "a" * 40, "message": "commit"}
    if commits is _MISSING:
        commits = [head_commit] if head_commit is not None else None
    return {
        "ref": ref,
        "deleted": deleted,
        "created": created,
        "head_commit": head_commit,
        "repository": {
            "name": "planetform",
            "full_name": "Rjshakya/planetform",
            "default_branch": default_branch,
        },
        "commits": commits,
    }


def _commit(files: dict) -> dict:
    return {
        "added": files.get("added", []),
        "removed": files.get("removed", []),
        "modified": files.get("modified", []),
    }


# --------------------------------------------------------------------------- #
# push classification                                                          #
# --------------------------------------------------------------------------- #


def test_is_default_branch_push_matches_ref() -> None:
    payload = _push_payload()
    assert is_default_branch_push(payload) is True


def test_is_default_branch_push_rejects_feature_branch() -> None:
    payload = _push_payload(ref="refs/heads/feature/x")
    assert is_default_branch_push(payload) is False


def test_is_default_branch_push_rejects_malformed() -> None:
    assert is_default_branch_push({}) is False
    assert is_default_branch_push({"ref": "refs/heads/main"}) is False
    assert is_default_branch_push({"ref": "refs/heads/main", "repository": {}}) is False


def test_push_skip_reason_eligible_push() -> None:
    assert push_skip_reason(_push_payload()) is None


def test_push_skip_reason_not_default_branch() -> None:
    payload = _push_payload(ref="refs/heads/feature/x")
    assert push_skip_reason(payload) == "not_default_branch"


def test_push_skip_reason_deleted() -> None:
    payload = _push_payload(deleted=True)
    assert push_skip_reason(payload) == "deleted_push"


def test_push_skip_reason_created() -> None:
    payload = _push_payload(created=True)
    assert push_skip_reason(payload) == "created_push"


def test_push_skip_reason_malformed() -> None:
    assert push_skip_reason({}) == "malformed_payload"
    assert (
        push_skip_reason({"ref": "refs/heads/main", "repository": {}})
        == "malformed_payload"
    )


# --------------------------------------------------------------------------- #
# file aggregation                                                             #
# --------------------------------------------------------------------------- #


def test_extract_push_files_single_commit() -> None:
    payload = _push_payload(
        commits=[
            _commit({"added": ["a.py"], "removed": ["b.py"], "modified": ["c.py"]})
        ]
    )
    files = extract_push_files(payload)
    assert files is not None
    assert files.head_sha == "a" * 40
    assert files.added == ["a.py"]
    assert files.removed == ["b.py"]
    assert files.modified == ["c.py"]


def test_extract_push_files_aggregates_all_commits() -> None:
    payload = _push_payload(
        head_commit={"id": "b" * 40, "message": "last"},
        commits=[
            _commit({"added": ["a.py"], "modified": ["shared.py"]}),
            _commit({"removed": ["old.py"], "modified": ["shared.py", "other.py"]}),
            _commit({"added": ["a.py"]}),
        ],
    )
    files = extract_push_files(payload)
    assert files is not None
    assert files.head_sha == "b" * 40
    assert files.added == ["a.py"]
    assert files.removed == ["old.py"]
    assert files.modified == ["other.py", "shared.py"]


def test_extract_push_files_drops_non_strings() -> None:
    payload = _push_payload(
        commits=[{"added": ["a.py", 42, None], "removed": [], "modified": []}]
    )
    files = extract_push_files(payload)
    assert files is not None
    assert files.added == ["a.py"]


def test_extract_push_files_none_on_null_head_commit() -> None:
    payload = _push_payload(head_commit=None)
    assert extract_push_files(payload) is None


def test_extract_push_files_none_on_malformed_head_commit() -> None:
    payload = _push_payload(head_commit={"id": 42})
    assert extract_push_files(payload) is None


def test_extract_push_files_tolerates_non_list_commits() -> None:
    payload = _push_payload(commits=None)
    files = extract_push_files(payload)
    assert files is not None
    assert files.added == []
    assert files.removed == []
    assert files.modified == []


# --------------------------------------------------------------------------- #
# workflow id                                                                  #
# --------------------------------------------------------------------------- #


def test_incremental_workflow_id() -> None:
    sha = "abcd1234efgh"
    assert incremental_workflow_id("Rjshakya", "planetform", sha) == (
        "index:Rjshakya:planetform:abcd123"
    )


def test_incremental_workflow_id_is_distinct_per_sha() -> None:
    assert incremental_workflow_id("o", "r", "aaaaaaaa") != incremental_workflow_id(
        "o", "r", "bbbbbbbb"
    )


# --------------------------------------------------------------------------- #
# delete predicates                                                            #
# --------------------------------------------------------------------------- #


def test_build_delete_predicates_single_batch() -> None:
    query = build_delete_query(["a.py", "b.py", "c.py"])
    assert len(query) > 0
    assert query == "file_name IN ('a.py', 'b.py', 'c.py')"


def test_build_delete_predicates_escapes_quotes() -> None:
    query = build_delete_query(["it's/tricky.py"])
    assert query == "file_name IN ('it's/tricky.py')"


def test_build_delete_predicates_empty_and_dirty_input() -> None:
    assert build_delete_query([]) == ""
    assert build_delete_query(["", "  ", "a.py", "a.py"]) == "file_name IN ('a.py')"


# --------------------------------------------------------------------------- #
# shapes                                                                       #
# --------------------------------------------------------------------------- #


def test_push_file_set_is_frozen() -> None:
    files = PushFileSet(head_sha="x", added=["b.py", "a.py"])
    assert files.added == ["b.py", "a.py"]
    try:
        files.head_sha = "y"  # type: ignore[misc]
    except (ValueError, AttributeError):
        pass
    else:
        raise AssertionError("PushFileSet must be immutable")


def test_incremental_context_subclasses_index_context() -> None:
    ctx = IncrementalIndexContext(
        user_id="u1",
        sandbox_id="sbx",
        sandbox_name="incr-o-r",
        repo_owner="o",
        repo_name="r",
        repo_url="https://github.com/o/r.git",
        default_branch="main",
        repo_dir="/home/user/sentinel-workspace/r",
        ingest_script_path="/home/user/sentinel-workspace/context/incremental_ingestion.py",
        table_uri="s3://bucket/sentinel/lance/o/r",
        files_to_index=["a.py", "b.py"],
    )
    assert isinstance(ctx, IndexContext)
    assert ctx.files_to_index == ["a.py", "b.py"]
    assert ctx.batch_size == 50


def test_incremental_workflow_input_defaults() -> None:
    workflow_input = IncrementalIndexWorkflowInput(
        user_id="u1",
        repo_owner="o",
        repo_name="r",
        repo_url="https://github.com/o/r.git",
        local_repo_id="repo-1",
        head_sha="a" * 40,
    )
    assert workflow_input.files_to_delete == []
    assert workflow_input.files_to_index == []
    assert workflow_input.default_branch is None
