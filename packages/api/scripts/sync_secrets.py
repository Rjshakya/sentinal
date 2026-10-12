"""Sync ``.env.production`` to Secrets Manager as JSON.

Read the env file with UTF-8 via ``dotenv``, convert it to JSON, save
the JSON to the system temp dir with a timestamped name (no clashes),
upload it with ``update-secret`` (full replacement, which is how stale
keys disappear), then delete the temp file. Never logs secret values —
only key names.

Run from ``packages/api/`` (same convention as the other scripts):

    uv run --with python-dotenv python scripts/sync_secrets.py --check
    uv run --with python-dotenv python scripts/sync_secrets.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - surfaced as a clear error below
    dotenv_values = None  # type: ignore[no-redef]

log = logging.getLogger(__name__)

REQUIRED_KEYS: tuple[str, ...] = (
    "PORT",
    "APP_ENV",
    "APP_NAME",
    "DATABASE_URL",
    "CORS_ORIGINS",
    "API_PREFIX",
    "WORKOS_API_KEY",
    "WORKOS_CLIENT_ID",
    "WORKOS_REDIRECT_URI",
    "WORKOS_COOKIE_PASSWORD",
    "FRONTEND_URL",
    "GITHUB_APP_ID",
    "GITHUB_APP_CLIENT_ID",
    "GITHUB_APP_CLIENT_SECRET",
    "GITHUB_APP_SLUG",
    "GITHUB_WEBHOOK_SECRET",
    "GITHUB_INSTALL_STATE_SECRET",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_DEFAULT_HEADERS",
    "SANDBOX_PROVIDER",
    "E2B_API_KEY",
    "E2B_TEMPLATE",
    "DAYTONA_API_KEY",
    "OPENAI_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "GITHUB_APP_PRIVATE_KEY",
)
"""Keys the template resolves plus the runtime-read private key.

Every ``{{resolve:secretsmanager:...:KEY}}`` in ``template.yaml`` must
be present; ``GITHUB_APP_PRIVATE_KEY`` is read at runtime via
``app.core.secrets`` (never a Lambda env var) but must still be in the
JSON or private-key flows break.
"""


@dataclass(frozen=True)
class Options:
    """Validated CLI options (fully typed; never carries secret values)."""

    env_file: Path | None
    secret_id: str
    region: str
    check: bool


def parseArgs(argv: list[str] | None = None) -> Options:
    """Parse CLI args into :class:`Options`."""
    parser = argparse.ArgumentParser(
        description="Sync .env.production to Secrets Manager as JSON."
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to the env file (default: packages/api/.env.production).",
    )
    parser.add_argument("--secret-id", default="sentinel-dev/app")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Diff key names only; do not upload.",
    )
    ns = parser.parse_args(argv)
    raw_env = ns.env_file
    return Options(
        env_file=Path(str(raw_env)) if raw_env is not None else None,
        secret_id=str(ns.secret_id),
        region=str(ns.region),
        check=bool(ns.check),
    )


def defaultEnvFile() -> Path:
    """Return ``packages/api/.env.production`` next to this script."""
    return Path(__file__).resolve().parents[1] / ".env.production"


def cleanKey(raw_key: str) -> str:
    """Strip BOM and edge whitespace from an env key name."""
    return raw_key.replace("\ufeff", "").strip()


def cleanValue(raw_value: str) -> str:
    """Strip edge whitespace/newlines; preserve inner content byte-identical."""
    return raw_value.strip()


def loadEnvFile(env_path: Path) -> dict[str, str]:
    """Read the env file as UTF-8; return a cleaned key-to-value map.

    Keys are BOM-stripped and trimmed; values are edge-trimmed only.
    Renames log by repr (names only, never values).
    """
    if dotenv_values is None:
        raise RuntimeError(
            "python-dotenv is missing: rerun with "
            "'uv run --with python-dotenv ...'."
        )
    raw: dict[str, str | None] = dotenv_values(env_path, encoding="utf-8")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not key or value is None:
            continue
        cleaned_key = cleanKey(key)
        if not cleaned_key:
            continue
        if cleaned_key != key:
            log.info("Cleaned key name: %r -> %r", key, cleaned_key)
        if cleaned_key in out:
            log.info("Duplicate key after cleanup, last wins: %r", cleaned_key)
        out[cleaned_key] = cleanValue(value)
    return out


def findMissing(data: dict[str, str]) -> list[str]:
    """Return required keys that are absent or blank."""
    return [key for key in REQUIRED_KEYS if not data.get(key, "").strip()]


def writeTempJson(data: dict[str, str]) -> Path:
    """Write JSON to the system temp dir with a timestamped name."""
    temp_dir = Path(tempfile.gettempdir()) / "opencode"
    temp_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = temp_dir / f"secret-{stamp}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def readLiveKeys(secret_id: str, region: str) -> set[str]:
    """Return key names in the live secret (never values)."""
    import boto3

    client: Any = boto3.client("secretsmanager", region_name=region)
    resp: Any = client.get_secret_value(SecretId=secret_id)
    payload = str(resp.get("SecretString", "{}"))
    parsed: Any = json.loads(payload)
    if not isinstance(parsed, dict):
        raise RuntimeError("Live secret is not a JSON object.")
    return {str(key) for key in parsed.keys()}


def uploadJson(secret_id: str, region: str, temp_path: Path) -> None:
    """Replace the secret value with the temp JSON file content."""
    import boto3

    client: Any = boto3.client("secretsmanager", region_name=region)
    client.update_secret(
        SecretId=secret_id,
        SecretString=temp_path.read_text(encoding="utf-8"),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the sync; return the process exit code."""
    opts = parseArgs(argv)
    env_path = opts.env_file or defaultEnvFile()
    if not env_path.is_file():
        log.error("Missing env file: %s", env_path)
        return 1
    try:
        data = loadEnvFile(env_path)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    missing = findMissing(data)
    if missing:
        log.error("Missing required keys: %s", ", ".join(missing))
        return 1
    try:
        live = readLiveKeys(opts.secret_id, opts.region)
    except Exception as exc:
        log.error("Cannot read live secret: %s: %s", type(exc).__name__, exc)
        return 1
    new_keys = set(data.keys())
    log.info("Add: %s", ", ".join(sorted(new_keys - live)) or "(none)")
    log.info("Remove: %s", ", ".join(sorted(live - new_keys)) or "(none)")
    if opts.check:
        log.info("Check only. No upload.")
        return 0
    temp_path: Path | None = None
    try:
        temp_path = writeTempJson(data)
        log.info("Wrote: %s", temp_path)
        uploadJson(opts.secret_id, opts.region, temp_path)
        log.info("Uploaded to: %s", opts.secret_id)
    except Exception as exc:
        log.error("Upload failed: %s: %s", type(exc).__name__, exc)
        return 1
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception as exc:
                log.warning("Delete temp file by hand %s: %s", temp_path, exc)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
