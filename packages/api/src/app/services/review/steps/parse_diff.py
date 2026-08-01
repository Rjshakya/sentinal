"""DBOS durable step: parse the diff into a :data:`HunkMap` and write ``diff.json``.

Connects to the E2B sandbox, calls
:func:`app.services.review.diff.parse_and_write_diff_json`, and returns
the parsed :data:`ParsedDiff` so the workflow can pass it into the
agent step and the server-side filter without re-reading the sandbox.

The sandbox is stopped in ``finally`` so a parse failure does not
leave the connection open.
"""

from __future__ import annotations

import logging

from dbos import DBOS

from app.core.sandbox.e2b import E2BSandbox
from app.services.review._internal import _e2b_spec
from app.services.review.diff import parse_and_write_diff_json
from app.services.review.errors import SandboxConnectError
from app.services.review.hunk_map import ParsedDiff

log = logging.getLogger(__name__)


@DBOS.step()
async def parse_diff_step(
    *,
    sandbox_id: str,
    sandbox_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
) -> ParsedDiff:
    """Durable step: read ``file.diff``, parse, write ``diff.json``.

    The returned :data:`ParsedDiff` is the same data structure that
    was written to ``diff.json``. The agent reads the file from the
    sandbox; the workflow passes the in-memory copy into
    :func:`app.services.review.hunk_map.filter_drafts`.

    Raises:
        SandboxConnectError: failed to reconnect to the sandbox.
        DiffUnavailableError: ``file.diff`` is missing, empty, or
            unparseable.
    """
    spec = _e2b_spec()
    try:
        sandbox = await E2BSandbox.connect(
            sandbox_id=sandbox_id,
            sandbox_name=sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        raise SandboxConnectError(
            user_id=user_id,
            repo_id=repo_id,
            sandbox_id=sandbox_id,
            cause=f"failed to reconnect sandbox for diff parse: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        return await parse_and_write_diff_json(
            sandbox,
            pr_number=pr_number,
            head_sha=head_sha,
            repo_id=repo_id,
            base_sha=base_sha,
        )
    finally:
        try:
            await sandbox.stop()
        except Exception:
            log.exception("failed to stop sandbox after diff parse")


__all__ = ["parse_diff_step"]
