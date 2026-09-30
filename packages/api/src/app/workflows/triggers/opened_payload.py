"""Pure projection of a pull_request opened payload onto PRPayload.

No I/O, no DB, no session. Returns None when any required field is
missing or mistyped — the handler folds that into a malformed skip.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.models.enums import PRStatus
from app.workflows.triggers.types import PRPayload


def prStatusFromGithub(state: object, merged: object) -> PRStatus | None:
    if state == "open":
        return PRStatus.OPEN
    if state == "closed":
        return PRStatus.MERGED if merged else PRStatus.CLOSED
    return None


def extractOpenedPrPayload(payload: dict) -> PRPayload | None:
    repo = payload.get("repository")
    if not isinstance(repo, dict):
        return None
    pr = payload.get("pull_request")
    if not isinstance(pr, dict):
        return None
    base = pr.get("base")
    if not isinstance(base, dict):
        return None
    head = pr.get("head")
    if not isinstance(head, dict):
        return None
    user = pr.get("user")
    if not isinstance(user, dict):
        return None

    status = prStatusFromGithub(pr.get("state"), pr.get("merged"))
    if status is None:
        return None

    try:
        return PRPayload.model_validate(
            {
                "ghRepoId": repo.get("id"),
                "ghPrId": pr.get("id"),
                "number": pr.get("number"),
                "baseBranch": base.get("ref"),
                "defaultBranch": repo.get("default_branch"),
                "baseSha": base.get("sha"),
                "headBranch": head.get("ref"),
                "headSha": head.get("sha"),
                "author": user.get("login"),
                "title": pr.get("title"),
                "body": pr.get("body") or "",
                "status": status,
                "prSize": {
                    "additions": int(pr.get("additions") or 0),
                    "deletions": int(pr.get("deletions") or 0),
                    "changedFiles": int(pr.get("changed_files") or 0),
                },
            }
        )
    except ValidationError:
        return None


__all__ = ["extractOpenedPrPayload", "prStatusFromGithub"]
