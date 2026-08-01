"""Shared chat-model factory and :class:`LLMConfig` value object.

This module owns the single place where Sentinel constructs a LangChain
chat model from a configuration. Both the review and setup agents
consume it, so the factory lives in :mod:`app.core` rather than inside
either service.

Two surfaces are exported:

- :class:`LLMConfig` — a frozen, DBOS-serializable Pydantic model that
  bundles every knob the chat-model factory needs (``model`` /
  ``api_key`` / ``base_url`` / ``headers`` / ``max_retries`` /
  ``rate_limit_rps``). A single value object replaces the four
  scattered fields (``provider`` / ``base_url`` / ``api_key`` /
  ``model``) that today cross the webhook → workflow → step
  boundary.

- :func:`build_chat_model` — a pure factory that takes an
  :class:`LLMConfig` plus an optional ``callbacks`` list and returns
  a :class:`langchain_core.language_models.BaseChatModel`. Provider
  dispatch is delegated to LangChain's
  :func:`langchain.chat_models.init_chat_model`, which accepts the
  combined ``"provider:model"`` string and picks the right
  integration package.

Why ``"provider:model"``:

- LangChain's :func:`init_chat_model` is built around the
  ``provider:model`` convention. Encoding it as a single string
  means we never have to maintain a ``Literal[...]`` union of
  supported providers — :func:`init_chat_model` raises on an
  unknown prefix.
- The same string is reusable across :mod:`.routers`, ``.webhook``,
  and any future UI surface without re-parsing.

The factory is **provider-agnostic** in the sense that it doesn't
branch on the provider. The provider-specific knobs (``base_url`` /
``default_headers`` / ``rate_limiter``) are applied uniformly and
forwarded as kwargs to :func:`init_chat_model`, which silently
drops ones the resolved provider class doesn't accept (and warns
when transferring a kwarg to ``model_kwargs`` — see the Google
GenAI note in the function docstring).
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from pydantic import BaseModel, ConfigDict, Field, SecretStr

log = logging.getLogger(__name__)


class LLMConfig(BaseModel):
    """Frozen, DBOS-serializable LLM configuration.

    A single value object that replaces the four scattered fields
    (``provider`` / ``base_url`` / ``api_key`` / ``model``) that
    used to cross the webhook → workflow → step boundary. The
    ``model`` field is the combined ``"provider:model"`` string
    that LangChain's :func:`init_chat_model` consumes (e.g.
    ``"openai:gpt-5.5"``, ``"anthropic:claude-opus-4-6"``,
    ``"google_genai:gemini-3.6-flash"``).

    The ``api_key`` is stored as a plain ``str`` (not
    :class:`pydantic.SecretStr`) so DBOS can serialize the config
    to its system database without losing the credential. The
    factory wraps it in :class:`SecretStr` at the chat-model
    construction boundary, which is the only place the value is
    actually used.

    Examples:
        >>> LLMConfig(model="openai:gpt-5.5", api_key="sk-…")
        >>> LLMConfig(model="anthropic:claude-opus-4-6", api_key="…")
        >>> LLMConfig(
        ...     model="openai:gpt-5.5",
        ...     api_key="…",
        ...     base_url="https://api.cloudflare.com/.../ai/v1",
        ...     headers={"cf-aig-gateway-id": "sentinal-ai-gateway"},
        ... )
    """

    model_config = ConfigDict(frozen=True)

    model: str = Field(
        description=(
            'The combined "provider:model" string consumed by '
            "langchain.chat_models.init_chat_model. Examples: "
            "'openai:gpt-5.5', 'anthropic:claude-opus-4-6', "
            "'google_genai:gemini-3.6-flash'."
        ),
    )
    api_key: str | None = Field(
        default=None,
        description=(
            "API key for the active provider. Leave empty to defer "
            "to the provider's native env-var resolution "
            "(OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY)."
        ),
    )
    base_url: str | None = Field(
        default=None,
        description=(
            "Base URL for the chat model. Required when proxying "
            "through an OpenAI-compatible gateway (Cloudflare AI "
            "Gateway, OpenCode Zen, Baseten, OpenRouter, Ollama, "
            "…). Ignored by providers that do not accept a base URL."
        ),
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Default HTTP headers attached to every request — "
            "e.g. gateway identifiers, project tags, or "
            "per-tenant routing hints. Forwarded to providers that "
            "accept a `default_headers` kwarg; ignored otherwise."
        ),
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description=(
            "Number of retries the underlying SDK will attempt on "
            "transient errors. 0 disables retries."
        ),
    )
    rate_limit_rps: float | None = Field(
        default=0.5,
        ge=0.0,
        description=(
            "Client-side requests-per-second rate limit applied via "
            "langchain_core.rate_limiters.InMemoryRateLimiter. "
            "0 / None disables the limiter (use when the SDK or "
            "upstream gateway enforces its own limits)."
        ),
    )

    @property
    def provider(self) -> str:
        """Return the provider prefix of :attr:`model`.

        Raises:
            ValueError: ``model`` does not contain a ``":"`` separator.
        """
        if ":" not in self.model:
            raise ValueError(
                f"LLMConfig.model must be a 'provider:model' string, got {self.model!r}"
            )
        return self.model.split(":", 1)[0]

    @property
    def model_id(self) -> str:
        """Return the model identifier (the part after ``":"`` in :attr:`model`)."""
        if ":" not in self.model:
            raise ValueError(
                f"LLMConfig.model must be a 'provider:model' string, got {self.model!r}"
            )
        return self.model.split(":", 1)[1]


def build_chat_model(
    *,
    config: LLMConfig,
    callbacks: list[BaseCallbackHandler] | None = None,
) -> BaseChatModel:
    """Construct a LangChain chat model from a single :class:`LLMConfig`.

    Pure factory — no I/O, no settings reads. Provider dispatch is
    delegated to :func:`langchain.chat_models.init_chat_model`,
    which accepts the ``"provider:model"`` string and picks the
    right integration package.

    Knobs are forwarded as kwargs to :func:`init_chat_model`:

    - ``max_retries`` — applied to every provider that supports it.
    - ``rate_limiter`` — applied to every provider that supports
      it; built from a fresh :class:`InMemoryRateLimiter` per call
      so each chat-model instance has its own bucket.
    - ``base_url`` — forwarded to providers that accept one
      (OpenAI-compatible ones, plus Anthropic and Google). Ignored
      by providers that don't.
    - ``default_headers`` — forwarded to providers that accept one
      (OpenAI-compatible ones and Anthropic). For
      :class:`ChatGoogleGenerativeAI` the kwarg gets transferred
      to ``model_kwargs`` and emits a LangChain ``UserWarning``;
      this is the upstream library's behaviour, not ours.
    - ``api_key`` — wrapped in :class:`SecretStr` at the
      construction boundary so it never lands in a log line.

    ``callbacks`` is forwarded to every provider constructor.
    LangChain threads the chat model's callbacks through every
    inner run, so attaching a handler here captures every LLM
    call and tool invocation a deep-agent makes internally — not
    just the outer ``ainvoke``. The review-agent observability
    handler is built in
    :func:`app.core.llm_callbacks.make_llm_io_handler` and passed
    through this kwarg.

    Raises:
        ValueError: :attr:`LLMConfig.model` is not a valid
            ``"provider:model"`` string, or the provider prefix is
            not supported by LangChain.
    """
    init_kwargs: dict[str, Any] = {"max_retries": config.max_retries}
    if config.rate_limit_rps is not None and config.rate_limit_rps > 0:
        init_kwargs["rate_limiter"] = InMemoryRateLimiter(
            requests_per_second=config.rate_limit_rps
        )
    if config.base_url:
        init_kwargs["base_url"] = config.base_url
    if config.headers:
        init_kwargs["default_headers"] = dict(config.headers)

    provider = config.provider
    extra = {}
    if (
        provider == "openai"
        and config.model_id
        and config.model_id.startswith(("gpt-5.6"))
    ):
        extra = {
            "use_responses_api": True,
            "output_version": "responses/v1",
        }

    return init_chat_model(
        model=config.model,
        api_key=SecretStr(config.api_key) if config.api_key else None,
        callbacks=callbacks,
        **init_kwargs,
        **extra,
    )


__all__: list[str] = ["LLMConfig", "build_chat_model"]
