### packages/api/tests/test_incremental_indexing.py

```diff

deleted file mode 100644
index 206ebae..0000000
--- a/packages/api/tests/test_incremental_indexing.py
+++ /dev/null
@@ -1,260 +0,0 @@
    2       -"""Pure-helper tests for the incremental indexing pipeline.
    3       -
    4       -No DB, no DBOS, no sandbox — only the Ring-1 helpers and the frozen
    5       -Pydantic shapes from :mod:`app.services.indexing.incremental`.
    6       -
    7       -Run: cd packages/api && uv run pytest tests/test_incremental_indexing.py -v
    8       -"""
    9       -
   10       -from __future__ import annotations
   11       -
   12       -from app.services.indexing.incremental.helpers import (
   13       -    build_delete_query,
   14       -    extract_push_files,
   15       -    incremental_workflow_id,
   16       -    is_default_branch_push,
   17       -    push_skip_reason,
   18       -)
   19       -from app.services.indexing.incremental.types import (
   20       -    IncrementalIndexContext,
   21       -    IncrementalIndexWorkflowInput,
   22       -    PushFileSet,
   23       -)
   24       -from app.services.indexing.types import IndexContext
   25       -
   26       -_MISSING = object()
   27       -
   28       -
   29       -def _push_payload(
   30       -    *,
   31       -    ref: str = "refs/heads/main",
   32       -    default_branch: str = "main",
   33       -    head_commit: dict | None = _MISSING,  # type: ignore[assignment]
   34       -    commits: list[dict] | None = _MISSING,  # type: ignore[assignment]
   35       -    deleted: bool = False,
   36       -    created: bool = False,
   37       -) -> dict:
   38       -    if head_commit is _MISSING:
   39       -        head_commit = {"id": "a" * 40, "message": "commit"}
   40       -    if commits is _MISSING:
   41       -        commits = [head_commit] if head_commit is not None else None
   42       -    return {
   43       -        "ref": ref,
   44       -        "deleted": deleted,
   45       -        "created": created,
   46       -        "head_commit": head_commit,
   47       -        "repository": {
   48       -            "name": "planetform",
   49       -            "full_name": "Rjshakya/planetform",
   50       -            "default_branch": default_branch,
   51       -        },
   52       -        "commits": commits,
   53       -    }
   54       -
   55       -
   56       -def _commit(files: dict) -> dict:
   57       -    return {
   58       -        "added": files.get("added", []),
   59       -        "removed": files.get("removed", []),
   60       -        "modified": files.get("modified", []),
   61       -    }
   62       -
   63       -
   64       -# --------------------------------------------------------------------------- #
   65       -# push classification                                                          #
   66       -# --------------------------------------------------------------------------- #
   67       -
   68       -
   69       -def test_is_default_branch_push_matches_ref() -> None:
   70       -    payload = _push_payload()
   71       -    assert is_default_branch_push(payload) is True
   72       -
   73       -
   74       -def test_is_default_branch_push_rejects_feature_branch() -> None:
   75       -    payload = _push_payload(ref="refs/heads/feature/x")
   76       -    assert is_default_branch_push(payload) is False
   77       -
   78       -
   79       -def test_is_default_branch_push_rejects_malformed() -> None:
   80       -    assert is_default_branch_push({}) is False
   81       -    assert is_default_branch_push({"ref": "refs/heads/main"}) is False
   82       -    assert is_default_branch_push({"ref": "refs/heads/main", "repository": {}}) is False
   83       -
   84       -
   85       -def test_push_skip_reason_eligible_push() -> None:
   86       -    assert push_skip_reason(_push_payload()) is None
   87       -
   88       -
   89       -def test_push_skip_reason_not_default_branch() -> None:
   90       -    payload = _push_payload(ref="refs/heads/feature/x")
   91       -    assert push_skip_reason(payload) == "not_default_branch"
   92       -
   93       -
   94       -def test_push_skip_reason_deleted() -> None:
   95       -    payload = _push_payload(deleted=True)
   96       -    assert push_skip_reason(payload) == "deleted_push"
   97       -
   98       -
   99       -def test_push_skip_reason_created() -> None:
  100       -    payload = _push_payload(created=True)
  101       -    assert push_skip_reason(payload) == "created_push"
  102       -
  103       -
  104       -def test_push_skip_reason_malformed() -> None:
  105       -    assert push_skip_reason({}) == "malformed_payload"
  106       -    assert (
  107       -        push_skip_reason({"ref": "refs/heads/main", "repository": {}})
  108       -        == "malformed_payload"
  109       -    )
  110       -
  111       -
  112       -# --------------------------------------------------------------------------- #
  113       -# file aggregation                                                             #
  114       -# --------------------------------------------------------------------------- #
  115       -
  116       -
  117       -def test_extract_push_files_single_commit() -> None:
  118       -    payload = _push_payload(
  119       -        commits=[
  120       -            _commit({"added": ["a.py"], "removed": ["b.py"], "modified": ["c.py"]})
  121       -        ]
  122       -    )
  123       -    files = extract_push_files(payload)
  124       -    assert files is not None
  125       -    assert files.head_sha == "a" * 40
  126       -    assert files.added == ["a.py"]
  127       -    assert files.removed == ["b.py"]
  128       -    assert files.modified == ["c.py"]
  129       -
  130       -
  131       -def test_extract_push_files_aggregates_all_commits() -> None:
  132       -    payload = _push_payload(
  133       -        head_commit={"id": "b" * 40, "message": "last"},
  134       -        commits=[
  135       -            _commit({"added": ["a.py"], "modified": ["shared.py"]}),
  136       -            _commit({"removed": ["old.py"], "modified": ["shared.py", "other.py"]}),
  137       -            _commit({"added": ["a.py"]}),
  138       -        ],
  139       -    )
  140       -    files = extract_push_files(payload)
  141       -    assert files is not None
  142       -    assert files.head_sha == "b" * 40
  143       -    assert files.added == ["a.py"]
  144       -    assert files.removed == ["old.py"]
  145       -    assert files.modified == ["other.py", "shared.py"]
  146       -
  147       -
  148       -def test_extract_push_files_drops_non_strings() -> None:
  149       -    payload = _push_payload(
  150       -        commits=[{"added": ["a.py", 42, None], "removed": [], "modified": []}]
  151       -    )
  152       -    files = extract_push_files(payload)
  153       -    assert files is not None
  154       -    assert files.added == ["a.py"]
  155       -
  156       -
  157       -def test_extract_push_files_none_on_null_head_commit() -> None:
  158       -    payload = _push_payload(head_commit=None)
  159       -    assert extract_push_files(payload) is None
  160       -
  161       -
  162       -def test_extract_push_files_none_on_malformed_head_commit() -> None:
  163       -    payload = _push_payload(head_commit={"id": 42})
  164       -    assert extract_push_files(payload) is None
  165       -
  166       -
  167       -def test_extract_push_files_tolerates_non_list_commits() -> None:
  168       -    payload = _push_payload(commits=None)
  169       -    files = extract_push_files(payload)
  170       -    assert files is not None
  171       -    assert files.added == []
  172       -    assert files.removed == []
  173       -    assert files.modified == []
  174       -
  175       -
  176       -# --------------------------------------------------------------------------- #
  177       -# workflow id                                                                  #
  178       -# --------------------------------------------------------------------------- #
  179       -
  180       -
  181       -def test_incremental_workflow_id() -> None:
  182       -    sha = "abcd1234efgh"
  183       -    assert incremental_workflow_id("Rjshakya", "planetform", sha) == (
  184       -        "index:Rjshakya:planetform:abcd123"
  185       -    )
  186       -
  187       -
  188       -def test_incremental_workflow_id_is_distinct_per_sha() -> None:
  189       -    assert incremental_workflow_id("o", "r", "aaaaaaaa") != incremental_workflow_id(
  190       -        "o", "r", "bbbbbbbb"
  191       -    )
  192       -
  193       -
  194       -# --------------------------------------------------------------------------- #
  195       -# delete predicates                                                            #
  196       -# --------------------------------------------------------------------------- #
  197       -
  198       -
  199       -def test_build_delete_predicates_single_batch() -> None:
  200       -    query = build_delete_query(["a.py", "b.py", "c.py"])
  201       -    assert len(query) > 0
  202       -    assert query == "file_name IN ('a.py', 'b.py', 'c.py')"
  203       -
  204       -
  205       -def test_build_delete_predicates_escapes_quotes() -> None:
  206       -    query = build_delete_query(["it's/tricky.py"])
  207       -    assert query == "file_name IN ('it's/tricky.py')"
  208       -
  209       -
  210       -def test_build_delete_predicates_empty_and_dirty_input() -> None:
  211       -    assert build_delete_query([]) == ""
  212       -    assert build_delete_query(["", "  ", "a.py", "a.py"]) == "file_name IN ('a.py')"
  213       -
  214       -
  215       -# --------------------------------------------------------------------------- #
  216       -# shapes                                                                       #
  217       -# --------------------------------------------------------------------------- #
  218       -
  219       -
  220       -def test_push_file_set_is_frozen() -> None:
  221       -    files = PushFileSet(head_sha="x", added=["b.py", "a.py"])
  222       -    assert files.added == ["b.py", "a.py"]
  223       -    try:
  224       -        files.head_sha = "y"  # type: ignore[misc]
  225       -    except (ValueError, AttributeError):
  226       -        pass
  227       -    else:
  228       -        raise AssertionError("PushFileSet must be immutable")
  229       -
  230       -
  231       -def test_incremental_context_subclasses_index_context() -> None:
  232       -    ctx = IncrementalIndexContext(
  233       -        user_id="u1",
  234       -        sandbox_id="sbx",
  235       -        sandbox_name="incr-o-r",
  236       -        repo_owner="o",
  237       -        repo_name="r",
  238       -        repo_url="https://github.com/o/r.git",
  239       -        default_branch="main",
  240       -        repo_dir="/home/user/sentinel-workspace/r",
  241       -        ingest_script_path="/home/user/sentinel-workspace/context/incremental_ingestion.py",
  242       -        table_uri="s3://bucket/sentinel/lance/o/r",
  243       -        files_to_index=["a.py", "b.py"],
  244       -    )
  245       -    assert isinstance(ctx, IndexContext)
  246       -    assert ctx.files_to_index == ["a.py", "b.py"]
  247       -    assert ctx.batch_size == 50
  248       -
  249       -
  250       -def test_incremental_workflow_input_defaults() -> None:
  251       -    workflow_input = IncrementalIndexWorkflowInput(
  252       -        user_id="u1",
  253       -        repo_owner="o",
  254       -        repo_name="r",
  255       -        repo_url="https://github.com/o/r.git",
  256       -        local_repo_id="repo-1",
  257       -        head_sha="a" * 40,
  258       -    )
  259       -    assert workflow_input.files_to_delete == []
  260       -    assert workflow_input.files_to_index == []
  261       -    assert workflow_input.default_branch is None

```
