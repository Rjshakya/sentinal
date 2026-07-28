from __future__ import annotations

from typing import TypeAlias

from langgraph.graph.state import CompiledStateGraph

DeepAgentGraph: TypeAlias = CompiledStateGraph
"""The compiled langgraph state graph returned by the review agent factories.

The alias is module-level so callers can name the return type of
:func:`app.services.review.agent.build_summary_agent` (and the three
sibling ``build_*_agent`` factories) without pulling langgraph types
into their own signatures."""

__all__ = ["DeepAgentGraph"]
