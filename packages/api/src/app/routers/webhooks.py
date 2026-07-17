"""GitHub App webhook receiver.

Verifies the ``X-Hub-Signature-256`` HMAC against
``settings.github_webhook_secret`` and routes the delivery by
``X-GitHub-Event``:

- ``ping`` -> 200, no DB.
- ``installation`` (action ``created``) -> no-op (the install-flow
  setup callback is the source of truth; see :mod:`app.routers.github`).
- ``installation`` (action ``deleted`` / ``suspend`` / ``unsuspend``)
  -> soft-delete or toggle the matching :class:`Installation` rows.
- ``installation_repositories`` (action ``added``) -> upsert one
  :class:`Repo` row per added repo. The owning ``user_id`` is
  recovered from the local :class:`Installation` row by
  ``github_installation_id`` (set up by the setup callback).
- ``installation_repositories`` (action ``removed``) -> delete the
  matching :class:`Repo` rows.
- ``pull_request`` (action ``opened``) -> delegate to
  :func:`app.services.review.webhook.handle_pull_request_opened`,
  which upserts the :class:`PullRequest` row and dispatches a
  background review run via FastAPI's ``BackgroundTasks``. Other
  ``pull_request`` actions are log + 202.
- anything else -> 202 with a log line.

The handler sits outside AuthMiddleware's protected prefixes: GitHub
calls this endpoint, not a logged-in user.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import Response
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.models.installation import Installation
from app.models.repo import Repo
from app.services.review import webhook as review_webhook
from app.utils.util import uuidToStr

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)

GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"
GITHUB_EVENT_HEADER = "X-GitHub-Event"
GITHUB_DELIVERY_HEADER = "X-GitHub-Delivery"
SIGNATURE_PREFIX = "sha256="


# --------------------------------------------------------------------------- #
# verification                                                                 #
# --------------------------------------------------------------------------- #


def _verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check.

    Returns ``False`` for any malformed input (missing header, wrong
    scheme, mismatched digest) - never raises. The caller is expected
    to treat the body as untrusted on a ``False`` result.
    """
    if not signature_header or not signature_header.startswith(SIGNATURE_PREFIX):
        return False
    provided = signature_header[len(SIGNATURE_PREFIX) :]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


# --------------------------------------------------------------------------- #
# summarizers                                                                  #
# --------------------------------------------------------------------------- #


def _summarize_pull_request(payload: dict[str, Any]) -> dict[str, Any]:
    repo = payload.get("repository") or {}
    owner = (repo.get("owner") or {}).get("login")
    name = repo.get("name")
    pr = payload.get("pull_request") or {}
    return {
        "repository": f"{owner}/{name}" if owner and name else None,
        "number": pr.get("number"),
        "sender": (payload.get("sender") or {}).get("login"),
    }


# --------------------------------------------------------------------------- #
# user resolution                                                              #
# --------------------------------------------------------------------------- #


async def _resolve_user_id_by_installation_id(
    github_installation_id: int,
) -> str | None:
    """Return the WorkOS ``user_id`` that owns the local installation row.

    The setup callback writes one :class:`Installation` row per
    ``(user_id, github_installation_id)`` pair, so a lookup by the
    GitHub-side id uniquely identifies the owner.
    """
    async with async_session_maker() as session:
        stmt = select(Installation.user_id).where(
            Installation.github_installation_id == github_installation_id,
            Installation.user_id.is_not(None),  # type: ignore[union-attr]
        )
        return (await session.exec(stmt)).first()


# --------------------------------------------------------------------------- #
# repo upsert                                                                  #
# --------------------------------------------------------------------------- #


async def _upsert_repo(
    session: AsyncSession, *, user_id: str, repo_payload: dict[str, Any]
) -> str:
    """Insert-or-fetch a Repo row for one GitHub repo object. Returns repo.id."""
    github_repo_id = repo_payload["id"]
    full_name = repo_payload["full_name"]
    owner, _, name = full_name.partition("/")

    stmt = select(Repo).where(Repo.github_repo_id == github_repo_id)
    repo = (await session.exec(stmt)).first()
    if repo is not None:
        return repo.id

    repo = Repo(
        id=uuidToStr(),
        user_id=user_id,
        github_repo_id=github_repo_id,
        repo_name=name,
        repo_owner=owner,
        clone_url=repo_payload.get("clone_url")
        or f"https://github.com/{full_name}.git",
        url=repo_payload.get("html_url"),
        private=repo_payload.get("private", False),
        default_branch=repo_payload.get("default_branch"),
    )
    session.add(repo)
    await session.flush()
    return repo.id


def _extract_repositories(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Pull the repo-object list from ``payload[key]``, dropping malformed entries."""
    raw = payload.get(key) or []
    return [
        r
        for r in raw
        if isinstance(r, dict)
        and isinstance(r.get("id"), int)
        and isinstance(r.get("full_name"), str)
    ]


# --------------------------------------------------------------------------- #
# installation event handlers                                                  #
# --------------------------------------------------------------------------- #


async def _handle_installation_created(payload: dict[str, Any]) -> Response:
    installation = payload.get("installation") or {}
    gh_installation_id = installation.get("id")
    account = (installation.get("account") or {}).get("login")
    log.info(
        "github_webhook: installation.created ignored (setup callback is source of truth) "
        "(github_installation_id=%s, account=%s)",
        gh_installation_id,
        account,
    )
    return Response(status_code=202)


async def _handle_installation_deleted(payload: dict[str, Any]) -> Response:
    installation = payload.get("installation") or {}
    gh_installation_id = installation.get("id")
    if not isinstance(gh_installation_id, int):
        log.warning("github_webhook: installation.deleted missing id")
        return Response(status_code=202)

    async with async_session_maker() as session:
        stmt = delete(Installation).where(
            Installation.github_installation_id == gh_installation_id  # pyright: ignore
        )
        await session.exec(stmt)
        await session.commit()

    log.info(
        "github_webhook: installation.deleted dropped %d row(s) "
        "(github_installation_id=%s)",
        gh_installation_id,
    )
    return Response(status_code=202)


async def _handle_installation_suspend(payload: dict[str, Any]) -> Response:
    installation = payload.get("installation") or {}
    gh_installation_id = installation.get("id")
    if not isinstance(gh_installation_id, int):
        return Response(status_code=202)
    now = datetime.now(UTC)
    async with async_session_maker() as session:
        stmt = select(Installation).where(
            Installation.github_installation_id == gh_installation_id,
        )
        rows = list((await session.exec(stmt)).all())
        for row in rows:
            row.suspended_at = now
            row.updated_at = now
            session.add(row)
        await session.commit()
    return Response(status_code=202)


async def _handle_installation_unsuspend(payload: dict[str, Any]) -> Response:
    installation = payload.get("installation") or {}
    gh_installation_id = installation.get("id")
    if not isinstance(gh_installation_id, int):
        return Response(status_code=202)
    now = datetime.now(UTC)
    async with async_session_maker() as session:
        stmt = select(Installation).where(
            Installation.github_installation_id == gh_installation_id,
        )
        rows = list((await session.exec(stmt)).all())
        for row in rows:
            row.suspended_at = None
            row.updated_at = now
            session.add(row)
        await session.commit()
    return Response(status_code=202)


async def _handle_installation_repositories_added(payload: dict[str, Any]) -> Response:
    installation = payload.get("installation") or {}
    gh_installation_id = installation.get("id")
    if not isinstance(gh_installation_id, int):
        return Response(status_code=202)

    repositories = _extract_repositories(payload, "repositories_added")
    if not repositories:
        return Response(status_code=202)

    user_id = await _resolve_user_id_by_installation_id(gh_installation_id)
    if user_id is None:
        log.info(
            "github_webhook: installation_repositories.added unowned "
            "(github_installation_id=%s, repos=%d)",
            gh_installation_id,
            len(repositories),
        )
        return Response(status_code=202)

    count = 0
    async with async_session_maker() as session:
        for repo_payload in repositories:
            await _upsert_repo(session, user_id=user_id, repo_payload=repo_payload)
            count += 1
        await session.commit()

    log.info(
        "github_webhook: installation_repositories.added upserted "
        "user_id=%s github_installation_id=%s repos=%d",
        user_id,
        gh_installation_id,
        count,
    )
    return Response(status_code=202)


async def _handle_installation_repositories_removed(
    payload: dict[str, Any],
) -> Response:
    installation = payload.get("installation") or {}
    gh_installation_id = installation.get("id")
    if not isinstance(gh_installation_id, int):
        return Response(status_code=202)

    removed = _extract_repositories(payload, "repositories_removed")
    if not removed:
        return Response(status_code=202)

    github_repo_ids = {r["id"] for r in removed}

    async with async_session_maker() as session:
        stmt = select(Repo).where(Repo.github_repo_id.in_(github_repo_ids))  # type: ignore[attr-defined]
        repos = list((await session.exec(stmt)).all())
        for repo in repos:
            await session.delete(repo)
        await session.commit()

    log.info(
        "github_webhook: installation_repositories.removed dropped %d repo row(s) "
        "(github_installation_id=%s, repos=%d)",
        len(repos),
        gh_installation_id,
        len(removed),
    )
    return Response(status_code=202)


# --------------------------------------------------------------------------- #
# main handler                                                                 #
# --------------------------------------------------------------------------- #


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    body = await request.body()

    if not settings.github_webhook_configured:
        log.warning("github_webhook: rejected (GITHUB_WEBHOOK_SECRET not set)")
        return Response(status_code=401)

    if not _verify_signature(
        settings.github_webhook_secret,
        body,
        request.headers.get(GITHUB_SIGNATURE_HEADER),
    ):
        log.warning(
            "github_webhook: rejected (bad signature, %d bytes)",
            len(body),
        )
        return Response(status_code=401)

    event = request.headers.get(GITHUB_EVENT_HEADER) or "unknown"
    delivery = request.headers.get(GITHUB_DELIVERY_HEADER) or "unknown"

    if event == "ping":
        log.info("github_webhook: ping accepted (delivery=%s)", delivery)
        return Response(status_code=200)

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        log.warning(
            "github_webhook: invalid JSON (delivery=%s, bytes=%d)",
            delivery,
            len(body),
        )
        return Response(status_code=202)

    if event == "installation":
        action = payload.get("action")
        log.info(
            "github_webhook: installation.%s (delivery=%s, account=%s, "
            "github_installation_id=%s)",
            action,
            delivery,
            ((payload.get("installation") or {}).get("account") or {}).get("login"),
            (payload.get("installation") or {}).get("id"),
        )
        if action == "created":
            return await _handle_installation_created(payload)
        if action == "deleted":
            return await _handle_installation_deleted(payload)
        if action == "suspend":
            return await _handle_installation_suspend(payload)
        if action == "unsuspend":
            return await _handle_installation_unsuspend(payload)
        return Response(status_code=202)

    if event == "installation_repositories":
        action = payload.get("action")
        log.info(
            "github_webhook: installation_repositories.%s (delivery=%s)",
            action,
            delivery,
        )
        if action == "added":
            return await _handle_installation_repositories_added(payload)
        if action == "removed":
            return await _handle_installation_repositories_removed(payload)
        return Response(status_code=202)

    if event == "pull_request":
        action = payload.get("action")
        # summary = _summarize_pull_request(payload)

        log.info(f"[pr_payload]:{payload}\n")

        if action == "opened" or action == "synchronize":
            ack = await review_webhook.handle_pull_request_opened(
                payload, delivery, background_tasks=background_tasks
            )
            log.info("github_webhook: pull_request handled: %s", ack.model_dump_json())
        return Response(status_code=202)

    log.info(
        "github_webhook: ignored event=%s (delivery=%s, bytes=%d)",
        event,
        delivery,
        len(body),
    )
    return Response(status_code=202)
