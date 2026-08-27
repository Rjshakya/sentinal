"""Provider-pluggable LLM service types.

This module owns the *contract* of the LLM service: the serializable
:class:`LLMCtx` (pure data — everything the model factory needs), the
error variant of the context-creator union (:class:`LLMContextError`),
and the branded identifier types the package carries.

Naming convention: this package intentionally uses **camelCase**
identifiers — the same convention as :mod:`app.services.sandbox`. The
one exception is the value-object shape of :class:`LLMCtx`, which maps
onto the snake_case :class:`app.core.llm.LLMConfig` at the
:func:`app.services.llm.service.createLLMModel` boundary.

Design notes:

- :class:`LLMCtx` is a plain Pydantic model (DBOS-serializable) so it
  can cross workflow boundaries. It carries every knob the chat-model
  factory needs — model, key, base URL, headers, retries, rate limit —
  and nothing else.
- Ids and keys are **branded types** (``NewType`` over ``str``): they
  erase to ``str`` at runtime (Pydantic validation and DBOS
  serialization are unaffected) but pyright enforces the branding
  statically, so a bare ``str`` cannot accidentally flow into a ctx.
- :class:`LLMContextError` is the error variant of the
  ``LLMCtx | LLMContextError`` union returned by the per-user context
  creator (:func:`app.services.llm.service.createUserLLMContext`). It
  is a Pydantic model so it survives the same workflow boundaries as
  the ctx; callers discriminate with ``isinstance``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.llm.errors import LLMConfigError
from app.utils.branded import ApiKey, BaseUrl, UserId


class LLMCtx(BaseModel):
    """Everything a chat-model build needs, as pure serializable data.

    Assembled by :func:`app.services.llm.service.createDefaultLLMContext`
    (settings-driven) or :func:`app.services.llm.service.createUserLLMContext`
    (per-user DB row); consumed by
    :func:`app.services.llm.service.createLLMModel`, which converts it to
    :class:`app.core.llm.LLMConfig` at the factory boundary.
    """

    model: str = Field(
        min_length=1,
        description=(
            'The combined "provider:model" string consumed by '
            "langchain.chat_models.init_chat_model. Examples: "
            "'openai:gpt-5.5', 'anthropic:claude-opus-4-6', "
            "'google_genai:gemini-3.6-flash'."
        ),
    )
    apiKey: ApiKey | None = None
    """API key for the active provider; ``None`` defers to the provider's
    native env-var resolution."""

    baseUrl: BaseUrl | None = None
    """Base URL for the chat model (required when proxying through an
    OpenAI-compatible gateway)."""

    defaultHeaders: dict[str, str] = Field(
        default_factory=dict,
        description="HTTP headers attached to every request (gateway ids, tags).",
    )
    maxRetries: int = Field(
        default=3,
        ge=0,
        description="Retries the underlying SDK attempts on transient errors.",
    )
    rateLimitRps: float | None = Field(
        default=0.5,
        ge=0.0,
        description="Client-side requests-per-second rate limit; 0 / None disables.",
    )

    @property
    def provider(self) -> str:
        """Return the provider prefix of :attr:`model`.

        Raises:
            LLMConfigError: ``model`` does not contain a ``":"`` separator.
        """
        if ":" not in self.model:
            raise LLMConfigError(
                f"LLMCtx.model must be a 'provider:model' string, got {self.model!r}"
            )
        return self.model.split(":", 1)[0]

    @property
    def modelId(self) -> str:
        """Return the model identifier (the part after ``":"`` in :attr:`model`).

        Raises:
            LLMConfigError: ``model`` does not contain a ``":"`` separator.
        """
        if ":" not in self.model:
            raise LLMConfigError(
                f"LLMCtx.model must be a 'provider:model' string, got {self.model!r}"
            )
        return self.model.split(":", 1)[1]


__all__ = [
    "ApiKey",
    "BaseUrl",
    "LLMCtx",
    "UserId",
]
