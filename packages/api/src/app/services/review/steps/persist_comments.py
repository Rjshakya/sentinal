"""Persist the code-comment rows produced by the review agent.

Two layers, following the Functional Core / Imperative Shell split:

- :func:`persist_code_comments` — the **pure** helper. Takes an
  :class:`AsyncSession` and a sequence of :class:`CodeCommentDraft`,
  returns the inserted :class:`CodeComment` rows. No DBOS.
- :func:`persist_code_comments_tx` — the **DBOS-wrapped**
  transaction. Acquires the DBOS datasource session, calls the pure
  helper, and returns the inserted row ids.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from app.core.db import dbos_datasource
from app.models.code_comment import CodeComment
from app.utils.schema import CodeCommentDraft
from app.services.review.helpers import map_drafts_to_comment_rows
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def persist_code_comments(
    session: AsyncSession,
    *,
    pr_id: str,
    review_id: str | None,
    commit_id: str,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Insert one :class:`CodeComment` row per draft finding."""
    rows = map_drafts_to_comment_rows(
        pr_id=pr_id, review_id=review_id, commit_id=commit_id, comments=comments
    )

    if not rows:
        log.info("no code comments to persist (pr_id=%s)", pr_id)
        return []

    session.add_all(rows)
    await session.flush()
    for row in rows:
        await session.refresh(row)

    log.info(
        "persisted %d code comment(s): pr_id=%s commit_id=%s",
        len(rows),
        pr_id,
        commit_id,
    )
    return rows


@dbos_datasource.transaction()
async def persist_code_comments_tx(
    *,
    pr_id: str,
    review_id: str | None,
    commit_id: str,
    comments: list[dict[str, Any]],
) -> list[str]:
    """Durable DBOS transaction: persist the code comment rows.

    Accepts a list of plain dicts (the workflow passes the agent's
    ``model_dump(mode="json")`` output) and validates each one into a
    :class:`CodeCommentDraft` before insertion. Returns the inserted
    row ids.
    """
    session = dbos_datasource.sql_session()
    drafts = [CodeCommentDraft.model_validate(c) for c in comments]
    rows = map_drafts_to_comment_rows(
        pr_id=pr_id, review_id=review_id, commit_id=commit_id, comments=drafts
    )
    if not rows:
        return []
    session.add_all(rows)
    await session.flush()
    for row in rows:
        await session.refresh(row)
    return [row.id for row in rows]


__all__ = ["persist_code_comments", "persist_code_comments_tx"]
