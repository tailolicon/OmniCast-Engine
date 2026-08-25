"""Quality and benchmark gates (strategic review §8, §9; P1 in §15).

Two related complaints, one root cause.

§8 says the "95% similar to the benchmark" claim has no measurement behind it,
and lists eleven dimensions it would have to be split into. It also states the
conditions under which the claim may NOT be made: no golden reference, no
per-dimension metric, no blind human comparison, no pass/fail threshold, no
report of what should not be copied.

§9 says quality gates either do not exist or return fixed scores, and that
`video_intel`'s tests mocked the very methods under test — so a green suite
proved nothing about the analyzer.

The root cause both share: a single number stands in for a judgement nobody can
inspect. So this package has exactly two rules.

  1. NO FIXED SCORES. Every dimension is measured against a REFERENCE, and a
     dimension with no reference returns `unknown` — never a default that looks
     like a pass.
  2. NO OVERALL CLAIM WITHOUT ITS PARTS. `benchmark_similarity` refuses to
     produce a headline percentage until the §8 preconditions are met, and says
     which one is missing.

`gates.py`  §9 — the gate list, each with a real check or an honest `unknown`
`benchmark.py` §8 — per-dimension similarity against a golden reference
"""

from omnicast.quality.benchmark import (
    SIMILARITY_DIMENSIONS,
    BenchmarkComparison,
    compare_to_reference,
)
from omnicast.quality.gates import (
    GATE_ORDER,
    GateOutcome,
    QualityReport,
    run_gates,
)

__all__ = [
    "SIMILARITY_DIMENSIONS", "BenchmarkComparison", "compare_to_reference",
    "GATE_ORDER", "GateOutcome", "QualityReport", "run_gates",
]
