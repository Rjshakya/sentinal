"""GitHub App routes.

- ``GET /api/github/installation`` — list every installation the
  signed-in user has. Returns ``connected: false`` with an empty
  list when the user has none.
- ``GET /api/github/repos`` — live pass-through. Groups the user's
  installations by ``github_installation_id`` and calls
  ``GET /installation/repositories`` for each via the
  installation-scoped client, then merges the results. The local
  :class:`Installation` row's id (``installation_id``) is attached to
  every repo so the client can round-trip it back to the indexing
  endpoint.
- ``DELETE /api/github/installation/{installation_id}`` — local
  "Forget". Deletes the matching :class:`Installation` rows and
  cascades to the ``repos`` they referenced. The user still has to
  uninstall the App on github.com separately.
- ``GET /api/github/install-url`` — mints a server-signed GitHub App
  install URL for the signed-in user. The ``state`` parameter is an
  HMAC-signed token that round-trips the WorkOS ``user_id`` through
  GitHub's install → setup-URL redirect.
- ``GET /api/github/setup`` — GitHub's redirect target after a
  successful install. Verifies the state, fetches the installation
  details from GitHub, upserts the local :class:`Installation` row,
  and 302s back to the dashboard. Sits outside ``AuthMiddleware``'s
  protected prefixes; carries no session.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.github_app import get_installation, list_installation_repos
from app.core.install_state import sign as sign_install_state
from app.core.install_state import verify as verify_install_state
from app.models.installation import Installation
from app.models.repo import Repo
from app.utils.util import uuidToStr

log = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


# --------------------------------------------------------------------------- #
# response models                                                              #
# --------------------------------------------------------------------------- #


class InstallationOut(BaseModel):
    installation_id: str
    github_installation_id: int
    account_login: str
    account_type: str
    repository_selection: str
    suspended: bool
    repo_count: int


class InstallationStateOut(BaseModel):
    connected: bool
    installation_count: int
    installations: list[InstallationOut]


class RepoOut(BaseModel):
    id: int
    name: str
    full_name: str
    owner: str | None
    private: bool
    description: str | None
    default_branch: str
    html_url: str
    stargazers_count: int
    language: str | None
    updated_at: datetime | None
    clone_url: str
    installation_id: str
    github_installation_id: int
    is_configured: bool = Field(
        default=False,
        description=(
            "True when a row with this github_repo_id exists in the "
            "local 'repo' table for the calling user. The dashboard "
            "uses this to mark already-configured repos in the list "
            "and exclude them from the configure payload."
        ),
    )
    is_indexed: bool = Field(
        default=False,
        description=(
            "True when the latest :class:`IndexRun` for this repo "
            "completed with ``state=SUCCESS``. ``False`` for never-"
            "indexed repos, repos whose last index run errored, or "
            "repos not yet configured on the local side. Computed "
            "at the boundary from :attr:`Repo.is_indexed` "
            "(``None`` is coerced to ``False``)."
        ),
    )


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #


async def _load_user_installations(
    session: AsyncSession, user_id: str
) -> list[Installation]:
    stmt = (
        select(Installation)
        .where(Installation.user_id == user_id)
        .order_by(Installation.created_at.asc())  # type: ignore[attr-defined]
    )
    return list((await session.exec(stmt)).all())


async def _load_user_repo_count(session: AsyncSession, user_id: str) -> int:
    """Count every :class:`Repo` row belonging to ``user_id``.

    ``Repo`` rows are user-scoped, not installation-scoped, so this
    total is the same on every installation of the same user.
    """
    stmt = select(func.count()).select_from(Repo).where(Repo.user_id == user_id)
    return int((await session.exec(stmt)).one() or 0)


def _summarize(
    installations: list[Installation], repo_count: int
) -> list[InstallationOut]:
    return [
        InstallationOut(
            installation_id=inst.id,
            github_installation_id=inst.github_installation_id,
            account_login=inst.account_login,
            account_type=inst.account_type,
            repository_selection=inst.repository_selection,
            suspended=inst.suspended_at is not None,
            repo_count=repo_count,
        )
        for inst in installations
    ]


# --------------------------------------------------------------------------- #
# endpoints                                                                    #
# --------------------------------------------------------------------------- #


@router.get("/installation", response_model=InstallationStateOut)
async def list_my_installations(request: Request) -> InstallationStateOut:
    user_id = request.state.user_id
    async with async_session_maker() as session:
        rows = await _load_user_installations(session, user_id)
        repo_count = await _load_user_repo_count(session, user_id)
    return InstallationStateOut(
        connected=bool(rows),
        installation_count=len(rows),
        installations=_summarize(rows, repo_count),
    )


@router.get("/repos", response_model=list[RepoOut])
async def list_installation_repos_route(request: Request) -> list[RepoOut]:
    """Live pass-through — no DB read.

    For every installation the user has, call
    ``GET /installation/repositories`` and merge. Repos are deduplicated
    by GitHub ``id`` (a repo accessible via two installations appears
    once, attributed to the first installation that surfaces it).
    """
    user_id = request.state.user_id
    async with async_session_maker() as session:
        installations = await _load_user_installations(session, user_id)

    if not installations:
        return []

    seen: dict[int, RepoOut] = {}
    errors: list[str] = []
    for inst in installations:
        if inst.suspended_at is not None:
            continue
        try:
            repos = await list_installation_repos(inst.github_installation_id)
        except Exception as exc:
            log.warning(
                "list_installation_repos failed for installation_id=%s: %s",
                inst.github_installation_id,
                exc,
            )
            errors.append(str(inst.github_installation_id))
            continue
        for r in repos:
            gh_id = r.id
            if gh_id in seen:
                continue
            seen[gh_id] = RepoOut(
                id=gh_id,
                name=r.name,
                full_name=r.full_name,
                owner=r.owner,
                private=r.private,
                description=r.description,
                default_branch=r.default_branch,
                html_url=r.html_url,
                stargazers_count=r.stargazers_count,
                language=r.language,
                updated_at=r.updated_at,
                clone_url=r.clone_url,
                installation_id=inst.id,
                github_installation_id=inst.github_installation_id,
            )

    if errors and not seen:
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to list GitHub repos for any installation. "
                f"installation_ids attempted: {', '.join(errors)}"
            ),
        )

    # Cross-reference the merged GitHub-side repo list with the
    # local ``repo`` table to flag which ones the user has already
    # started configuring and to surface the indexing mirror
    # (``is_indexed``) of each local row. One indexed
    # ``SELECT … WHERE github_repo_id IN (…)`` keyed on
    # ``Repo.github_repo_id`` (UNIQUE) and ``Repo.user_id``
    # (indexed). ``is_indexed`` is coerced ``None → False`` at the
    # boundary so the response shape stays a strict ``bool``.
    if seen:
        async with async_session_maker() as session:
            stmt = select(Repo.github_repo_id, Repo.is_indexed).where(
                Repo.user_id == user_id,
                Repo.github_repo_id.in_(list(seen.keys())),  # type: ignore[attr-defined]
            )
            local_state: dict[int, bool] = {
                row[0]: bool(row[1]) if row[1] is not None else False
                for row in (await session.exec(stmt)).all()
            }
        for r in seen.values():
            r.is_configured = r.id in local_state
            r.is_indexed = local_state.get(r.id, False)

    return list(seen.values())


@router.delete("/installation/{installation_id}", status_code=204)
async def forget_installation(
    request: Request,
    installation_id: Annotated[str, Path()],
) -> None:
    """Locally "forget" an installation.

    Deletes every :class:`Installation` row whose ``id`` matches and


    The user still has to uninstall the GitHub App on
    ``github.com/settings/installations`` to fully revoke Sentinel's
    access.
    """
    user_id = request.state.user_id
    async with async_session_maker() as session:
        delete_installations = delete(Installation).where(
            Installation.id == installation_id,  # pyright: ignore
            Installation.user_id == user_id,
        )
        result = await session.exec(delete_installations)
        await session.commit()

        deleted_count = result.rowcount
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="Installation not found")

    log.info(
        "forget_installation: deleted %d installation row(s) (installation_id=%s, user_id=%s)",
        deleted_count,
        installation_id,
        user_id,
    )


# --------------------------------------------------------------------------- #
# install flow                                                                 #
# --------------------------------------------------------------------------- #


class InstallUrlOut(BaseModel):
    url: str


@router.get("/install-url", response_model=InstallUrlOut)
async def get_install_url(request: Request) -> InstallUrlOut:
    """Mint a GitHub App install URL with a server-signed ``state``.

    The dashboard opens this URL in a new tab. After the user completes
    the install on github.com, GitHub redirects the browser to the
    App's configured Setup URL (see :func:`setup_callback`) with
    ``installation_id`` and the same ``state`` appended. The setup
    callback verifies the signature, recovers the WorkOS ``user_id``,
    and upserts the local :class:`Installation` row.
    """
    user_id: str = request.state.user_id
    secret = settings.github_install_state_secret
    if not settings.github_app_configured or not secret:
        raise HTTPException(
            status_code=503,
            detail="GitHub App is not fully configured",
        )

    state = sign_install_state(user_id, secret)
    slug = settings.github_app_slug
    url = f"https://github.com/apps/{slug}/installations/new?state={quote(state, safe='')}"
    return InstallUrlOut(url=url)


def _setup_redirect(
    reason: str | None = None, setup_action: str | None = None
) -> Response:
    """Build the post-setup 302 to the dashboard with the result encoded."""
    outcome = "failed" if reason else "success"
    parts = [f"installation={outcome}"]
    if reason:
        parts.append(f"reason={quote(reason, safe='')}")
    if setup_action:
        parts.append(f"setup_action={quote(setup_action, safe='')}")
    target = f"{settings.frontend_url.rstrip('/')}/dashboard?{'&'.join(parts)}"
    return Response(status_code=302, headers={"Location": target})


async def _upsert_installation(
    *,
    user_id: str,
    github_installation_id: int,
    account_login: str,
    account_type: str,
    repository_selection: str,
    suspended_at: datetime | None,
) -> bool:
    """Insert-or-update the account-level :class:`Installation` row.

    Returns ``True`` when a new row was created, ``False`` when an
    existing row was updated. The unique-on-``(user_id,
    github_installation_id)`` invariant is enforced at the DB level
    (see the matching alembic revision); the implementation does a
    select-then-insert/update to stay safe even before the constraint
    exists in dev.
    """
    now = datetime.now(UTC)
    async with async_session_maker() as session:
        stmt = select(Installation).where(
            Installation.user_id == user_id,
            Installation.github_installation_id == github_installation_id,
        )
        existing = (await session.exec(stmt)).first()
        if existing is not None:
            existing.account_login = account_login
            existing.account_type = account_type
            existing.repository_selection = repository_selection
            existing.suspended_at = suspended_at
            existing.updated_at = now
            session.add(existing)
            await session.commit()
            return False

        session.add(
            Installation(
                id=uuidToStr(),
                user_id=user_id,
                github_installation_id=github_installation_id,
                account_login=account_login,
                account_type=account_type,
                repository_selection=repository_selection,
                suspended_at=suspended_at,
            )
        )
        await session.commit()
        return True


@router.get("/setup")
async def setup_callback(
    installation_id: Annotated[int, Query(ge=1)],
    state: Annotated[str, Query(min_length=1)],
    setup_action: Annotated[str | None, Query()] = None,
) -> Response:
    """GitHub's redirect target after a successful App install.

    Verifies the HMAC-signed ``state``, fetches the installation
    details from GitHub via :func:`get_installation`, upserts the
    local :class:`Installation` row, and 302s to the dashboard with
    ``?installation=success|failed`` so the new tab can toast the
    outcome.

    The endpoint is intentionally outside ``AuthMiddleware``'s
    protected prefixes — GitHub calls it via a user-agent redirect
    and no session cookie is present.
    """
    if not settings.github_app_configured:
        log.warning("github_setup: rejected (GitHub App not configured)")
        return _setup_redirect(reason="app_not_configured", setup_action=setup_action)

    secret = settings.github_install_state_secret
    user_id = None
    if secret:
        user_id = verify_install_state(state, secret)
    if not user_id:
        log.warning(
            "github_setup: rejected (bad state, installation_id=%s)", installation_id
        )
        return _setup_redirect(reason="bad_state", setup_action=setup_action)

    try:
        details = await get_installation(installation_id)
    except Exception as exc:
        log.warning(
            "github_setup: get_installation failed (installation_id=%s, user_id=%s): %s",
            installation_id,
            user_id,
            exc,
        )
        return _setup_redirect(reason="github_fetch_failed", setup_action=setup_action)

    if details.id != installation_id:
        log.warning(
            "github_setup: installation id mismatch (queried=%s, returned=%s, user_id=%s)",
            installation_id,
            details.id,
            user_id,
        )
        return _setup_redirect(reason="id_mismatch", setup_action=setup_action)

    try:
        created = await _upsert_installation(
            user_id=user_id,
            github_installation_id=details.id,
            account_login=details.account_login,
            account_type=details.account_type,
            repository_selection=details.repository_selection,
            suspended_at=details.suspended_at,
        )
    except Exception as exc:
        log.warning(
            "github_setup: upsert failed (installation_id=%s, user_id=%s): %s",
            details.id,
            user_id,
            exc,
        )
        return _setup_redirect(reason="db_write_failed", setup_action=setup_action)

    log.info(
        "github_setup: %s installation_id=%s account=%s user_id=%s setup_action=%s",
        "created" if created else "updated",
        details.id,
        details.account_login,
        user_id,
        setup_action,
    )
    return _setup_redirect(setup_action=setup_action)
