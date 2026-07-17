"""GitHub ``pull_request`` webhook adapter for the review pipeline.

Layered on top of :mod:`app.services.review.pipeline` so the existing
``pipeline.run`` does not need to know about FastAPI, BackgroundTasks,
or GitHub's payload shape. Mirrors the three-ring layout used in
:mod:`app.services.review.pipeline` and
:mod:`app.services.agent.setup_pipeline` — no classes, only functions.

- **Ring 1 (pure)**       — :class:`PRReviewInput`,
  :func:`classify_action`, :func:`extract_payload`,
  :func:`build_review_input`. No I/O, no session, no clock. Testable
  in isolation.

- **Ring 2 (orchestrator)** — :func:`handle_pull_request_opened`. The
  single public entry point. Sequences the DB lookups, the config
  preconditions, and the background dispatch. Single outer
  ``try / except`` keeps the request handler from ever raising out
  of this module.

- **Ring 3 (shell / background)** — :func:`resolve_user_id`,
  :func:`resolve_repo_id`, :func:`trigger_review`. Each is the
  single boundary into an external system (DB or pipeline) and is
  the only place that catches the underlying SDK's exceptions.

The public entry point :func:`handle_pull_request_opened` is the
only function the :mod:`app.routers.webhooks` router needs to call
for a ``pull_request`` ``opened`` delivery.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, cast

from pydantic import BaseModel, ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.result import Err
from app.core.sandbox import build_default_spec
from app.core.sandbox.e2b import E2BSandboxSpec
from app.models.enums import PRStatus
from app.models.installation import Installation
from app.models.repo import Repo
from app.services.review import pipeline
from app.services.review.pipeline import LLMProviderStr, flatten_review_error_to_message

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# ack                                                                          #
# --------------------------------------------------------------------------- #


class WebhookAck(BaseModel):
    """What the orchestrator hands back to the router for logging.

    The router logs the dumped JSON; the response body to GitHub is
    always ``202 Accepted`` regardless of ``accepted``.
    """

    accepted: bool
    action: str
    delivery: str
    skip_reason: str | None = None


# --------------------------------------------------------------------------- #
# Ring 1 — pure helpers                                                        #
# --------------------------------------------------------------------------- #


class PRReviewInput(BaseModel):
    """Flat, typed view of a verified ``pull_request`` ``opened`` payload.

    The single contract :func:`build_review_input` and
    :func:`trigger_review` depend on. Field types mirror GitHub's
    payload: numeric ids stay ``int``; ``body`` is optional.
    """

    gh_repo_id: int
    gh_pr_id: int
    number: int
    base_branch: str
    base_sha: str
    head_branch: str
    head_sha: str
    author: str
    title: str
    body: str | None = None
    status: PRStatus


# _TRIGGERED_ACTION: str = "opened"


def classify_action(action: Any) -> bool:
    """Return ``True`` iff ``action`` is the string ``"opened" or "synchronize"``."""
    return action == "opened" or action == "synchronize"


def _classify_status(pr: dict[str, Any]) -> str | None:
    state = pr.get("state")
    if state == "open":
        return PRStatus.OPEN
    if state == "closed":
        return PRStatus.MERGED if pr.get("merged") else PRStatus.CLOSED
    return None


def extract_payload(payload: dict[str, Any]) -> PRReviewInput | None:
    """Project the GitHub ``pull_request`` payload onto a typed view.

    Returns ``None`` on any malformed input — the orchestrator folds
    that into a ``skip_reason="malformed_payload"`` ack. Never raises:
    a :class:`ValidationError` from :meth:`PRReviewInput.model_validate`
    is caught and folded into the same ``None`` return.
    """
    repo = payload.get("repository") or {}
    pr = payload.get("pull_request") or {}
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    user = pr.get("user") or {}

    flat: dict[str, Any] = {
        "gh_repo_id": repo.get("id"),
        "gh_pr_id": pr.get("id"),
        "number": pr.get("number"),
        "base_branch": base.get("ref"),
        "base_sha": base.get("sha"),
        "head_branch": head.get("ref"),
        "head_sha": head.get("sha"),
        "author": user.get("login"),
        "title": pr.get("title"),
        "body": pr.get("body"),
        "status": _classify_status(pr),
    }
    try:
        return PRReviewInput.model_validate(flat)
    except ValidationError:
        return None


def build_review_input(
    view: PRReviewInput,
    *,
    user_id: str,
    session: Any,
    spec: E2BSandboxSpec,
    llm_provider: LLMProviderStr,
    llm_base_url: str | None,
    llm_api_key: str,
    llm_model: str,
    github_installation_id: int | None = None,
    post_to_github: bool = False,
) -> pipeline.Input:
    """Translate the view + LLM/sandbox config into a ``pipeline.Input``.

    Pure mapping: every field comes from the view, the args, or
    settings via the caller. ``session`` is passed in (rather than
    opened here) so the function stays sync and testable; the
    background task is the one that owns the session lifecycle.
    """
    return pipeline.Input(
        session=session,
        user_id=user_id,
        gh_repo_id=view.gh_repo_id,
        pr_id=view.gh_pr_id,
        pr_number=view.number,
        branch=view.base_branch,
        base_sha=view.base_sha,
        head_sha=view.head_sha,
        head_branch=view.head_branch,
        author=view.author,
        title=view.title,
        body=view.body or "",
        status=view.status,
        llm_baseurl=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        provider=llm_provider,
        spec=spec,
        github_installation_id=github_installation_id,
        post_to_github=post_to_github,
    )


# --------------------------------------------------------------------------- #
# Ring 3 — DB shell                                                            #
# --------------------------------------------------------------------------- #


async def resolve_user_id(github_installation_id: int) -> str | None:
    """Return the WorkOS ``user_id`` that owns the installation, or ``None``.

    Looks up the :class:`Installation` row by
    ``github_installation_id`` and returns its ``user_id``. Returns
    ``None`` when no row matches (the user has not completed the App
    install flow for this installation).
    """
    async with async_session_maker() as session:
        stmt = select(Installation.user_id).where(
            Installation.github_installation_id == github_installation_id,
            Installation.user_id.is_not(None),  # type: ignore[union-attr]
        )
        return (await session.exec(stmt)).first()


async def resolve_repo_id(gh_repo_id: int) -> str | None:
    """Return the local :class:`Repo` id matching ``github_repo_id``, or ``None``.

    Returns ``None`` when the repo has not been indexed by any user
    yet. The webhook's :class:`pull_request` event is expected to
    arrive after the :class:`installation_repositories` ``added``
    event has populated the row.
    """
    async with async_session_maker() as session:
        stmt = select(Repo).where(Repo.github_repo_id == gh_repo_id)
        repo = (await session.exec(stmt)).first()
        return repo.id if repo is not None else None


async def resolve_installation_id_from_repo_id(
    *,
    gh_repo_id: int,
    session: AsyncSession,
) -> int | None:
    """Return the GitHub installation ID for a local repo ID, or ``None``.

    Follows the chain: repo_id → user_id → github_installation_id.

    Returns ``None`` when:
    - The repo doesn't exist
    - The repo has no user_id
    - No installation exists for that user
    """

    # Step 1: Get user_id from repo_id
    repo_stmt = select(Repo.user_id).where(Repo.github_repo_id == gh_repo_id)
    user_id = (await session.exec(repo_stmt)).first()

    if user_id is None:
        log.warning(
            "resolve_installation_id_from_repo_id: repo not found: repo_id=%s",
            gh_repo_id,
        )
        return None

    # Step 2: Get github_installation_id from user_id
    installation_stmt = select(Installation.github_installation_id).where(
        Installation.user_id == user_id
    )
    installation_id = (await session.exec(installation_stmt)).first()

    if installation_id is None:
        log.warning(
            "resolve_installation_id_from_repo_id: no installation for user: repo_id=%s user_id=%s",
            gh_repo_id,
            user_id,
        )
        return None

    log.info(
        "resolve_installation_id_from_repo_id: found installation: repo_id=%s user_id=%s installation_id=%s",
        gh_repo_id,
        user_id,
        installation_id,
    )
    return installation_id


# --------------------------------------------------------------------------- #
# Ring 3 — background task                                                     #
# --------------------------------------------------------------------------- #


def _resolve_llm_config() -> tuple[LLMProviderStr, str | None, str, str]:
    """Read the LLM configuration from :class:`Settings`.

    The fallback ``openai_api_key`` is applied here so callers can
    treat the returned key as non-empty (the
    :attr:`Settings.llm_configured` precondition is checked at the
    call site).
    """
    provider = cast(LLMProviderStr, settings.llm_provider)
    base_url = settings.llm_base_url or None
    api_key = settings.llm_api_key or settings.openai_api_key
    model = settings.llm_model
    return provider, base_url, api_key, model


async def trigger_review(
    *,
    view: PRReviewInput,
    user_id: str,
    installation_id: int | None = None,
) -> None:
    """Run the review pipeline in a background task; never raises.

    Opens its own session (the request's session is gone by the time
    BackgroundTasks runs) and builds the :class:`pipeline.Input` from
    the view. The single outer ``try / except`` is the net for
    anything escaping :func:`pipeline.run` — a programmer bug, an
    unhandled SDK error, ``asyncio.CancelledError``.
    """
    provider, base_url, api_key, model = _resolve_llm_config()
    sandbox_provider = cast(Literal["e2b", "daytona"], settings.sandbox_provider)
    spec = cast(E2BSandboxSpec, build_default_spec(sandbox_provider))

    gh_repo_id: int = view.gh_repo_id
    pr_number: int = view.number

    try:
        async with async_session_maker() as session:
            # Resolve installation_id for GitHub posting if local_repo_id is provided
            post_to_github = False

            if installation_id:
                post_to_github = True
                log.info(
                    "review.webhook: will post to GitHub: installation_id=%s",
                    installation_id,
                )

            input = build_review_input(
                view,
                user_id=user_id,
                session=session,
                spec=spec,
                llm_provider=provider,
                llm_base_url=base_url,
                llm_api_key=api_key,
                llm_model=model,
                github_installation_id=installation_id,
                post_to_github=post_to_github,
            )
            log.info(
                "review.webhook: trigger_review starting: gh_repo_id=%s "
                "pr_number=%s head_sha=%s post_to_github=%s",
                gh_repo_id,
                pr_number,
                view.head_sha,
                post_to_github,
            )
            result = await pipeline.run(input)
    except Exception as exc:
        log.exception(
            "review.webhook: trigger_review crashed: gh_repo_id=%s pr_number=%s",
            gh_repo_id,
            pr_number,
        )
        log.error(
            "review.webhook: trigger_review cause: %s: %s",
            type(exc).__name__,
            exc,
        )
        return

    if isinstance(result, Err):
        log.warning(
            "review.webhook: trigger_review failed: gh_repo_id=%s "
            "pr_number=%s cause=%s",
            gh_repo_id,
            pr_number,
            flatten_review_error_to_message(result.error),
        )
        return

    log.info(
        "review.webhook: trigger_review ok: gh_repo_id=%s pr_number=%s "
        "summary_id=%s comment_count=%d",
        gh_repo_id,
        pr_number,
        result.value.result.summary,
        len(result.value.result.comments),
    )


# --------------------------------------------------------------------------- #
# Ring 2 — orchestrator                                                        #
# --------------------------------------------------------------------------- #


async def handle_pull_request_opened(
    payload: dict[str, Any],
    delivery: str,
    *,
    background_tasks: Any,
) -> WebhookAck:
    """Dispatch a verified ``pull_request`` ``opened`` delivery to the pipeline.

    The router calls this once per delivery that has already passed
    signature verification. Every skip path returns a
    :class:`WebhookAck` with ``accepted=False`` and a ``skip_reason``;
    the handler never raises so the router can always reply ``202``.
    """
    action = payload.get("action")
    if not classify_action(action):
        return WebhookAck(
            accepted=False,
            action=str(action) if action is not None else "unknown",
            delivery=delivery,
            skip_reason="not_opened",
        )

    installation = payload.get("installation") or {}
    installation_id = installation.get("id")
    if not isinstance(installation_id, int):
        return WebhookAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="malformed_installation",
        )

    view = extract_payload(payload)
    if view is None:
        return WebhookAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="malformed_payload",
        )

    user_id = await resolve_user_id(installation_id)
    if user_id is None:
        log.info(
            "review.webhook: skip (unowned installation): delivery=%s "
            "github_installation_id=%s gh_repo_id=%s number=%s",
            delivery,
            installation_id,
            view.gh_repo_id,
            view.number,
        )
        return WebhookAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="unowned_installation",
        )

    if not settings.llm_configured or not settings.sandbox_configured:
        log.warning(
            "review.webhook: skip (llm or sandbox not configured): "
            "delivery=%s gh_repo_id=%s number=%s llm_configured=%s "
            "sandbox_configured=%s",
            delivery,
            view.gh_repo_id,
            view.number,
            settings.llm_configured,
            settings.sandbox_configured,
        )
        return WebhookAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="review_not_configured",
        )

    log.info(
        "review.webhook:  delivery=%s gh_repo_id=%s number=%s head_sha=%s",
        delivery,
        view.gh_repo_id,
        view.number,
        view.head_sha,
    )

    background_tasks.add_task(
        trigger_review,
        view=view,
        user_id=user_id,
        installation_id=installation_id,
    )

    return WebhookAck(accepted=True, action="opened", delivery=delivery)


__all__ = [
    "PRReviewInput",
    "WebhookAck",
    "build_review_input",
    "classify_action",
    "extract_payload",
    "handle_pull_request_opened",
    "resolve_installation_id_from_repo_id",
    "resolve_repo_id",
    "resolve_user_id",
    "trigger_review",
]
