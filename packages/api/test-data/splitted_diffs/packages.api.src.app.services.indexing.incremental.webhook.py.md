### packages/api/src/app/services/indexing/incremental/webhook.py

```diff

deleted file mode 100644
index 83717dd..0000000
--- a/packages/api/src/app/services/indexing/incremental/webhook.py
+++ /dev/null
@@ -1,274 +0,0 @@
    2       -"""GitHub ``push`` webhook adapter for the incremental indexing workflow.
    3       -
    4       -Dispatches a verified default-branch push delivery to the DBOS
    5       -incremental workflow. Mirrors the ring structure of
    6       -:mod:`app.services.review.webhook`:
    7       -
    8       -- **Ring 1 (pure)**       — :func:`push_skip_reason`,
    9       -  :func:`extract_push_files`, :func:`incremental_workflow_id`. No I/O.
   10       -- **Ring 2 (orchestrator)** — :func:`handle_push_event`. The single
   11       -  public entry point. Sequences the DB lookups, the config
   12       -  preconditions, and the workflow dispatch.
   13       -- **Ring 3 (DB shell)**   — :func:`resolve_installation_owner`,
   14       -  :func:`resolve_installed_repo`. Each is the single boundary into the
   15       -  database.
   16       -
   17       -Every skip path returns a :class:`PushWebhookAck` with
   18       -``accepted=False`` and a ``skip_reason``; the handler never raises so
   19       -the router can always reply ``202``.
   20       -"""
   21       -
   22       -from __future__ import annotations
   23       -
   24       -import logging
   25       -from typing import Any
   26       -
   27       -from dbos import DBOS, SetWorkflowID
   28       -from pydantic import BaseModel
   29       -from sqlmodel import select
   30       -
   31       -from app.core.db import async_session_maker
   32       -from app.models.installation import Installation
   33       -from app.models.repo import Repo
   34       -from app.services.indexing.incremental.helpers import (
   35       -    extract_push_files,
   36       -    incremental_workflow_id,
   37       -    push_skip_reason,
   38       -)
   39       -from app.services.indexing.incremental.types import IncrementalIndexWorkflowInput
   40       -from app.services.indexing.incremental.workflow import incrementalIndexRepo
   41       -
   42       -log = logging.getLogger(__name__)
   43       -
   44       -
   45       -# --------------------------------------------------------------------------- #
   46       -# ack                                                                          #
   47       -# --------------------------------------------------------------------------- #
   48       -
   49       -
   50       -class PushWebhookAck(BaseModel):
   51       -    """What the orchestrator hands back to the router for logging.
   52       -
   53       -    The router logs the dumped JSON; the response body to GitHub is
   54       -    always ``202 Accepted`` regardless of ``accepted``.
   55       -    """
   56       -
   57       -    accepted: bool
   58       -    action: str = "push"
   59       -    delivery: str
   60       -    skip_reason: str | None = None
   61       -
   62       -
   63       -# --------------------------------------------------------------------------- #
   64       -# Ring 3 — DB shell                                                            #
   65       -# --------------------------------------------------------------------------- #
   66       -
   67       -
   68       -async def resolve_installation_owner(github_installation_id: int) -> str | None:
   69       -    """Return the WorkOS ``user_id`` that owns the installation, or ``None``."""
   70       -    async with async_session_maker() as session:
   71       -        stmt = select(Installation.user_id).where(
   72       -            Installation.github_installation_id == github_installation_id,
   73       -            Installation.user_id.is_not(None),  # type: ignore[union-attr]
   74       -        )
   75       -        return (await session.exec(stmt)).first()
   76       -
   77       -
   78       -async def resolve_installed_repo(
   79       -    *,
   80       -    user_id: str,
   81       -    repo_owner: str,
   82       -    repo_name: str,
   83       -) -> Repo | None:
   84       -    """Return the local :class:`Repo` row for ``user_id``'s installed repo."""
   85       -    async with async_session_maker() as session:
   86       -        stmt = select(Repo).where(
   87       -            Repo.user_id == user_id,
   88       -            Repo.repo_owner == repo_owner,
   89       -            Repo.repo_name == repo_name,
   90       -        )
   91       -        return (await session.exec(stmt)).first()
   92       -
   93       -
   94       -# --------------------------------------------------------------------------- #
   95       -# Ring 2 — orchestrator                                                        #
   96       -# --------------------------------------------------------------------------- #
   97       -
   98       -
   99       -async def handle_push_event(
  100       -    payload: dict[str, Any],
  101       -    delivery: str,
  102       -) -> PushWebhookAck:
  103       -    """Dispatch a verified ``push`` delivery to the incremental workflow.
  104       -
  105       -    The router calls this once per delivery that has already passed
  106       -    signature verification. Skip reasons (all return ``accepted=False``):
  107       -
  108       -    ``malformed_payload``, ``not_default_branch``, ``deleted_push``,
  109       -    ``created_push``, ``missing_head_commit``, ``malformed_installation``,
  110       -    ``unowned_installation``, ``repo_not_configured``,
  111       -    ``repo_not_indexed``, ``indexing_not_configured``, ``no_file_changes``.
  112       -    """
  113       -    skip_reason = push_skip_reason(payload)
  114       -    if skip_reason is not None:
  115       -        return PushWebhookAck(
  116       -            accepted=False,
  117       -            delivery=delivery,
  118       -            skip_reason=skip_reason,
  119       -        )
  120       -
  121       -    files = extract_push_files(payload)
  122       -    if files is None:
  123       -        log.info(
  124       -            "incremental.webhook: skip (missing head commit): delivery=%s",
  125       -            delivery,
  126       -        )
  127       -        return PushWebhookAck(
  128       -            accepted=False,
  129       -            delivery=delivery,
  130       -            skip_reason="missing_head_commit",
  131       -        )
  132       -
  133       -    installation = payload.get("installation") or {}
  134       -    installation_id = installation.get("id")
  135       -    if not isinstance(installation_id, int):
  136       -        log.info(
  137       -            "incremental.webhook: skip (malformed installation): delivery=%s",
  138       -            delivery,
  139       -        )
  140       -        return PushWebhookAck(
  141       -            accepted=False,
  142       -            delivery=delivery,
  143       -            skip_reason="malformed_installation",
  144       -        )
  145       -
  146       -    repo = payload.get("repository") or {}
  147       -    owner = ((repo.get("owner") or {}).get("login")) if isinstance(repo, dict) else None
  148       -    name = repo.get("name") if isinstance(repo, dict) else None
  149       -    if not isinstance(owner, str) or not isinstance(name, str):
  150       -        log.info(
  151       -            "incremental.webhook: skip (malformed repository): delivery=%s",
  152       -            delivery,
  153       -        )
  154       -        return PushWebhookAck(
  155       -            accepted=False,
  156       -            delivery=delivery,
  157       -            skip_reason="malformed_payload",
  158       -        )
  159       -
  160       -    user_id = await resolve_installation_owner(installation_id)
  161       -    if user_id is None:
  162       -        log.info(
  163       -            "incremental.webhook: skip (unowned installation): delivery=%s "
  164       -            "github_installation_id=%s owner=%s repo=%s",
  165       -            delivery,
  166       -            installation_id,
  167       -            owner,
  168       -            name,
  169       -        )
  170       -        return PushWebhookAck(
  171       -            accepted=False,
  172       -            delivery=delivery,
  173       -            skip_reason="unowned_installation",
  174       -        )
  175       -
  176       -    installed_repo = await resolve_installed_repo(
  177       -        user_id=user_id,
  178       -        repo_owner=owner,
  179       -        repo_name=name,
  180       -    )
  181       -    if installed_repo is None:
  182       -        log.info(
  183       -            "incremental.webhook: skip (repo not installed): delivery=%s "
  184       -            "user_id=%s owner=%s repo=%s",
  185       -            delivery,
  186       -            user_id,
  187       -            owner,
  188       -            name,
  189       -        )
  190       -        return PushWebhookAck(
  191       -            accepted=False,
  192       -            delivery=delivery,
  193       -            skip_reason="repo_not_configured",
  194       -        )
  195       -
  196       -    # A repo that never completed a full index has no dataset yet — the
  197       -    # full index (setup auto-dispatch or the dashboard button) owns the
  198       -    # bootstrap. Incremental runs must not create the table.
  199       -    if not installed_repo.is_indexed:
  200       -        log.info(
  201       -            "incremental.webhook: skip (repo not indexed yet): delivery=%s "
  202       -            "owner=%s repo=%s",
  203       -            delivery,
  204       -            owner,
  205       -            name,
  206       -        )
  207       -        return PushWebhookAck(
  208       -            accepted=False,
  209       -            delivery=delivery,
  210       -            skip_reason="repo_not_indexed",
  211       -        )
  212       -
  213       -    files_to_delete = sorted(set(files.removed) | set(files.modified))
  214       -    files_to_index = sorted(set(files.added) | set(files.modified))
  215       -    if not files_to_delete and not files_to_index:
  216       -        log.info(
  217       -            "incremental.webhook: skip (no file changes): delivery=%s "
  218       -            "owner=%s repo=%s head_sha=%s",
  219       -            delivery,
  220       -            owner,
  221       -            name,
  222       -            files.head_sha,
  223       -        )
  224       -        return PushWebhookAck(
  225       -            accepted=False,
  226       -            delivery=delivery,
  227       -            skip_reason="no_file_changes",
  228       -        )
  229       -
  230       -    default_branch = repo.get("default_branch") if isinstance(repo, dict) else None
  231       -    clone_url = repo.get("clone_url") if isinstance(repo, dict) else None
  232       -    repo_url = (
  233       -        clone_url
  234       -        if isinstance(clone_url, str)
  235       -        else f"https://github.com/{owner}/{name}.git"
  236       -    )
  237       -
  238       -    workflow_input = IncrementalIndexWorkflowInput(
  239       -        user_id=user_id,
  240       -        repo_owner=owner,
  241       -        repo_name=name,
  242       -        repo_url=repo_url,
  243       -        default_branch=default_branch if isinstance(default_branch, str) else None,
  244       -        local_repo_id=installed_repo.id,
  245       -        head_sha=files.head_sha,
  246       -        files_to_delete=files_to_delete,
  247       -        files_to_index=files_to_index,
  248       -    )
  249       -
  250       -    workflow_id = incremental_workflow_id(owner, name, files.head_sha)
  251       -
  252       -    log.info(
  253       -        "incremental.webhook: starting workflow: delivery=%s workflow_id=%s "
  254       -        "owner=%s repo=%s head_sha=%s delete=%d index=%d",
  255       -        delivery,
  256       -        workflow_id,
  257       -        owner,
  258       -        name,
  259       -        files.head_sha,
  260       -        len(files_to_delete),
  261       -        len(files_to_index),
  262       -    )
  263       -
  264       -    with SetWorkflowID(workflow_id):
  265       -        await DBOS.start_workflow_async(incrementalIndexRepo, workflow_input)
  266       -
  267       -    return PushWebhookAck(accepted=True, delivery=delivery)
  268       -
  269       -
  270       -__all__ = [
  271       -    "PushWebhookAck",
  272       -    "handle_push_event",
  273       -    "resolve_installation_owner",
  274       -    "resolve_installed_repo",
  275       -]

```
