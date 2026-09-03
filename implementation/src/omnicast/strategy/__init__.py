"""Long-term channel strategy (strategic review §11).

OmniCast behaves as `find topic -> make video -> upload -> count views`. An
experienced channel operator does something else: they know who the channel is
for, which formats it owns, which experiments are allowed to fail, and which
numbers mean the library is compounding rather than merely growing.

Three modules, matching the review's own division:

  thesis      §11.1 channel thesis + §11.2 content architecture
  stage_gate  §11.5 experiment portfolio and the gates before scale/kill/pivot
  metrics     §11.3 shorts->long funnel, §11.4 audience journey, §11.6 the
              long-term metrics that are not views

The rule shared by all three: THIS LAYER DECLARES, IT DOES NOT INVENT. A thesis
nobody wrote is missing, not generated; a metric we cannot compute is missing
with the reason, not estimated. A strategy layer that fills its own gaps is a
strategy layer that always agrees with itself.
"""

from omnicast.strategy.metrics import (
    JOURNEY_STAGES,
    LongTermMetrics,
    classify_journey_stage,
    measure_long_term,
    shorts_to_long_funnel,
)
from omnicast.strategy.stage_gate import (
    GATES,
    ExperimentPortfolio,
    StageGateResult,
    evaluate_gates,
    portfolio_drift,
)
from omnicast.strategy.thesis import (
    ChannelThesis,
    ContentArchitecture,
    PillarRole,
    load_thesis,
    review_architecture,
)

__all__ = [
    "ChannelThesis", "ContentArchitecture", "PillarRole", "load_thesis",
    "review_architecture", "GATES", "ExperimentPortfolio", "StageGateResult",
    "evaluate_gates", "portfolio_drift", "JOURNEY_STAGES", "LongTermMetrics",
    "classify_journey_stage", "measure_long_term", "shorts_to_long_funnel",
]
