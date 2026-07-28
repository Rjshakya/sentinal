"""GitHub ``pull_request`` webhook adapter for the durable review workflow.

Dispatches a verified ``opened`` / ``synchronize`` delivery to the DBOS
review workflow. The workflow is durable, idempotent, and runs in the
background without FastAPI ``BackgroundTasks``.

- **Ring 1 (pure)**       — :class:`PRReviewInput`,
  :func:`classify_action`, :func:`extract_payload`,
  :func:`build_review_workflow_input`. No I/O, no session, no clock.

- **Ring 2 (orchestrator)** — :func:`handle_pull_request_opened`. The
  single public entry point. Sequences the DB lookups, the config
  preconditions, and the workflow dispatch.

- **Ring 3 (shell)**      — :func:`resolve_user_id`,
  :func:`resolve_repo_id`, :func:`resolve_installation_id_from_repo_id`.
  Each is the single boundary into the database.
"""

from __future__ import annotations

import logging
from typing import Any

from dbos import DBOS, SetWorkflowID
from pydantic import BaseModel, ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.llm import LLMProviderStr
from app.models.enums import PRStatus
from app.models.installation import Installation
from app.models.repo import Repo
from app.services.review.workflow import ReviewWorkflowInput, review_workflow

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
    """Flat, typed view of a verified ``pull_request`` payload."""

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


def classify_action(action: Any) -> bool:
    """Return ``True`` iff ``action`` is ``"opened"`` or ``"synchronize"``."""
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
    that into a ``skip_reason="malformed_payload"`` ack. Never raises.
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


def opencode_anthropic_models():
    provider = "anthropic"
    base_url = "https://opencode.ai/zen/go"
    model = "minimax-m3"
    api_key = settings.llm_api_key
    return provider, base_url, api_key, model


def _resolve_llm_config() -> tuple[LLMProviderStr, str | None, str, str]:
    """Read the LLM configuration from :class:`Settings`.

    The fallback ``openai_api_key`` is applied here so callers can
    treat the returned key as non-empty.
    """
    # provider = settings.llm_provider
    # base_url = settings.llm_base_url or None
    # api_key = settings.llm_api_key or settings.openai_api_key
    # model = settings.llm_model

    provider = "openai"
    base_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{settings.cf_account_id}/ai/v1"
    )

    api_key = settings.cf_ai_gateway_auth_token
    # model = "@cf/moonshotai/kimi-k2.7-code"
    model = "openai/gpt-5.1"

    return opencode_anthropic_models()
    return provider, base_url, api_key, model  # type: ignore[return-value]


def build_review_workflow_input(
    view: PRReviewInput,
    *,
    user_id: str,
    llm_provider: LLMProviderStr,
    llm_base_url: str | None,
    llm_api_key: str,
    llm_model: str,
    github_installation_id: int | None = None,
    post_to_github: bool = False,
) -> ReviewWorkflowInput:
    """Translate the webhook view into a serializable workflow input."""
    return ReviewWorkflowInput(
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
        post_to_github=post_to_github,
        github_installation_id=github_installation_id,
    )


# --------------------------------------------------------------------------- #
# Ring 3 — DB shell                                                            #
# --------------------------------------------------------------------------- #


async def resolve_user_id(github_installation_id: int) -> str | None:
    """Return the WorkOS ``user_id`` that owns the installation, or ``None``."""
    async with async_session_maker() as session:
        stmt = select(Installation.user_id).where(
            Installation.github_installation_id == github_installation_id,
            Installation.user_id.is_not(None),  # type: ignore[union-attr]
        )
        return (await session.exec(stmt)).first()


async def resolve_repo_id(gh_repo_id: int) -> str | None:
    """Return the local :class:`Repo` id matching ``github_repo_id``, or ``None``."""
    async with async_session_maker() as session:
        stmt = select(Repo.id).where(Repo.github_repo_id == gh_repo_id)
        repo_id = (await session.exec(stmt)).first()
        return repo_id


async def resolve_installation_id_from_repo_id(
    *,
    gh_repo_id: int,
    session: AsyncSession,
) -> int | None:
    """Return the GitHub installation ID for a local repo ID, or ``None``."""

    repo_stmt = select(Repo.user_id).where(Repo.github_repo_id == gh_repo_id)
    user_id = (await session.exec(repo_stmt)).first()

    if user_id is None:
        log.warning(
            "resolve_installation_id_from_repo_id: repo not found: repo_id=%s",
            gh_repo_id,
        )
        return None

    installation_stmt = select(Installation.github_installation_id).where(
        Installation.user_id == user_id
    )
    installation_id = (await session.exec(installation_stmt)).first()

    if installation_id is None:
        log.warning(
            "resolve_installation_id_from_repo_id: no installation for user: "
            "repo_id=%s user_id=%s",
            gh_repo_id,
            user_id,
        )
        return None

    log.info(
        "resolve_installation_id_from_repo_id: found installation: "
        "repo_id=%s user_id=%s installation_id=%s",
        gh_repo_id,
        user_id,
        installation_id,
    )
    return installation_id


# --------------------------------------------------------------------------- #
# Ring 2 — orchestrator                                                        #
# --------------------------------------------------------------------------- #


async def handle_pull_request_opened(
    payload: dict[str, Any],
    delivery: str,
) -> WebhookAck:
    """Dispatch a verified ``pull_request`` ``opened`` delivery to the workflow.

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

    repo_id = await resolve_repo_id(view.gh_repo_id)
    if repo_id is None:
        log.info(
            "review.webhook: skip (repo not configured): delivery=%s "
            "gh_repo_id=%s number=%s",
            delivery,
            view.gh_repo_id,
            view.number,
        )
        return WebhookAck(
            accepted=False,
            action="opened",
            delivery=delivery,
            skip_reason="repo_not_indexed",
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

    provider, base_url, api_key, model = _resolve_llm_config()
    post_to_github = installation_id is not None

    workflow_input = build_review_workflow_input(
        view,
        user_id=user_id,
        llm_provider=provider,
        llm_base_url=base_url,
        llm_api_key=api_key,
        llm_model=model,
        github_installation_id=installation_id,
        post_to_github=post_to_github,
    )

    workflow_id = f"review:{repo_id}:{view.number}:{view.head_sha[:7]}"

    log.info(
        "review.webhook: starting workflow: delivery=%s workflow_id=%s "
        "gh_repo_id=%s number=%s head_sha=%s post_to_github=%s",
        delivery,
        workflow_id,
        view.gh_repo_id,
        view.number,
        view.head_sha,
        post_to_github,
    )

    with SetWorkflowID(workflow_id):
        await DBOS.start_workflow_async(review_workflow, workflow_input)

    return WebhookAck(accepted=True, action="opened", delivery=delivery)


__all__ = [
    "PRReviewInput",
    "WebhookAck",
    "build_review_workflow_input",
    "classify_action",
    "extract_payload",
    "handle_pull_request_opened",
    "resolve_installation_id_from_repo_id",
    "resolve_repo_id",
    "resolve_user_id",
]
