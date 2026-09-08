"""Chat-model factory for the judge lane (env-driven, same factory as prod)."""

from __future__ import annotations
from uuid import uuid4

from app.services.llm.types import LLMCtx
from app.utils.branded import BaseUrl
from langchain_core.language_models.chat_models import BaseChatModel

from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createDefaultLLMContext, createLLMModel


def build_model(sessionId: str) -> tuple[BaseChatModel, LLMCtx]:
    """Build the judge's chat model from the env (``LLM_MODEL`` / ``LLM_API_KEY``)."""

    session_id = f"sentinal-eval-judge-{sessionId}"
    ctx = createDefaultLLMContext(
        model="openai:gpt-5.6-luna",
        baseUrl=BaseUrl("https://opencode.ai/zen/go/v1"),
        headers={"x-opencode-session": session_id},
    )

    model = createLLMModel(ctx=ctx)
    if isinstance(model, LLMConfigError):
        raise RuntimeError(f"failed to build chat model: {model}")
    return model, ctx


def model_name() -> str:
    """The configured ``provider:model`` string (report metadata)."""
    return createDefaultLLMContext().model


__all__ = ["build_model", "model_name"]
