### packages/api/src/app/services/review/steps/review_run_steps.py

```diff

deleted file mode 100644
index aeddcc7..0000000
--- a/packages/api/src/app/services/review/steps/review_run_steps.py
+++ /dev/null
@@ -1,308 +0,0 @@
    2       -"""DBOS steps that record the review workflow's lifecycle onto the
    3       -``review`` table.
    4       -
    5       -Three steps — one per state transition, plus a pure error-context
    6       -helper:
    7       -
    8       -- :func:`mark_review_is_running_step` — finds (or creates) the
    9       -  ``review`` row for the current workflow and flips it to ``RUNNING``:
   10       -  records the pr link, sandbox, and the LLM snapshot.
   11       -- :func:`mark_review_is_stopped_step` — flips to ``SUCCESS`` with the
   12       -  surviving comment count, the GitHub review id (when the post
   13       -  workflow returned one), and ``completed_at``.
   14       -- :func:`mark_review_is_errored_step` — flips to ``FAILED`` with the
   15       -  typed error name / message / context and ``completed_at``.
   16       -- :func:`build_error_context` — pure; projects an exception onto the
   17       -  ``error_context`` JSONB shape.
   18       -
   19       -Every step is durable: each is ``@DBOS.step(retries_allowed=True,
   20       -max_attempts=3, should_retry=_SHOULD_RETRY_TRANSIENT)`` and raises
   21       -:class:`app.services.review.errors.ReviewRunUpdateError` on failure,
   22       -so a DB blip is retried and a persistent failure surfaces as a
   23       -workflow ERROR instead of silently leaving the row stuck in
   24       -``RUNNING``. The running step's find-or-create semantics make retries
   25       -safe (a retried insert re-finds the committed row via the unique
   26       -``workflow_id``). Only :func:`mark_review_is_errored_step` still
   27       -accepts a ``None`` review id (it runs from the workflow's ``except``
   28       -block, where the running step may never have completed) and no-ops in
   29       -that case.
   30       -"""
   31       -
   32       -from __future__ import annotations
   33       -
   34       -import logging
   35       -from datetime import UTC, datetime
   36       -from typing import Any
   37       -
   38       -from dbos import DBOS
   39       -from sqlalchemy.ext.asyncio import AsyncSession
   40       -from sqlmodel import select
   41       -
   42       -from app.core.db import async_session_maker
   43       -from app.models.review import Review, ReviewState
   44       -from app.services.review._internal import _SHOULD_RETRY_TRANSIENT
   45       -from app.services.review.errors import (
   46       -    ReviewAgentsInvocationError,
   47       -    ReviewRunUpdateError,
   48       -)
   49       -
   50       -log = logging.getLogger(__name__)
   51       -
   52       -
   53       -def _utcnow() -> datetime:
   54       -    return datetime.now(UTC)
   55       -
   56       -
   57       -async def _fetch_review(session: AsyncSession, review_id: str) -> Review | None:
   58       -    return await session.get(Review, review_id)
   59       -
   60       -
   61       -@DBOS.step(
   62       -    retries_allowed=True,
   63       -    max_attempts=3,
   64       -    should_retry=_SHOULD_RETRY_TRANSIENT,
   65       -)
   66       -async def mark_review_is_running_step(
   67       -    *,
   68       -    user_id: str,
   69       -    repo_id: str,
   70       -    gh_repo_id: int,
   71       -    pr_id: str,
   72       -    pr_number: int,
   73       -    commit_id: str,
   74       -    base_sha: str | None,
   75       -    trigger: str,
   76       -    sandbox_id: str,
   77       -    workflow_id: str,
   78       -    llm_provider: str,
   79       -    llm_model: str,
   80       -    llm_base_url: str | None,
   81       -) -> str:
   82       -    """Find-or-create the ``RUNNING`` row for the current workflow.
   83       -
   84       -    Uses ``workflow_id`` as the deterministic DBOS id so the row is
   85       -    unique per run and duplicate dispatches / workflow restarts reuse
   86       -    it. On restart the existing row is reset to ``RUNNING`` and its
   87       -    error fields cleared (``started_at`` is kept from the original
   88       -    attempt). Returns the row's ``id`` so the workflow can carry it
   89       -    across step boundaries.
   90       -
   91       -    Raises:
   92       -        ReviewRunUpdateError: the row could not be written (or the
   93       -            existing row could not be reset). Transient — DBOS retries
   94       -            the step up to 3 attempts, then the workflow is ERROR.
   95       -    """
   96       -    try:
   97       -        async with async_session_maker() as session:
   98       -            existing = (
   99       -                await session.exec(
  100       -                    select(Review).where(Review.workflow_id == workflow_id)
  101       -                )
  102       -            ).first()
  103       -
  104       -            if existing is not None:
  105       -                existing.state = ReviewState.RUNNING
  106       -                existing.pr_id = pr_id
  107       -                existing.sandbox_id = sandbox_id
  108       -                existing.llm_provider = llm_provider
  109       -                existing.llm_model = llm_model
  110       -                existing.llm_base_url = llm_base_url
  111       -                existing.error_name = None
  112       -                existing.error_message = None
  113       -                existing.error_context = None
  114       -
  115       -                if existing.started_at is None:
  116       -                    existing.started_at = _utcnow()
  117       -                    existing.updated_at = _utcnow()
  118       -
  119       -                await session.commit()
  120       -
  121       -                log.info(
  122       -                    "mark_review_is_running_step: reset existing row "
  123       -                    "review_id=%s workflow_id=%s",
  124       -                    existing.id,
  125       -                    workflow_id,
  126       -                )
  127       -
  128       -                return existing.id
  129       -
  130       -            review = Review(
  131       -                user_id=user_id,
  132       -                repo_id=repo_id,
  133       -                gh_repo_id=gh_repo_id,
  134       -                pr_id=pr_id,
  135       -                pr_number=pr_number,
  136       -                commit_id=commit_id,
  137       -                base_sha=base_sha,
  138       -                workflow_id=workflow_id,
  139       -                trigger=trigger,
  140       -                state=ReviewState.RUNNING,
  141       -                sandbox_id=sandbox_id,
  142       -                llm_provider=llm_provider,
  143       -                llm_model=llm_model,
  144       -                llm_base_url=llm_base_url,
  145       -                started_at=_utcnow(),
  146       -            )
  147       -            session.add(review)
  148       -            await session.commit()
  149       -            await session.refresh(review)
  150       -        log.info(
  151       -            "mark_review_is_running_step: ok review_id=%s workflow_id=%s "
  152       -            "repo_id=%s pr_number=%s",
  153       -            review.id,
  154       -            workflow_id,
  155       -            repo_id,
  156       -            pr_number,
  157       -        )
  158       -        return review.id
  159       -    except Exception as exc:
  160       -        log.warning(
  161       -            "mark_review_is_running_step: failed workflow_id=%s repo_id=%s "
  162       -            "pr_number=%s",
  163       -            workflow_id,
  164       -            repo_id,
  165       -            pr_number,
  166       -            exc_info=True,
  167       -        )
  168       -        raise ReviewRunUpdateError(
  169       -            f"mark running failed for workflow_id={workflow_id} "
  170       -            f"repo_id={repo_id} pr_number={pr_number}: {exc}"
  171       -        ) from exc
  172       -
  173       -
  174       -@DBOS.step(
  175       -    retries_allowed=True,
  176       -    max_attempts=3,
  177       -    should_retry=_SHOULD_RETRY_TRANSIENT,
  178       -)
  179       -async def mark_review_is_stopped_step(
  180       -    *,
  181       -    review_id: str,
  182       -    comment_count: int,
  183       -    github_review_id: str | None,
  184       -) -> None:
  185       -    """Flip the row to ``SUCCESS`` and persist the run outcome.
  186       -
  187       -    Raises:
  188       -        ReviewRunUpdateError: the row does not exist or could not be
  189       -            updated. Transient — DBOS retries up to 3 attempts, then
  190       -            the workflow lands in the ``except`` block, which flips
  191       -            the row to ``FAILED`` with this error and re-raises.
  192       -    """
  193       -    try:
  194       -        async with async_session_maker() as session:
  195       -            review = await _fetch_review(session, review_id)
  196       -            if review is None:
  197       -                raise ReviewRunUpdateError(
  198       -                    f"mark stopped: review {review_id!r} not found"
  199       -                )
  200       -            review.state = ReviewState.SUCCESS
  201       -            review.comment_count = comment_count
  202       -            review.github_review_id = github_review_id
  203       -            review.completed_at = _utcnow()
  204       -            review.updated_at = _utcnow()
  205       -            await session.commit()
  206       -        log.info(
  207       -            "mark_review_is_stopped_step: ok review_id=%s comments=%d "
  208       -            "github_review_id=%s",
  209       -            review_id,
  210       -            comment_count,
  211       -            github_review_id,
  212       -        )
  213       -    except Exception as exc:
  214       -        log.warning(
  215       -            "mark_review_is_stopped_step: failed review_id=%s",
  216       -            review_id,
  217       -            exc_info=True,
  218       -        )
  219       -        raise ReviewRunUpdateError(
  220       -            f"mark stopped failed for review_id={review_id}: {exc}"
  221       -        ) from exc
  222       -
  223       -
  224       -@DBOS.step(
  225       -    retries_allowed=True,
  226       -    max_attempts=3,
  227       -    should_retry=_SHOULD_RETRY_TRANSIENT,
  228       -)
  229       -async def mark_review_is_errored_step(
  230       -    *,
  231       -    review_id: str | None,
  232       -    error_name: str,
  233       -    error_message: str,
  234       -    error_context: dict[str, Any] | None,
  235       -) -> None:
  236       -    """Flip the row to ``FAILED`` and persist the typed error info.
  237       -
  238       -    No-ops when ``review_id`` is ``None`` — the workflow's ``except``
  239       -    block calls this even when the running step never completed, so
  240       -    there may be no row to flip. The workflow wraps this call in its
  241       -    own try/except so a failure here never masks the original error.
  242       -
  243       -    Raises:
  244       -        ReviewRunUpdateError: the row does not exist or could not be
  245       -            updated. Transient — DBOS retries up to 3 attempts.
  246       -    """
  247       -    if review_id is None:
  248       -        return
  249       -    try:
  250       -        async with async_session_maker() as session:
  251       -            review = await _fetch_review(session, review_id)
  252       -            if review is None:
  253       -                raise ReviewRunUpdateError(
  254       -                    f"mark errored: review {review_id!r} not found"
  255       -                )
  256       -            review.state = ReviewState.FAILED
  257       -            review.error_name = error_name
  258       -            review.error_message = error_message
  259       -            review.error_context = error_context
  260       -            review.completed_at = _utcnow()
  261       -            review.updated_at = _utcnow()
  262       -            await session.commit()
  263       -        log.info(
  264       -            "mark_review_is_errored_step: ok review_id=%s error=%s",
  265       -            review_id,
  266       -            error_name,
  267       -        )
  268       -    except Exception as exc:
  269       -        log.warning(
  270       -            "mark_review_is_errored_step: failed review_id=%s",
  271       -            review_id,
  272       -            exc_info=True,
  273       -        )
  274       -        raise ReviewRunUpdateError(
  275       -            f"mark errored failed for review_id={review_id}: {exc}"
  276       -        ) from exc
  277       -
  278       -
  279       -def build_error_context(exc: BaseException) -> dict[str, Any] | None:
  280       -    """Project an exception onto the ``error_context`` JSONB shape.
  281       -
  282       -    Full payload for :class:`ReviewAgentsInvocationError` (the
  283       -    dominant failure mode — both agent lanes exhausted their
  284       -    retries); ``None`` for everything else (the row keeps just
  285       -    ``error_name`` / ``error_message``).
  286       -
  287       -    ``error_name`` carries the per-agent error class names of the
  288       -    failed lanes (e.g. ``"SummaryAgentInvocationError,
  289       -    CommentsAgentInvocationError"``), falling back to the aggregate
  290       -    class name when no lane detail is available.
  291       -    """
  292       -    if isinstance(exc, ReviewAgentsInvocationError):
  293       -        failed_names = [type(e).__name__ for e in exc.failed_agents]
  294       -        return {
  295       -            "error_name": ", ".join(failed_names) or type(exc).__name__,
  296       -            "succeeded_agents": list(exc.succeeded_agents),
  297       -            "llm_provider": exc.llm_provider,
  298       -            "llm_model": exc.llm_model,
  299       -            "occurred_at": exc.occurred_at.isoformat(),
  300       -        }
  301       -    return None
  302       -
  303       -
  304       -__all__ = [
  305       -    "build_error_context",
  306       -    "mark_review_is_errored_step",
  307       -    "mark_review_is_running_step",
  308       -    "mark_review_is_stopped_step",
  309       -]

```
