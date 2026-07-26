"""Manual smoke test for the LLM provider config used by the review workflow.

Calls ``_resolve_llm_config()`` from the webhook adapter, builds a chat
model from it, creates a vanilla E2B sandbox, wires both into a minimal
``create_deep_agent`` with a Pydantic ``response_format`` schema and a
single custom tool. If this script works but the real workflow fails,
the problem is in the review-agent stack (subagents, long prompts,
HunkMap), not the provider config.

Run from ``packages/api/``:

    uv run python scripts/test_llm_provider.py
"""

from __future__ import annotations

import asyncio
import logging
import sys

from deepagents import create_deep_agent
from e2b import AsyncSandbox
from langchain_core.tools import tool
from langchain_e2b import AsyncE2BSandbox
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm import build_chat_model
from app.services.review.webhook import _resolve_llm_config

log = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.DEBUG)


class EchoResult(BaseModel):
    """Structured output for the smoke test."""

    greeting: str = Field(description="Short greeting the assistant produced")
    tool_used: bool = Field(description="Whether the echo_word tool was called")
    echoed_word: str | None = Field(
        default=None, description="The word that was passed to echo_word, if any"
    )


@tool
def echo_word(word: str) -> str:
    """Echo the given word back to the caller.

    Args:
        word: The word to echo.

    Returns:
        The word, unchanged.
    """
    return word


async def main() -> int:
    provider, base_url, api_key, model = _resolve_llm_config()
    log.info(
        "llm config: provider=%s base_url=%s model=%s key=%s…",
        provider,
        base_url,
        model,
        api_key[:6],
    )

    chat = build_chat_model(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        headers={"cf-aig-gateway-id": "sentinal-ai-gateway"},
    )

    log.info("creating e2b sandbox…")
    sandbox = await AsyncSandbox.create(
        api_key=settings.e2b_api_key,
        timeout=600,
    )
    log.info("sandbox ready: id=%s", sandbox.sandbox_id)

    try:
        backend = AsyncE2BSandbox(sandbox=sandbox)
        agent = create_deep_agent(
            model=chat,
            backend=backend,
            system_prompt="You are a helpful assistant. Reply briefly.",
            response_format=EchoResult,
            tools=[echo_word],
        )
        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Call the echo_word tool with word='hello'. "
                            "with greeting='done', "
                            "tool_used=true, and echoed_word='hello'."
                        ),
                    }
                ]
            }
        )

        # agent = create_agent(
        #     model=chat,
        #     system_prompt="You are a helpful assistant. Reply briefly.",
        #     tools=[echo_word],
        #     response_format=ToolStrategy(EchoResult),
        # )
        # result = await agent.ainvoke(
        #     {
        #         "messages": [
        #             {
        #                 "role": "user",
        #                 "content": "Call echo_word with word='hello', then return the result.",
        #             }
        #         ]
        #     }
        # )

        messages = result.get("messages", [])
        last = messages[-1] if messages else None
        log.info("last message content: %s", getattr(last, "content", last))
        log.info("last message tool_calls: %s", getattr(last, "tool_calls", None))
        log.info("structured_response: %s", result.get("structured_response"))

    except Exception as e:
        body = getattr(e, "body", None) or getattr(
            getattr(e, "response", None), "text", None
        )
        print("RAW ERROR BODY:", body)

        raise
    finally:
        await sandbox.kill()
        log.info("sandbox killed")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(main()))
