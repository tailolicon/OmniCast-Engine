"""LLM client module for OmniCast Engine."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResponse:
    """Immutable response from LLM call."""
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str
    # Subscription (Claude CLI) calls are not billed per token, so cost_usd stays
    # 0.0 and budgets/ROI stay honest. The notional figure the CLI reports is kept
    # separately for usage-limit awareness — it is a real constraint, just not a
    # marginal cost. Optional: every existing call site predates these.
    notional_cost_usd: float = 0.0
    role: str = ""
    effort: str = ""


from omnicast.llm.client import LLMClient
from omnicast.llm.fallback import DryRunClient
from omnicast.llm.cost import CostCalculator, CostBreakdown, MODEL_PRICING

__all__ = [
    "LLMClient",
    "LLMResponse",
    "DryRunClient",
    "CostCalculator",
    "CostBreakdown",
    "MODEL_PRICING",
]
