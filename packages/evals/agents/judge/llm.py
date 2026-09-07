"""Chat-model factory for the judge lane (env-driven, same factory as prod)."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.services.llm.errors import LLMConfigError
from app.services.llm.service import createDefaultLLMContext, createLLMModel


def build_model() -> BaseChatModel:
    """Build the judge's chat model from the env (``LLM_MODEL`` / ``LLM_API_KEY``)."""
    model = createLLMModel(createDefaultLLMContext())
    if isinstance(model, LLMConfigError):
        raise RuntimeError(f"failed to build chat model: {model}")
    return model


def model_name() -> str:
    """The configured ``provider:model`` string (report metadata)."""
    return createDefaultLLMContext().model


__all__ = ["build_model", "model_name"]