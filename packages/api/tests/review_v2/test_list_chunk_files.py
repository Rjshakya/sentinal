"""Live-sandbox tests for the v2 chunk inventor.

Calls :func:`app.workflows.review_v2.steps.list_chunks.listChunkFiles`
against a real E2B sandbox seeded with real ``splitted_diffs/`` chunk
files — no mocks, no durable runtime, no repo checkout. One sandbox is shared
across the whole file (module-scoped fixture, killed once at teardown);
cases stay isolated through unique ``(pr_number, head_sha)`` dirs.

Requires ``E2B_API_KEY`` (skips without it).

Run: cd packages/api && uv run pytest tests/test_review_v2_list_chunks.py -v
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import e2b
import pytest
from langchain_e2b import AsyncE2BSandbox

from app.core.config import settings
from app.services.agent_v2.types import ChunkInventory
from app.utils.branded import CommitId, PRNumber, RepoId
from app.workflows.review_v2.errors import ChunkListError
from app.workflows.review_v2.steps.list_chunks import listChunkFiles

_SANDBOX_WORKDIR = "/home/user"
# Sandbox lifetime (seconds): long enough for seed + list, short enough
# that a missed kill never leaves a long-lived orphan.
_SANDBOX_LIFETIME_S = 600
_CMD_TIMEOUT_S = 60


@pytest.fixture(scope="module")
async def live_sandbox() -> AsyncGenerator[AsyncE2BSandbox, None]:
    """Create one real E2B sandbox shared by the file; kill it at teardown."""
    if not settings.e2b_api_key:
        pytest.skip("E2B_API_KEY is not set; live sandbox test needs it")
    raw = await e2b.AsyncSandbox.create(
        template=settings.e2b_template,
        api_key=settings.e2b_api_key,
        timeout=_SANDBOX_LIFETIME_S,
    )
    sandbox = AsyncE2BSandbox(sandbox=raw, workdir=_SANDBOX_WORKDIR)
    try:
        yield sandbox
    finally:
        try:
            await e2b.AsyncSandbox.kill(
                sandbox_id=raw.sandbox_id,
                api_key=settings.e2b_api_key,
            )
        except Exception:
            pass  # teardown must never mask the test outcome


def _chunks_dir(pr_number: int, head_sha: str) -> str:
    """The in-sandbox ``splitted_diffs/`` dir the worker inventories."""
    return f"{_SANDBOX_WORKDIR}/tmp/{pr_number}/{head_sha}/splitted_diffs"


def _chunk_body(real_path: str) -> str:
    """A minimal chunk file: ``### <real path>`` header + fenced diff."""
    return (
        f"### {real_path}\n"
        "\n"
        "```diff\n"
        f"--- a/{real_path}\n"
        f"+++ b/{real_path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "```\n"
    )


async def _seed_chunks(
    sandbox: AsyncE2BSandbox,
    *,
    pr_number: int,
    head_sha: str,
    files: dict[str, str],
) -> str:
    """Write chunk files into the run's ``splitted_diffs/`` dir."""
    chunks_dir = _chunks_dir(pr_number, head_sha)
    mkdir = await sandbox.aexecute(f"mkdir -p {chunks_dir}", timeout=_CMD_TIMEOUT_S)
    assert mkdir.exit_code == 0, f"mkdir failed: {mkdir.output!r}"
    uploads = await sandbox.aupload_files(
        [(f"{chunks_dir}/{name}", body.encode("utf-8")) for name, body in files.items()]
    )
    assert len(uploads) == len(files)
    failed = [(u.path, u.error) for u in uploads if u.error is not None]
    assert not failed, f"chunk uploads failed: {failed}"
    return chunks_dir


async def test_list_chunk_files_inventories_seeded_chunks(
    live_sandbox: AsyncE2BSandbox,
) -> None:
    pr_number = 11
    head_sha = "a" * 40
    await _seed_chunks(
        live_sandbox,
        pr_number=pr_number,
        head_sha=head_sha,
        files={
            "src.app.b.py.md": _chunk_body("src/app/b.py"),
            "src.app.a.py.md": _chunk_body("src/app/a.py"),
        },
    )

    inventory = await listChunkFiles(
        live_sandbox,
        repoId=RepoId("list-chunks-repo"),
        prNumber=PRNumber(pr_number),
        headSha=CommitId(head_sha),
    )

    assert isinstance(inventory, ChunkInventory)
    assert inventory.actualFiles == ["src/app/a.py", "src/app/b.py"]
    assert [(c.filePath, c.diffPath) for c in inventory.chunks] == [
        ("src/app/a.py", "src.app.a.py.md"),
        ("src/app/b.py", "src.app.b.py.md"),
    ]


async def test_list_chunk_files_handles_duplicates_colons_spaces_and_noise(
    live_sandbox: AsyncE2BSandbox,
) -> None:
    pr_number = 12
    head_sha = "b" * 40
    await _seed_chunks(
        live_sandbox,
        pr_number=pr_number,
        head_sha=head_sha,
        files={
            # Two chunks, one real path: the glob-first file wins.
            "02.a.py.md": _chunk_body("src/app/a.py"),
            "01.a.py.md": _chunk_body("src/app/a.py"),
            # Chunk name with a colon + trailing non-header noise line.
            "weird:name.py.md": _chunk_body("src/weird.py")
            + "\nA reviewer note that is not a header.\n",
            # Real path with a space.
            "src.app.my module.py.md": _chunk_body("src/app/my module.py"),
            # No header at all: contributes no inventory entry.
            "notes.md": "just some notes\nno headers here\n",
        },
    )

    inventory = await listChunkFiles(
        live_sandbox,
        repoId=RepoId("list-chunks-repo"),
        prNumber=PRNumber(pr_number),
        headSha=CommitId(head_sha),
    )

    assert isinstance(inventory, ChunkInventory)
    assert inventory.actualFiles == [
        "src/app/a.py",
        "src/app/my module.py",
        "src/weird.py",
    ]
    assert [(c.filePath, c.diffPath) for c in inventory.chunks] == [
        ("src/app/a.py", "01.a.py.md"),
        ("src/app/my module.py", "src.app.my module.py.md"),
        ("src/weird.py", "weird:name.py.md"),
    ]


@pytest.mark.parametrize("make_empty_dir", [False, True])
async def test_list_chunk_files_errors_when_no_chunks(
    live_sandbox: AsyncE2BSandbox, make_empty_dir: bool
) -> None:
    """Missing dir and chunk-less dir are both business errors, not retries."""
    pr_number = 21 if make_empty_dir else 20
    head_sha = "d" * 40
    if make_empty_dir:
        mkdir = await live_sandbox.aexecute(
            f"mkdir -p {_chunks_dir(pr_number, head_sha)}",
            timeout=_CMD_TIMEOUT_S,
        )
        assert mkdir.exit_code == 0, f"mkdir failed: {mkdir.output!r}"

    result = await listChunkFiles(
        live_sandbox,
        repoId=RepoId("list-chunks-repo"),
        prNumber=PRNumber(pr_number),
        headSha=CommitId(head_sha),
    )

    assert isinstance(result, ChunkListError)
    assert result.retryable is False
    assert result.message.strip() != ""
    assert result.prNumber == PRNumber(pr_number)
    assert result.headSha == CommitId(head_sha)
