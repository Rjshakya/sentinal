"""V3 pi agent harness (``app.services.pi_harness``).

Builds ``pi`` CLI commands and runs them inside a sandbox
(``pi --print``). Isolated from v2: nothing here imports
``app.services.llm`` or ``app.services.agent_v2`` (only the v3
``LLMConfigCtx`` shape for model projection).
"""

from app.services.pi_harness.harness import (
    PiAgentHarness,
    modelFromCtx,
    phaseSessionId,
    validateSessionId,
)
from app.services.pi_harness.types import (
    DEFAULT_TOOLS,
    PiModel,
    PiRunResult,
    ThinkingLevel,
)

__all__ = [
    "DEFAULT_TOOLS",
    "PiAgentHarness",
    "PiModel",
    "PiRunResult",
    "ThinkingLevel",
    "modelFromCtx",
    "phaseSessionId",
    "validateSessionId",
]
