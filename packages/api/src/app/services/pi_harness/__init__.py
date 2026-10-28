"""V3 pi agent harness (``app.services.pi_harness``).

Builds ``pi`` CLI commands and runs them inside a sandbox
(``pi --print``). Isolated from v2: nothing here imports
``app.services.llm`` or ``app.services.agent_v2`` (only the v3
``LLMConfigCtx`` shape for model projection).
"""

from app.services.pi_harness.cost import (
    addTotalCosts,
    findCostsOfSession,
    getPiSessionCost,
)
from app.services.pi_harness.errors import PiCostError
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
    PiSessionCost,
    ThinkingLevel,
)

__all__ = [
    "DEFAULT_TOOLS",
    "PiAgentHarness",
    "PiCostError",
    "PiModel",
    "PiRunResult",
    "PiSessionCost",
    "ThinkingLevel",
    "addTotalCosts",
    "findCostsOfSession",
    "getPiSessionCost",
    "modelFromCtx",
    "phaseSessionId",
    "validateSessionId",
]
