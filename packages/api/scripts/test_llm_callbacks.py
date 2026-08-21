"""Smoke test for the LLM I/O callback handler.

Exercises :class:`app.core.llm_callbacks.LLMIOCallbackHandler` with
synthetic langchain events and prints the resulting structured log
lines. The handler is metadata-only by design — no input messages,
no output text, no tool input/output are emitted. Each line carries
the correlation envelope, the per-call index, latency, and usage.

Run from the repo root:  uv run python packages/api/scripts/test_llm_callbacks.py
"""

from __future__ import annotations

import json
import logging
import sys
from io import StringIO
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult


def main() -> int:
    from app.core.config import settings
    from app.core.logging import JsonFormatter
    from app.core.llm_callbacks import make_llm_io_handler

    buf = StringIO()
    json_handler = logging.StreamHandler(buf)
    json_handler.setFormatter(JsonFormatter())
    target = logging.getLogger("app.core.logging")
    target.handlers = [json_handler]
    target.propagate = False
    target.setLevel(logging.INFO)

    # Force the feature on (the env var defaults to false).
    settings.llm_log_io = True

    callbacks = make_llm_io_handler(
        agent_name="security",
        repo_name="foo/bar",
        repo_id="uuid-1",
        pr_number=42,
        head_sha="abc1234",
        workflow_id="review:uuid-1:42:abc1234",
        model="gpt-test",
    )
    assert len(callbacks) == 1
    h = callbacks[0]

    run_id = uuid4()
    h.on_chat_model_start(
        serialized={"name": "ChatOpenAI"},
        messages=[
            [
                SystemMessage(content="You are a security reviewer."),
                HumanMessage(content="Review this diff."),
            ]
        ],
        run_id=run_id,
    )

    tool_run_id = uuid4()
    h.on_tool_start(
        serialized={"name": "get_diff"},
        input_str="",
        run_id=tool_run_id,
        parent_run_id=run_id,
        inputs={},
    )
    h.on_tool_end(
        output="diff content...",
        run_id=tool_run_id,
        parent_run_id=run_id,
    )

    h.on_llm_end(
        response=LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=AIMessage(
                            content="Found 1 issue",
                            tool_calls=[
                                {
                                    "id": "call_1",
                                    "name": "read_file",
                                    "args": {"file_path": "/home/user/tmp/42/abc1234/overview.md"},
                                }
                            ],
                            usage_metadata={
                                "input_tokens": 100,
                                "output_tokens": 50,
                                "total_tokens": 150,
                            },
                        )
                    )
                ]
            ]
        ),
        run_id=run_id,
    )

    run_id_2 = uuid4()
    h.on_chat_model_start(
        serialized={"name": "ChatOpenAI"},
        messages=[[HumanMessage(content="Retry?")]],
        run_id=run_id_2,
    )
    try:
        raise RuntimeError("rate limited")
    except RuntimeError as exc:
        h.on_llm_error(error=exc, run_id=run_id_2)

    # Drive a large input through on_chat_model_start to confirm
    # the byte counting does not blow up the log line.
    big = "x" * (20 * 1024)
    h.on_chat_model_start(
        serialized={"name": "ChatOpenAI"},
        messages=[[HumanMessage(content=big)]],
        run_id=uuid4(),
    )

    print("=== event summary ===")
    for line in buf.getvalue().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        msg = rec.get("message", "<no>")
        data = rec.get("data") or {}
        agent = data.get("agent", "-")
        index = data.get("index", "-")
        tool_name = data.get("tool_name", "-")
        latency = data.get("latency_ms", "-")
        msg_count = data.get("message_count", "-")
        total_bytes = data.get("total_input_bytes", "-")
        output_bytes = data.get("output_bytes", "-")
        tc_count = data.get("tool_call_count", "-")
        # Verify the metadata-only contract: no content fields at all.
        forbidden = {"input", "output", "tool_input", "tool_output"}
        leaked = forbidden & data.keys()
        assert not leaked, f"leaked content fields in {msg}: {leaked}"
        print(
            f"  {msg:24s}  agent={agent:8s}  index={index}  "
            f"tool={tool_name:8s}  latency={latency}  "
            f"msgs={msg_count}  in_bytes={total_bytes}  "
            f"out_bytes={output_bytes}  tool_calls={tc_count}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
