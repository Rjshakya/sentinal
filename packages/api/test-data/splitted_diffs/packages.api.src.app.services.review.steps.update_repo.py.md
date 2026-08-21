### packages/api/src/app/services/review/steps/update_repo.py

```diff

deleted file mode 100644
index 1dfe396..0000000
--- a/packages/api/src/app/services/review/steps/update_repo.py
+++ /dev/null
@@ -1,157 +0,0 @@
    2       -"""DBOS durable step: refresh the sandbox repo to the default branch.
    3       -
    4       -The sandbox working tree is left at whatever commit the setup-time
    5       -``git clone`` checked out, so on every later review the on-disk files
    6       -are stale relative to the merged history. :func:`update_repo_step`
    7       -reconnects to the sandbox, fetches the default branch, and hard-resets
    8       -the working tree to its remote tip — giving the review agents fresh
    9       -``read_file`` context. The unified diff itself is SHA-based
   10       -(``git diff base_sha...head_sha`` in :mod:`app.services.review.diff`),
   11       -so it is unaffected by the working tree state.
   12       -
   13       -``git reset --hard`` (rather than ``checkout`` + ``pull``) is the
   14       -deterministic "make the working tree equal the remote branch tip"
   15       -operation: it survives dirty trees, divergent local branches, and
   16       -missing tracking configuration, and it discards any local changes the
   17       -agents may have left behind (the sandbox is a scratch space, never a
   18       -source of truth).
   19       -"""
   20       -
   21       -from __future__ import annotations
   22       -
   23       -import logging
   24       -
   25       -from dbos import DBOS
   26       -
   27       -from app.core.sandbox import BaseSandbox
   28       -from app.core.sandbox.e2b import E2BSandbox
   29       -from app.services.review._internal import _SHOULD_RETRY_TRANSIENT, _e2b_spec
   30       -from app.services.review.diff import truncate_diff_output
   31       -from app.services.review.errors import RepoUpdateError, SandboxConnectError
   32       -from app.services.review.helpers import get_repo_path
   33       -
   34       -log = logging.getLogger(__name__)
   35       -
   36       -FETCH_TIMEOUT_S: float = 120.0
   37       -"""Upper bound on the wall-clock duration of ``git fetch``."""
   38       -RESET_TIMEOUT_S: float = 120.0
   39       -"""Upper bound on the wall-clock duration of ``git reset --hard``."""
   40       -
   41       -
   42       -async def update_repo(
   43       -    *,
   44       -    sandbox: BaseSandbox,
   45       -    repo_id: str,
   46       -    repo_path_str: str,
   47       -    default_branch: str,
   48       -) -> None:
   49       -    """Fetch the default branch and hard-reset the working tree to it.
   50       -
   51       -    Runs ``git fetch origin <default_branch>`` followed by
   52       -    ``git reset --hard origin/<default_branch>`` inside the sandbox.
   53       -
   54       -    Raises:
   55       -        RepoUpdateError: when either sub-command returns a non-zero
   56       -            exit code. Business outcome — not retried.
   57       -    """
   58       -    fetch = await sandbox.execute(
   59       -        f"git fetch origin {default_branch}",
   60       -        cwd=repo_path_str,
   61       -        timeout=FETCH_TIMEOUT_S,
   62       -    )
   63       -    if fetch.exit_code != 0:
   64       -        raise RepoUpdateError(
   65       -            repo_id=repo_id,
   66       -            branch=default_branch,
   67       -            cause=f"git fetch exited {fetch.exit_code}: "
   68       -            f"{truncate_diff_output(fetch.stderr or fetch.stdout or '')}",
   69       -        )
   70       -
   71       -    reset = await sandbox.execute(
   72       -        f"git reset --hard origin/{default_branch}",
   73       -        cwd=repo_path_str,
   74       -        timeout=RESET_TIMEOUT_S,
   75       -    )
   76       -    if reset.exit_code != 0:
   77       -        raise RepoUpdateError(
   78       -            repo_id=repo_id,
   79       -            branch=default_branch,
   80       -            cause=f"git reset exited {reset.exit_code}: "
   81       -            f"{truncate_diff_output(reset.stderr or reset.stdout or '')}",
   82       -        )
   83       -
   84       -    log.info(
   85       -        "Updated repo to default branch: repo_id=%s branch=%s",
   86       -        repo_id,
   87       -        default_branch,
   88       -    )
   89       -
   90       -
   91       -@DBOS.step(
   92       -    retries_allowed=True,
   93       -    max_attempts=3,
   94       -    should_retry=_SHOULD_RETRY_TRANSIENT,
   95       -)
   96       -async def update_repo_step(
   97       -    *,
   98       -    sandbox_id: str,
   99       -    sandbox_name: str,
  100       -    repo_id: str,
  101       -    repo_name: str,
  102       -    user_id: str,
  103       -    default_branch: str | None,
  104       -) -> None:
  105       -    """Durable step: reconnect to the sandbox and refresh the repo tree.
  106       -
  107       -    When ``default_branch`` is ``None`` (the repo row has no recorded
  108       -    default branch) the step is a no-op — the review still works
  109       -    because the diff is computed from explicit SHAs.
  110       -
  111       -    Raises:
  112       -        SandboxConnectError: reconnect to E2B failed.
  113       -            :class:`TransientStepError` — DBOS retries.
  114       -        RepoUpdateError: ``git fetch`` / ``git reset`` returned a
  115       -            non-zero exit code. Business outcome — not retried.
  116       -    """
  117       -    if default_branch is None:
  118       -        log.info(
  119       -            "update_repo_step: skipped (no default branch on repo row): "
  120       -            "repo_id=%s",
  121       -            repo_id,
  122       -        )
  123       -        return
  124       -
  125       -    spec = _e2b_spec()
  126       -    try:
  127       -        sandbox = await E2BSandbox.connect(
  128       -            sandbox_id=sandbox_id,
  129       -            sandbox_name=sandbox_name,
  130       -            repo_id=repo_id,
  131       -            user_id=user_id,
  132       -            spec=spec,
  133       -            timeout=60 * 60,
  134       -            api_key=spec.api_key,
  135       -        )
  136       -    except Exception as exc:
  137       -        raise SandboxConnectError(
  138       -            user_id=user_id,
  139       -            repo_id=repo_id,
  140       -            sandbox_id=sandbox_id,
  141       -            cause=f"failed to reconnect sandbox for repo update: {type(exc).__name__}: {exc}",
  142       -        ) from exc
  143       -
  144       -    try:
  145       -        await update_repo(
  146       -            sandbox=sandbox,
  147       -            repo_id=repo_id,
  148       -            repo_path_str=get_repo_path(repo_name),
  149       -            default_branch=default_branch,
  150       -        )
  151       -    finally:
  152       -        try:
  153       -            await sandbox.stop()
  154       -        except Exception:
  155       -            log.exception("failed to stop sandbox after repo update")
  156       -
  157       -
  158       -__all__ = ["update_repo", "update_repo_step"]
\ No newline at end of file

```
