"""Step: add a 👀 reaction to the triggering comment.

Fire-and-forget ack. The reaction is the only visible signal the
user gets that the trigger was accepted, so the step must not
raise — any :class:`githubkit.exception.GitHubException` is
swallowed after a structured log line. The trigger workflow
proceeds regardless of the reaction's outcome.

Two layers in this module:

- :func:`_add_eyes_reaction` — the **pure** helper. Takes an
  installation id, owner, repo, and comment id, mints an
  installation client, and POSTs the reaction. No DBOS.
- :func:`add_eyes_reaction_step` — the **DBOS-wrapped** step.
  Returns ``None`` always (success or caught failure).
"""

from __future__ import annotations

import logging

from dbos import DBOS
from githubkit import GitHub
from githubkit.exception import GitHubException

from app.core.github_app import installation_client

log = logging.getLogger(__name__)


async def _add_eyes_reaction(
    installation_id: int,
    *,
    owner: str,
    repo: str,
    comment_id: int,
    client: GitHub | None = None,
) -> None:
    """Pure helper: add a 👀 reaction via the installation client.

    ``client`` is injectable for tests; production code passes
    ``None`` and the function mints a real installation client.
    """
    gh = client if client is not None else installation_client(installation_id)
    try:
        await gh.rest.reactions.async_create_for_issue_comment(
            owner=owner,
            repo=repo,
            comment_id=comment_id,
            data={"content": "eyes"},
        )
    except GitHubException as exc:
        log.warning(
            "pr_issue_comment.add_eyes_reaction_step: reaction failed: "
            "owner=%s repo=%s comment_id=%s cause=%s: %s",
            owner,
            repo,
            comment_id,
            type(exc).__name__,
            exc,
        )


@DBOS.step()
async def add_eyes_reaction_step(
    installation_id: int,
    *,
    owner: str,
    repo: str,
    comment_id: int,
) -> None:
    """Durable DBOS step: add a 👀 reaction, best-effort.

    Never raises. A failure is logged at WARNING and the workflow
    proceeds — the user will still see the review run, just without
    the visual ack on the comment.
    """
    await _add_eyes_reaction(
        installation_id,
        owner=owner,
        repo=repo,
        comment_id=comment_id,
    )


__all__ = ["add_eyes_reaction_step"]
