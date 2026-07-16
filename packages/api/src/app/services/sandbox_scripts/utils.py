"""Single source of truth for the in-sandbox layout.

Both the host-side orchestrator (``app.services.indexing`` /
``app.services.retrieval``) and the in-sandbox scripts import this
module. The host copy is uploaded to the sandbox at
``<sandbox_home>/<workspace_name>/context/utils.py`` by
:meth:`app.services.indexing.upload_scripts`, so the same constants are
valid on both sides.

Layout::

    /home/user/                              <- sandbox_home()
    +-- sentinel-workspace/                  <- workspace_path()
    |   +-- context/                         <- scripts_path()
    |   |   +-- chunking.py
    |   |   +-- ingestion.py
    |   |   +-- embedding.py
    |   |   +-- search.py
    |   |   +-- utils.py
    |   |   +-- .env                         (renamed from sandbox.env)
    |   +-- <repo_name>/                     <- repo_path(repo_name)
    +-- lance_data/                          <- lance_path()
"""

from __future__ import annotations

SANDBOX_HOME: str = "/home/user"
WORKSPACE_NAME: str = "sentinel-workspace"
SCRIPTS_NAME: str = "context"
LANCEDB_NAME: str = "lance_data"

SCRIPT_FILES: tuple[str, ...] = (
    "chunking.py",
    "ingestion.py",
    "embedding.py",
    "search.py",
    "utils.py",
    "sandbox.env",
)


def sandbox_home() -> str:
    return SANDBOX_HOME


def workspace_path() -> str:
    return f"{SANDBOX_HOME}/{WORKSPACE_NAME}"


def scripts_path() -> str:
    return f"{workspace_path()}/{SCRIPTS_NAME}"


def repo_path(repo_name: str) -> str:
    return f"{workspace_path()}/{repo_name}"


def lance_path() -> str:
    return f"{SANDBOX_HOME}/{LANCEDB_NAME}"


def table_name(repo_name: str) -> str:
    return f"{repo_name}_table"
