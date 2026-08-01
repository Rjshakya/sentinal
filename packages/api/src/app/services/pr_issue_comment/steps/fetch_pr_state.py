"""Step: fetch the current PR state from GitHub.

The ``issue_comment`` payload does not carry the PR's current
``head_sha`` / ``base_sha`` / ``base_branch`` / ``head_branch`` /
``title`` / ``body`` / ``author`` / ``state`` / ``merged`` fields the
inner review workflow needs. The
:func:`fetch_pr_state_step` reads them via
``GET /repos/{owner}/{repo}/pulls/{pr_number}`` using the
App's installation token.

Two layers in this module:

- :func:`_read_pr_state` — the **pure** helper. Takes an
  installation id, owner, repo, and PR number, mints an
  installation client, and returns a
  :class:`app.services.pr_issue_comment.types.PRStateSnapshot`. No
  DBOS.
- :func:`fetch_pr_state_step` — the **DBOS-wrapped** step. Wraps the
  same call, retries up to ``max_attempts`` times on
  :class:`app.services.pr_issue_comment.errors.PRFetchError`, and
  returns the snapshot. The step is the durable I/O boundary.
"""

from __future__ import annotations

import logging

from dbos import DBOS
from githubkit import GitHub
from githubkit.exception import GitHubException

from app.core.github_app import installation_client
from app.services.pr_issue_comment.errors import PRFetchError
from app.services.pr_issue_comment.types import PRStateSnapshot

log = logging.getLogger(__name__)


def _should_retry(exc: BaseException) -> bool:
    """Retry predicate for the PR fetch step.

    DBOS's default retry policy needs a callable; we forward only
    :class:`app.services.pr_issue_comment.errors.PRFetchError`. The
    error is already raised transient-only, so this is a thin wrapper
    for symmetry with the rest of the codebase.
    """
    from app.services.pr_issue_comment.errors import TransientTriggerError

    return isinstance(exc, TransientTriggerError)


def _pr_state_from_response(parsed: object) -> PRStateSnapshot:
    """Project a githubkit ``PullRequest`` onto :class:`PRStateSnapshot`.

    Helper kept module-private to avoid leaking the githubkit schema
    into the rest of the package. Defensive: every field is read
    with a fallback so a partially-populated response still yields a
    usable snapshot (DBOS will retry the step on a true failure).
    """
    head = getattr(parsed, "head", None)
    base = getattr(parsed, "base", None)
    user = getattr(parsed, "user", None)

    head_sha = getattr(head, "sha", None) or ""
    head_branch = getattr(head, "ref", None) or ""
    base_sha = getattr(base, "sha", None) or ""
    base_branch = getattr(base, "ref", None) or ""
    title = getattr(parsed, "title", None) or ""
    body = getattr(parsed, "body", None) or ""
    author_login = getattr(user, "login", None) or ""
    state = getattr(parsed, "state", None) or "open"
    merged = bool(getattr(parsed, "merged", False))
    gh_pr_id = int(getattr(parsed, "id", 0) or 0)

    return PRStateSnapshot(
        gh_pr_id=gh_pr_id,
        base_sha=base_sha,
        head_sha=head_sha,
        base_branch=base_branch,
        head_branch=head_branch,
        title=title,
        body=body,
        author=author_login,
        state=state,
        merged=merged,
    )


async def _read_pr_state(
    installation_id: int,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    client: GitHub | None = None,
) -> PRStateSnapshot:
    """Pure helper: read the PR via the installation client.

    ``client`` is injectable for tests; production code passes
    ``None`` and the function mints a real installation client.
    """
    gh = client if client is not None else installation_client(installation_id)
    try:
        resp = await gh.rest.pulls.async_get(
            owner=owner,
            repo=repo,
            pull_number=pr_number,
        )
    except GitHubException as exc:
        cause = f"{type(exc).__name__}: {exc}"
        log.warning(
            "pr_issue_comment.fetch_pr_state_step: get failed: "
            "owner=%s repo=%s pr_number=%s cause=%s",
            owner,
            repo,
            pr_number,
            cause,
        )
        raise PRFetchError(
            owner=owner, repo=repo, pr_number=pr_number, cause=cause
        ) from exc

    parsed = resp.parsed_data
    if parsed is None:
        raise PRFetchError(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            cause="empty response",
        )
    return _pr_state_from_response(parsed)


@DBOS.step(
    retries_allowed=True,
    max_attempts=3,
    should_retry=_should_retry,
)
async def fetch_pr_state_step(
    installation_id: int,
    *,
    owner: str,
    repo: str,
    pr_number: int,
) -> PRStateSnapshot:
    """Durable DBOS step: read the current PR state via the GitHub API.

    Uses :func:`app.core.github_app.installation_client` to mint a
    fresh installation token. Retries up to ``max_attempts`` times on
    :class:`app.services.pr_issue_comment.errors.PRFetchError` (a
    :class:`TransientTriggerError`); on persistent failure the
    workflow's outer try/except converts the raised error to a
    ``skip_reason="pr_fetch_failed"`` :class:`TriggerRunResult`.

    Returns:
        A :class:`PRStateSnapshot` carrying the fields the inner
        review workflow needs (head_sha, base_sha, branches, title,
        body, author, state, merged, gh_pr_id).
    """
    return await _read_pr_state(
        installation_id,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )


__all__ = ["fetch_pr_state_step"]
