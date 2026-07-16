"""Sentinel review agent.

The agent itself lives in :mod:`app.services.agent.review`. The
submodules split concerns so the agent module stays a thin
orchestrator:

- :mod:`app.services.agent.models`   — Pydantic response schemas.
- :mod:`app.services.agent.prompts` — system prompts (orchestrator
  + 3 subagents).
- :mod:`app.services.agent.review`  — factory + entry points.
"""
