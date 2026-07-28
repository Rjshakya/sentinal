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
  the input messages (truncated), the per-call index, and the
  correlation context. Emitted upfront so a hang or process kill
  leaves a record of the request.
- ``llm_call_completed`` — emitted in ``on_llm_end``. Carries the
  LLM output (text + tool calls), usage metadata, and latency.
- ``llm_call_failed`` — emitted in ``on_llm_error``. Carries the
  error class and message.

Emitted events (per tool invocation, nested under the parent LLM
call):

- ``tool_call_started`` — emitted in ``on_tool_start``. Carries the
  tool name and parsed input.
- ``tool_call_completed`` — emitted in ``on_tool_end``. Carries the
  truncated tool output.

Per-call state (input messages, monotonic index, in-flight tool
invocations) is keyed on the langchain ``run_id`` so a single outer
``ainvoke`` yields N ordered, correlatable log lines.

The handler is **off by default** (gated on
``settings.llm_log_io_enabled``). When off, no handler is attached
and there is zero per-call overhead. The factory
:func:`make_llm_io_handler` returns an empty list in that case.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.core.config import settings
from app.core.logging import structured_log

log = logging.getLogger(__name__)

# Cap on per-field text content (chars). Diffs and code can run to
# megabytes; we want a useful but bounded log line.
_TRUNCATE_LIMIT: int = 8 * 1024


# --------------------------------------------------------------------------- #
# Correlation context                                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Context:
    """Immutable correlation context for one agent invocation.

    One :class:`Context` is built per agent (summary / security /
    correctness / style) and shared across every LLM call and tool
    invocation that agent makes. The fields show up on every emitted
    log line, which is what makes a multi-agent log stream
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
    input_messages: list[list[BaseMessage]]
    tool_invocations: list[dict[str, Any]] = field(default_factory=list)


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
        """Record the LLM call's input and emit ``llm_call_started``."""
        self._counter += 1
        started_at = time.monotonic()
        self._states[run_id] = _CallState(
            index=self._counter,
            started_at=started_at,
            input_messages=messages,
        )

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
                "input": [_serialize_message_group(group) for group in messages],
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
        """Emit ``llm_call_completed`` with output, usage, and latency."""
        state = self._states.pop(run_id, None)
        if state is None:
            # Defensive: an end without a start (e.g. recovered run).
            return

        latency_ms = int((time.monotonic() - state.started_at) * 1000)
        text, tool_calls, usage = _extract_output(response)

        structured_log(
            "INFO",
            "llm_call_completed",
            {
                **self._ctx_base(),
                "index": state.index,
                "langchain_run_id": str(run_id),
                "latency_ms": latency_ms,
                "output": {"text": text, "tool_calls": tool_calls},
                "usage": usage,
                "tool_invocations": state.tool_invocations,
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
        """Record a tool invocation under its parent LLM call and emit ``tool_call_started``."""
        tool_name = _tool_name(serialized, kwargs)
        tool_input: Any = inputs if inputs is not None else input_str
        invocation_index = self._record_tool_invocation(
            parent_run_id=parent_run_id,
            name=tool_name,
            input_obj=tool_input,
        )

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
                "tool_input": _truncate_value(tool_input),
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
        """Emit ``tool_call_completed`` with the (truncated) tool output."""
        structured_log(
            "INFO",
            "tool_call_completed",
            {
                **self._ctx_base(),
                "tool_run_id": str(run_id),
                "tool_parent_run_id": (
                    str(parent_run_id) if parent_run_id is not None else None
                ),
                "tool_output": _truncate_value(output),
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

    def _record_tool_invocation(
        self,
        *,
        parent_run_id: UUID | None,
        name: str,
        input_obj: Any,
    ) -> int:
        """Append a tool invocation record to the parent LLM call's state.

        Tool invocations whose ``parent_run_id`` is not in
        ``self._states`` (e.g. the deepagents runtime invokes some
        tools outside of an LLM turn) are recorded as ``orphan: true``
        so the log stream is still ordered correctly.
        """
        if parent_run_id is not None and parent_run_id in self._states:
            state = self._states[parent_run_id]
            state.tool_invocations.append(
                {
                    "name": name,
                    "input": _truncate_value(input_obj),
                    "orphan": False,
                }
            )
            return len(state.tool_invocations)
        # Orphan tool call (no active LLM parent). Still emit a record.
        return 0


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


def _serialize_message_group(group: list[BaseMessage]) -> list[dict[str, Any]]:
    """Project a list of input messages to a JSON-safe, truncated form."""
    return [_serialize_message(m) for m in group]


def _serialize_message(message: BaseMessage) -> dict[str, Any]:
    """Project one message to ``{role, content, name, tool_call_id, tool_calls}``."""
    role = getattr(message, "type", None) or message.__class__.__name__
    content_obj: Any = getattr(message, "content", "")
    if isinstance(content_obj, str):
        content: Any = _truncate_text(content_obj)
    elif isinstance(content_obj, list):
        content = [_truncate_value(part) for part in content_obj]
    else:
        content = _truncate_text(str(content_obj))
    name = getattr(message, "name", None)
    tool_call_id = getattr(message, "tool_call_id", None)
    tool_calls = getattr(message, "tool_calls", None) or None
    out: dict[str, Any] = {
        "role": str(role),
        "content": content,
    }
    if name is not None:
        out["name"] = str(name)
    if tool_call_id is not None:
        out["tool_call_id"] = str(tool_call_id)
    if tool_calls is not None:
        out["tool_calls"] = [
            {
                "id": str(tc.get("id", "")),
                "name": str(tc.get("name", "")),
                "args": _truncate_value(tc.get("args", {})),
            }
            for tc in tool_calls
        ]
    return out


def _extract_output(
    response: LLMResult,
) -> tuple[Any, list[dict[str, Any]], dict[str, Any] | None]:
    """Pull ``(text, tool_calls, usage)`` out of an :class:`LLMResult`.

    For chat models ``response.generations`` is
    ``list[list[ChatGeneration]]`` and the first element's
    ``.message`` is the :class:`BaseMessage` we want.
    ``usage_metadata`` is provider-dependent; we return ``None``
    rather than an empty dict when the provider didn't surface it.
    """
    if not response.generations:
        return "", [], None
    first_group = response.generations[0]
    if not first_group:
        return "", [], None
    first = first_group[0]
    message: BaseMessage | None = None
    if isinstance(first, ChatGeneration):
        message = first.message
    elif hasattr(first, "text"):
        text = getattr(first, "text", "")
        return _truncate_text(text), [], _usage_from_llm_output(response.llm_output)
    if message is None:
        return "", [], _usage_from_llm_output(response.llm_output)

    text = _format_ai_content(message.content)
    raw_tool_calls: Any = getattr(message, "tool_calls", None) or []
    tool_calls: list[dict[str, Any]] = [
        {
            "id": str(tc.get("id", "")),
            "name": str(tc.get("name", "")),
            "args": _truncate_value(tc.get("args", {})),
        }
        for tc in raw_tool_calls
        if isinstance(tc, dict)
    ]
    usage: dict[str, Any] | None = None
    raw_usage = getattr(message, "usage_metadata", None)
    if raw_usage:
        usage = {str(k): _as_jsonable(v) for k, v in raw_usage.items()}
    if usage is None:
        usage = _usage_from_llm_output(response.llm_output)
    return text, tool_calls, usage


def _format_ai_content(content: Any) -> Any:
    """Format the AIMessage content into a JSON-safe, truncated value."""
    if isinstance(content, str):
        return _truncate_text(content)
    if isinstance(content, list):
        return [_truncate_value(part) for part in content]
    return _truncate_text(str(content))


def _usage_from_llm_output(llm_output: dict[str, Any] | None) -> dict[str, Any] | None:
    """Best-effort usage extraction from the provider's ``llm_output`` dict.

    The shape is provider-specific (token_usage, usage, etc.). We
    only return the dict if it has at least one of the conventional
    token-count keys; otherwise ``None``.
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
                return {str(k): _as_jsonable(v) for k, v in inner.items()}
    return None


def _tool_name(serialized: dict[str, Any], kwargs: dict[str, Any]) -> str:
    """Extract a tool name from a langchain ``serialized`` payload.

    Tries the conventional keys in order, falling back to ``"unknown"``.
    """
    name = serialized.get("name")
    if isinstance(name, str) and name:
        return name
    # Some langchain versions put the tool name under "id".
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


def _truncate_value(value: Any) -> Any:
    """Truncate a free-form value (str / dict / list) to a bounded form."""
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, list):
        return [_truncate_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _truncate_value(v) for k, v in value.items()}
    return _as_jsonable(value)


def _truncate_text(text: str) -> dict[str, Any]:
    """Truncate a string to ``_TRUNCATE_LIMIT`` chars, preserving the original size."""
    encoded = text.encode("utf-8", errors="replace")
    original_bytes = len(encoded)
    if original_bytes <= _TRUNCATE_LIMIT:
        return {
            "text": text,
            "truncated": False,
            "original_bytes": original_bytes,
        }
    truncated = encoded[:_TRUNCATE_LIMIT].decode("utf-8", errors="replace")
    return {
        "text": truncated,
        "truncated": True,
        "original_bytes": original_bytes,
    }


def _as_jsonable(value: Any) -> Any:
    """Coerce a value into something ``json.dumps`` can handle.

    Falls back to ``str(value)`` for anything unknown.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _as_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_jsonable(item) for item in value]
    return str(value)


__all__ = ["LLMIOCallbackHandler", "make_llm_io_handler"]
