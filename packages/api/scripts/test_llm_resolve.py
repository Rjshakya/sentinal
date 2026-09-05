"""Multi-provider smoke test for :class:`app.core.llm.LLMConfig`.

Iterates a hard-coded list of ``"provider:model"`` strings and prints
the resolved :class:`LLMConfig` and the chat-model class
:func:`langchain.chat_models.init_chat_model` returns. Catches
provider-prefix typos and missing integration packages without
hitting the network.

Run from ``packages/api/``:

    uv run python scripts/test_llm_resolve.py

The script does NOT need any API keys. Provider resolution happens
in :func:`init_chat_model`; the resulting :class:`BaseChatModel`
may complain about a missing key at construction time (depending
on the provider) but the class lookup itself does not require one.
For providers where construction fails on missing creds, the script
catches the failure and reports it as ``unresolved``.
"""

from __future__ import annotations

import logging
import sys
from typing import NamedTuple

from app.core.llm import LLMConfig, build_chat_model

log = logging.getLogger(__name__)


class _Case(NamedTuple):
    label: str
    model: str
    base_url: str | None = None
    headers: dict[str, str] | None = None


CASES: list[_Case] = [
    # Provider prefixes recognised by init_chat_model today.
    _Case("openai direct", "openai:gpt-5.5"),
    _Case(
        "openai via CF AI Gateway",
        "openai:gpt-5.5",
        base_url="https://api.cloudflare.com/client/v4/accounts/abc/ai/v1",
        headers={"cf-aig-gateway-id": "sentinal-ai-gateway"},
    ),
    _Case("anthropic direct", "anthropic:claude-opus-4-6"),
    _Case(
        "anthropic via OpenCode Zen",
        "anthropic:minimax-m3",
        base_url="https://opencode.ai/zen/go",
    ),
    _Case("google_genai direct", "google_genai:gemini-3.6-flash"),
    # Provider prefixes from the docs that require additional
    # integration packages not currently in pyproject.toml. These
    # are expected to fail today with an ImportError — useful as
    # a check that the LLMConfig API is provider-agnostic.
    _Case("baseten (no integration pkg)", "baseten:zai-org/GLM-5.2"),
    _Case("fireworks (no integration pkg)", "fireworks:accounts/fireworks/models/glm-5p1"),
    _Case("openrouter (no integration pkg)", "openrouter:z-ai/glm-5.1"),
    _Case("ollama (no integration pkg)", "ollama:minimax-m2.7:cloud"),
    # Malformed model strings — should fail the provider property.
    _Case("malformed: no colon", "gpt-5.5"),
]


def _try_resolve(case: _Case) -> str:
    """Resolve one case and return a one-line summary."""
    try:
        cfg = LLMConfig(
            model=case.model,
            api_key="test-key-not-real",
            base_url=case.base_url,
            headers=case.headers or {},
        )
        provider = cfg.provider
        model_id = cfg.model_id
    except Exception as exc:  # ValidationError, ValueError, etc.
        return f"  rejected (LLMConfig): {type(exc).__name__}: {exc}"

    try:
        model = build_chat_model(config=cfg)
    except Exception as exc:
        return (
            f"  provider={provider!r} model_id={model_id!r} "
            f"  unresolved: {type(exc).__name__}: {exc}"
        )

    return (
        f"  provider={provider!r} model_id={model_id!r} "
        f"  resolved: {type(model).__module__}.{type(model).__name__}"
    )


def main() -> int:
    log.info("resolving %d LLMConfig cases", len(CASES))
    print("=" * 72)
    for case in CASES:
        print(f"[{case.label}]  model={case.model!r}")
        if case.base_url:
            print(f"    base_url={case.base_url}")
        if case.headers:
            print(f"    headers={case.headers}")
        print(_try_resolve(case))
        print()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
