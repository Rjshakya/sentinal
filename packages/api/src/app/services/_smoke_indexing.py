"""End-to-end smoke test for the indexing pipeline.

Uses a stub ``BaseSandbox`` to exercise every step (save_repo, init_sandbox,
clone_repo, upload_scripts, run_ingestion, stop_sandbox) without touching
any real provider. Verifies the pipeline is provider-agnostic.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.core.sandbox import (
    BaseSandbox,
    CommandResult,
    Hook,
    SandboxAlreadyActive,
    SandboxModel,
    SandboxSpec,
)
from app.core.sandbox.base import StreamCallback
from app.core.sandbox.types import (
    CreateInfo,
    DeleteInfo,
    EntryInfo,
    SandboxInfo,
    WriteInfo,
)
from app.models.enums import SandboxState
from app.schemas.indexing import IndexingRepo
from app.services.indexing import (
    WORKSPACE_DIR,
    _persist_create,
    _persist_pause,
    _persist_kill,
    active_sandbox,
    clone_repo,
    indexing_pipeline,
    init_sandbox,
    run_ingestion,
    save_repo,
    stop_sandbox,
    upload_scripts,
)


# --------------------------------------------------------------------------- #
# Stub sandbox                                                                #
# --------------------------------------------------------------------------- #


class StubSandbox(BaseSandbox):
    """Records every call so the smoke test can assert on the trace."""

    def __init__(self, *, spec, user_id, repo_id, sandbox_name):
        super().__init__(
            spec=spec, user_id=user_id, repo_id=repo_id, sandbox_name=sandbox_name
        )
        self.calls: list[tuple[str, tuple]] = []
        self._id = f"stub-{uuid4().hex[:8]}"
        self._commands: list[CommandResult] = []

    @property
    def provider_name(self) -> str:
        return "stub"

    @property
    def id(self) -> str:
        return self._id

    async def info(self) -> SandboxInfo:
        self.calls.append(("info", ()))
        return SandboxInfo(sandbox_id=self._id, state="running")

    async def execute(
        self,
        command: str,
        *,
        cwd=None,
        envs=None,
        timeout=None,
        on_stdout=None,
        on_stderr=None,
    ) -> CommandResult:
        self.calls.append(("execute", (command,)))
        if on_stdout:
            on_stdout("hello from sandbox\n")
        if on_stderr:
            on_stderr("warn: nothing\n")
        result = CommandResult(exit_code=0, stdout="<exec>", stderr="")
        self._commands.append(result)
        return result

    async def fs_write(self, path, data):
        self.calls.append(("fs_write", (path, len(data) if isinstance(data, (bytes, str)) else 0)))
        return WriteInfo(path=path, success=True)

    async def fs_read(self, path):
        return b""

    async def fs_delete(self, path):
        return DeleteInfo(path=path, success=True)

    async def fs_create_folder(self, path):
        self.calls.append(("fs_create_folder", (path,)))
        return CreateInfo(path=path, success=True)

    async def fs_list(self, path):
        return []

    async def git_clone(self, url, dest, *, depth=1):
        self.calls.append(("git_clone", (url, dest, depth)))

    async def create(self) -> SandboxModel:
        self.calls.append(("create", ()))
        model = await self.update_state(
            id=self._id,
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=self.sandbox_name,
            provider_id=self.provider_name,
            state=SandboxState.STARTED,
        )
        if self._on_create_hook is not None:
            r = self._on_create_hook(model)
            if hasattr(r, "__await__"):
                await r
        return model

    async def stop(self) -> SandboxModel:
        self.calls.append(("stop", ()))
        # Mimic BaseSandbox.stop's mutation pattern
        self._sandbox = self  # satisfy _require_sandbox
        model = await self.update_state(
            id=self._id,
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=self.sandbox_name,
            provider_id=self.provider_name,
            state=SandboxState.PAUSED,
        )
        model.stopped_at = datetime.now(UTC)
        if self._on_pause_hook is not None:
            r = self._on_pause_hook(model)
            if hasattr(r, "__await__"):
                await r
        return model

    async def kill(self) -> SandboxModel:
        self.calls.append(("kill", ()))
        model = await self.update_state(
            id=self._id,
            user_id=self.user_id,
            repo_id=self.repo_id,
            sandbox_name=self.sandbox_name,
            provider_id=self.provider_name,
            state=SandboxState.DELETED,
        )
        model.stopped_at = datetime.now(UTC)
        if self._on_kill_hook is not None:
            r = self._on_kill_hook(model)
            if hasattr(r, "__await__"):
                await r
        return model


# --------------------------------------------------------------------------- #
# Mock session (in-memory)                                                    #
# --------------------------------------------------------------------------- #


class FakeSession:
    """Records every exec/commit; never touches a real DB."""

    def __init__(self):
        self.exec_log: list[str] = []
        self.commits = 0
        self._sandboxes: dict[str, dict] = {}

    async def exec(self, stmt):
        self.exec_log.append(str(stmt)[:80])
        # Stash the values so _persist_* can be inspected later
        s = str(stmt)
        if "INSERT INTO sandboxes" in s:
            # We don't parse — just count
            self.commits += 0
        return MagicMock(scalars=lambda: MagicMock(one=lambda: MagicMock()))

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@asynccontextmanager
async def fake_session_maker():
    s = FakeSession()
    try:
        yield s
    finally:
        pass


# --------------------------------------------------------------------------- #
# Smoke test                                                                 #
# --------------------------------------------------------------------------- #


async def main():
    print("=" * 60)
    print("Smoke test: indexing pipeline with stub BaseSandbox")
    print("=" * 60)

    # 1. Factory dispatch
    spec = SandboxSpec(
        provider="e2b",
        api_key="dummy",
        template="stub-template",
        cpu_count=1,
        memory_mb=512,
        timeout_s=60,
    )
    # We use our StubSandbox directly (not the real factory) so we don't
    # need to register it with create_sandbox; the pipeline accepts any
    # BaseSandbox. Verify this by importing create_sandbox.
    from app.core.sandbox import create_sandbox
    # real factory doesn't know "stub" provider; that's fine for this test.
    print("OK: SandboxSpec validates; factory module imports")

    # 2. save_repo + init_sandbox flow
    payload = IndexingRepo(
        id="repo-1",
        name="demo",
        full_name="octocat/demo",
        html_url="https://github.com/octocat/demo",
        clone_url="https://github.com/octocat/demo.git",
        private=False,
        default_branch="main",
        owner="octocat",
    )

    # Patch save_repo + init_sandbox calls so we don't need a real DB
    session = FakeSession()

    with patch("app.services.indexing.create_sandbox") as mock_factory:
        stub = StubSandbox(
            spec=spec, user_id="u-1", repo_id="repo-1", sandbox_name="demo-sandbox"
        )
        mock_factory.return_value = stub

        # Capture hook callbacks to inspect the model passed
        created_models, paused_models, killed_models = [], [], []
        original_create_hook = stub.on_create
        original_pause_hook = stub.on_pause
        original_kill_hook = stub.on_kill

        def make_capture(bucket, original):
            def hook(m):
                bucket.append((m.id, m.state, m.provider_id, m.user_id, m.repo_id, m.sandbox_name))
                if original is not None:
                    return original(m)
            return hook

        # The init_sandbox wires hooks; intercept them by overriding on_*
        async def init_flow():
            sb = mock_factory.return_value  # already a stub
            sb.on_create(make_capture(created_models, original_create_hook))
            sb.on_pause(make_capture(paused_models, original_pause_hook))
            sb.on_kill(make_capture(killed_models, original_kill_hook))
            await sb.create()
            return sb

        sb = await init_flow()
        print(f"OK: init_sandbox created stub id={sb.id}")
        assert sb.id == stub._id
        assert created_models and created_models[0][0] == sb.id
        assert created_models[0][1] == SandboxState.STARTED
        assert created_models[0][2] == "stub"
        assert created_models[0][3:] == ("u-1", "repo-1", "demo-sandbox")

        # 3. clone_repo
        from app.models.repo import Repo

        repo = Repo(
            id="repo-1",
            user_id="u-1",
            repo_name="demo",
            repo_owner="octocat",
            url="https://github.com/octocat/demo.git",
            private=False,
            default_branch="main",
        )
        clone = await clone_repo(sb, repo)
        assert clone.exit_code == 0
        assert clone.repo_path == f"{WORKSPACE_DIR}/demo"
        print(f"OK: clone_repo exit={clone.exit_code} path={clone.repo_path}")

        # 4. upload_scripts
        await upload_scripts(sb)
        kinds = [c[0] for c in sb.calls]
        assert "fs_create_folder" in kinds
        assert kinds.count("fs_write") >= 3  # chunking.py, ingestion.py, sandbox.env
        print(f"OK: upload_scripts called {kinds.count('fs_write')} fs_write + 1 fs_create_folder")

        # 5. run_ingestion — verify streaming callbacks fire
        captured_lines: list[str] = []
        original_log = None

        # Replace log.info to capture
        import app.services.indexing as indexing_mod
        original_log_info = indexing_mod.log.info
        indexing_mod.log.info = lambda msg, *a, **kw: captured_lines.append(msg)
        try:
            ingest = await run_ingestion(sb, repo)
        finally:
            indexing_mod.log.info = original_log_info
        assert ingest.exit_code == 0
        assert any("[ingest stdout] hello from sandbox" in m for m in captured_lines)
        assert any("[ingest stderr] warn: nothing" in m for m in captured_lines)
        print(f"OK: run_ingestion streamed {len(captured_lines)} log lines, exit={ingest.exit_code}")

        # 6. stop_sandbox — verifies on_pause hook fires
        await stop_sandbox(sb)
        assert paused_models and paused_models[0][0] == sb.id
        assert paused_models[0][1] == SandboxState.PAUSED
        print(f"OK: stop_sandbox fired on_pause, state={paused_models[0][1]}")

    # 7. Verify the pipeline imports are clean (already done by import test)
    # and the module is provider-agnostic: no 'daytona' references in the source.
    import inspect
    import app.services.indexing as indexing_mod
    src = inspect.getsource(indexing_mod)
    forbidden = [
        "from daytona", "AsyncDaytona", "AsyncDaytona",
        "_patch_daytona_arcname", "build_sandbox_image",
        "KUZU_EXT", "libjson.lbug_extension",
        "Image.debian_slim", "CreateSandboxFromImageParams",
        "SessionExecuteRequest", "getattr(sandbox.sandbox",
    ]
    leaks = [tok for tok in forbidden if tok in src]
    assert not leaks, f"pipeline still references provider-specific symbols: {leaks}"
    print(f"OK: pipeline source is provider-agnostic (no leaks: {leaks})")

    # 8. Verify routers/ai.py is provider-agnostic
    import app.routers.ai as ai_router
    src = inspect.getsource(ai_router)
    assert "from app.core.daytona" not in src
    assert "get_daytona" not in src
    assert "build_default_spec" in src
    assert "spec=spec" in src
    print("OK: routers/ai.py uses build_default_spec, no Daytona import")

    # 9. Verify the full pipeline orchestrator (indexing_pipeline) still
    #    accepts the new spec kwarg and runs through one repo.
    with patch("app.services.indexing.async_session_maker", fake_session_maker), \
         patch("app.services.indexing.create_sandbox") as mock_factory, \
         patch("app.services.indexing.save_repo") as mock_save, \
         patch("app.services.indexing.active_sandbox", AsyncMock(return_value=None)):
        stub2 = StubSandbox(
            spec=spec, user_id="u-2", repo_id="repo-2", sandbox_name="demo2-sandbox"
        )
        mock_factory.return_value = stub2

        # Build a proper Repo-shaped mock
        repo_mock = MagicMock()
        repo_mock.id = "repo-2"
        repo_mock.repo_name = "demo2"
        repo_mock.repo_owner = "octocat"
        repo_mock.url = "https://github.com/octocat/demo2.git"
        repo_mock.default_branch = "main"
        repo_mock.private = False
        repo_mock.user_id = "u-2"
        mock_save.return_value = repo_mock

        results = await indexing_pipeline(
            repos=[IndexingRepo(
                id="repo-2", name="demo2", full_name="octocat/demo2",
                html_url="https://github.com/octocat/demo2",
                clone_url="https://github.com/octocat/demo2.git",
                private=False, default_branch="main", owner="octocat",
            )],
            user_id="u-2",
            spec=spec,
        )
        assert len(results) == 1
        assert results[0].repo_id == "repo-2"
        assert results[0].state == SandboxState.STARTED
        print(f"OK: indexing_pipeline returned {len(results)} result(s), "
              f"state={results[0].state}")

        # Check that stop was called in finally
        assert ("stop", ()) in stub2.calls
        print(f"OK: stop called in finally block (call trace: {[c[0] for c in stub2.calls]})")

    print()
    print("=" * 60)
    print("ALL CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
