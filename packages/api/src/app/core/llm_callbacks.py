"""LLM I/O observability callback handler.

A :class:`langchain_core.callbacks.base.BaseCallbackHandler` that
captures every LLM call and tool invocation made by the review
agents and emits a structured JSON log line per event via
:func:`app.core.logging.structured_log`.

Why a callback handler (and not a wrapper around ``agent.ainvoke``):

- A single ``ainvoke`` against a deep-agent can make N LLM calls
  internally (multi-turn tool use). A wrapper around ``ainvoke`` only
  sees the outermost boundary.
- LangChain threads the chat model's ``callbacks`` through every
  inner run, so attaching a handler at the chat-model level captures
  every turn, every tool call, and every error.

Emitted events (per LLM call):

- ``llm_call_started`` — emitted in ``on_chat_model_start``. Carries
  the input size (message count + total bytes), the per-call index,
  and the correlation context. Emitted upfront so a hang or process
  kill leaves a record of the request.
- ``llm_call_completed`` — emitted in ``on_llm_end``. Carries the
  output size (bytes + tool call count), usage metadata, and latency.
- ``llm_call_failed`` — emitted in ``on_llm_error``. Carries the
  error class and message.

Emitted events (per tool invocation):

- ``tool_call_started`` / ``tool_call_completed`` — carry only the
  tool name and the langchain run ids. No input/output content.

The handler is **metadata-only**: input messages, output text, tool
inputs, and tool outputs are all dropped. This is intentional — a
multi-thousand-line PR review would produce log lines in the tens of
megabytes if we kept the content. The handler exists to count, time,
and correlate; it does not mirror the full conversation.

The handler is **off by default** (gated on
``settings.llm_log_io_enabled``). When off, no handler is attached
and there is zero per-call overhead. The factory
:func:`make_llm_io_handler` returns an empty list in that case.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from app.core.config import settings
from app.core.logging import structured_log

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Correlation context                                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Context:
    """Immutable correlation context for one agent invocation.

    One :class:`Context` is built per agent (orchestrator / summary /
    security / correctness / style) and shared across every LLM call
    and tool invocation that agent makes. The fields show up on every
    emitted log line, which is what makes a multi-agent log stream
    greppable.
    """

    agent_name: str
    repo_name: str
    repo_id: str
    pr_number: int
    head_sha: str
    workflow_id: str | None
    model: str


# --------------------------------------------------------------------------- #
# Per-call state                                                               #
# --------------------------------------------------------------------------- #


@dataclass
class _CallState:
    """In-flight state for one LLM call, keyed on langchain ``run_id``.

    Cleared in :meth:`LLMIOCallbackHandler._finish` after the
    completed/failed event has been emitted.
    """

    index: int
    started_at: float


# --------------------------------------------------------------------------- #
# Handler                                                                      #
# --------------------------------------------------------------------------- #


class LLMIOCallbackHandler(BaseCallbackHandler):
    """Structured-logging callback handler for review-agent LLM/tool events.

    See module docstring for the event schema.
    """

    def __init__(self, *, ctx: Context) -> None:
        self._ctx = ctx
        self._states: dict[UUID, _CallState] = {}
        self._counter: int = 0

    # -- chat model --                                                       #

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Record the LLM call's input size and emit ``llm_call_started``."""
        self._counter += 1
        self._states[run_id] = _CallState(
            index=self._counter,
            started_at=time.monotonic(),
        )

        message_count = sum(len(group) for group in messages)
        total_input_bytes = sum(_message_bytes(m) for group in messages for m in group)

        structured_log(
            "INFO",
            "llm_call_started",
            {
                **self._ctx_base(),
                "index": self._counter,
                "langchain_run_id": str(run_id),
                "langchain_parent_run_id": (
                    str(parent_run_id) if parent_run_id is not None else None
                ),
                "message_count": message_count,
                "total_input_bytes": total_input_bytes,
            },
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Emit ``llm_call_completed`` with output size, usage, and latency."""
        state = self._states.pop(run_id, None)
        if state is None:
            # Defensive: an end without a start (e.g. recovered run).
            return

        latency_ms = int((time.monotonic() - state.started_at) * 1000)
        output_bytes, tool_call_count, usage = _extract_output_metrics(response)

        structured_log(
            "INFO",
            "llm_call_completed",
            {
                **self._ctx_base(),
                "index": state.index,
                "langchain_run_id": str(run_id),
                "latency_ms": latency_ms,
                "output_bytes": output_bytes,
                "tool_call_count": tool_call_count,
                "usage": usage,
            },
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Emit ``llm_call_failed`` with the error class and message."""
        state = self._states.pop(run_id, None)
        index = state.index if state is not None else -1
        latency_ms: int | None = None
        if state is not None:
            latency_ms = int((time.monotonic() - state.started_at) * 1000)

        structured_log(
            "ERROR",
            "llm_call_failed",
            {
                **self._ctx_base(),
                "index": index,
                "langchain_run_id": str(run_id),
                "latency_ms": latency_ms,
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                },
            },
        )

    # -- tools --                                                            #

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Emit ``tool_call_started`` with the tool name only."""
        tool_name = _tool_name(serialized, kwargs)
        structured_log(
            "INFO",
            "tool_call_started",
            {
                **self._ctx_base(),
                "tool_name": tool_name,
                "tool_run_id": str(run_id),
                "tool_parent_run_id": (
                    str(parent_run_id) if parent_run_id is not None else None
                ),
            },
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Emit ``tool_call_completed`` with no body (metadata-only)."""
        structured_log(
            "INFO",
            "tool_call_completed",
            {
                **self._ctx_base(),
                "tool_run_id": str(run_id),
                "tool_parent_run_id": (
                    str(parent_run_id) if parent_run_id is not None else None
                ),
            },
        )

    # -- internals --                                                        #

    def _ctx_base(self) -> dict[str, Any]:
        """Return the per-event correlation envelope."""
        return {
            "agent": self._ctx.agent_name,
            "repo_name": self._ctx.repo_name,
            "repo_id": self._ctx.repo_id,
            "pr_number": self._ctx.pr_number,
            "head_sha": self._ctx.head_sha,
            "workflow_id": self._ctx.workflow_id,
            "model": self._ctx.model,
        }


# --------------------------------------------------------------------------- #
# Factory                                                                      #
# --------------------------------------------------------------------------- #


def make_llm_io_handler(
    *,
    agent_name: str,
    repo_name: str,
    repo_id: str,
    pr_number: int,
    head_sha: str,
    workflow_id: str | None,
    model: str,
) -> list[BaseCallbackHandler]:
    """Return the callback list to attach to a review agent's chat model.

    Returns an empty list when :attr:`Settings.llm_log_io_enabled`
    is false, so callers can pass the result unconditionally and
    incur zero overhead when the feature is off.
    """
    if not settings.llm_log_io_enabled:
        return []
    return [
        LLMIOCallbackHandler(
            ctx=Context(
                agent_name=agent_name,
                repo_name=repo_name,
                repo_id=repo_id,
                pr_number=pr_number,
                head_sha=head_sha,
                workflow_id=workflow_id,
                model=model,
            )
        )
    ]


# --------------------------------------------------------------------------- #
# Pure helpers                                                                 #
# --------------------------------------------------------------------------- #


def _message_bytes(message: BaseMessage) -> int:
    """Byte size of one message's content (UTF-8 encoded).

    The content can be a plain string, a list of content parts (a mix
    of strings and dicts in langchain's mixed-content shape), or
    anything else (coerced to ``str``). Returns the encoded byte
    length so the value is meaningful for both ASCII and multi-byte
    text.
    """
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return len(content.encode("utf-8", errors="replace"))
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += len(part.encode("utf-8", errors="replace"))
            else:
                total += len(str(part).encode("utf-8", errors="replace"))
        return total
    return len(str(content).encode("utf-8", errors="replace"))


def _extract_output_metrics(
    response: LLMResult,
) -> tuple[int, int, dict[str, Any] | None]:
    """Pull ``(output_bytes, tool_call_count, usage)`` out of an LLMResult.

    For chat models the first generation is a ``ChatGeneration`` whose
    ``.message`` is the AI message. ``output_bytes`` is the byte size
    of the message content; ``tool_call_count`` is the number of tool
    calls in the message; ``usage`` is the provider's usage metadata
    (``None`` when not surfaced).
    """
    if not response.generations:
        return 0, 0, None
    first_group = response.generations[0]
    if not first_group:
        return 0, 0, None
    first = first_group[0]
    message: BaseMessage | None = getattr(first, "message", None)
    if message is None:
        # Non-chat LLM path: ``Generation`` exposes ``text``.
        text = getattr(first, "text", "")
        if isinstance(text, str):
            return (
                len(text.encode("utf-8", errors="replace")),
                0,
                _usage_from_llm_output(response.llm_output),
            )
        return 0, 0, _usage_from_llm_output(response.llm_output)

    output_bytes = _message_bytes(message)
    raw_tool_calls: Any = getattr(message, "tool_calls", None) or []
    tool_call_count = sum(1 for tc in raw_tool_calls if isinstance(tc, dict))

    usage: dict[str, Any] | None = None
    raw_usage = getattr(message, "usage_metadata", None)
    if raw_usage:
        usage = _coerce_usage(raw_usage)
    if usage is None:
        usage = _usage_from_llm_output(response.llm_output)
    return output_bytes, tool_call_count, usage


def _coerce_usage(raw: Any) -> dict[str, Any] | None:
    """Project a usage-metadata object to a JSON-safe dict.

    Returns ``None`` when the input is empty or not a mapping. Drops
    non-scalar values; we only want the count fields, not arbitrary
    nested structures.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if v is None or isinstance(v, (bool, int, float, str)):
            out[str(k)] = v
    return out or None


def _usage_from_llm_output(llm_output: dict[str, Any] | None) -> dict[str, Any] | None:
    """Best-effort usage extraction from the provider's ``llm_output`` dict.

    The shape is provider-specific (``token_usage`` / ``usage`` /
    ``usage_metadata``). Returns ``None`` when no recognizable token
    counts are present.
    """
    if not llm_output:
        return None
    for key in ("token_usage", "usage", "usage_metadata"):
        if key in llm_output and isinstance(llm_output[key], dict):
            inner = llm_output[key]
            if any(
                k in inner
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            ):
                return _coerce_usage(inner)
    return None


def _tool_name(serialized: dict[str, Any], kwargs: dict[str, Any]) -> str:
    """Extract a tool name from a langchain ``serialized`` payload.

    Tries the conventional keys in order, falling back to ``"unknown"``.
    """
    name = serialized.get("name")
    if isinstance(name, str) and name:
        return name
    ident = serialized.get("id")
    if isinstance(ident, list) and ident:
        last = ident[-1]
        if isinstance(last, str):
            return last
    if isinstance(ident, str) and ident:
        return ident
    kwargs_name = kwargs.get("name")
    if isinstance(kwargs_name, str) and kwargs_name:
        return kwargs_name
    return "unknown"


__all__ = ["LLMIOCallbackHandler", "make_llm_io_handler"]
