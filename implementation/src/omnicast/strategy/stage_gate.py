"""Experiment portfolio and stage gates (strategic review §11.5).

The review's objection, verbatim in spirit: do not spin up many channels and
wait for one to explode. Validate in stages, and decide scale / kill / pivot on
evidence.

    niche -> format -> packaging -> retention -> audience return -> monetization

TWO PROPERTIES DO THE WORK HERE.

1. GATES ARE ORDERED AND EACH ONE NAMES THE DATA IT NEEDS. A channel cannot
   pass "retention" while "packaging" is unproven, because a video nobody
   clicks has no retention to measure. And a gate whose input is absent returns
   `unknown`, never `fail`: "we have not measured this yet" and "this channel
   does not retain viewers" lead to opposite decisions, and a system that
   confuses them kills its own best experiments.

2. THE PORTFOLIO SPLIT IS A DECLARED TARGET, NOT A LAW. The review offers
   70/20/10 and says explicitly that the numbers need validating against the
   operation's own resources and stage. So the target is configuration, the
   default is the review's suggestion, and what this module reports is DRIFT
   from whatever target was set — never a verdict that 70/20/10 is correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

# Ordered. Each entry: gate id -> (question, required inputs).
GATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("niche", "Is there proven demand we can serve?", ("scored_topics", "approved_topics")),
    ("format", "Can we produce it at the quality the niche expects?",
     ("published_videos", "audit_pass_rate")),
    ("packaging", "Do people click it?", ("impressions", "ctr")),
    ("retention", "Do they stay?", ("avd_percent",)),
    ("audience_return", "Do they come back?", ("returning_viewer_rate",)),
    ("monetization", "Does it pay for itself?", ("rpm", "production_cost_usd")),
)

# Defaults from the review, explicitly labelled as a starting point.
DEFAULT_PORTFOLIO = {"proven": 0.70, "adjacent": 0.20, "asymmetric": 0.10}
# How far a lane may drift from target before it is worth reporting. A portfolio
# that never drifts at all is a portfolio nobody is actually running.
PORTFOLIO_TOLERANCE = 0.10


@dataclass
class StageGateResult:
    gate: str
    status: str
    question: str = ""
    reason: str = ""
    missing_inputs: list[str] = field(default_factory=list)
    value: object = None

    def as_dict(self) -> dict:
        return {"gate": self.gate, "status": self.status, "question": self.question,
                "reason": self.reason, "missing_inputs": list(self.missing_inputs),
                "value": self.value}


from omnicast.shared.numbers import num as _num  # noqa: E402
from omnicast.shared.numbers import rate as _rate  # noqa: E402
from omnicast.shared.numbers import ratio as _ratio  # noqa: E402

# Which gate inputs are FRACTIONS. Out-of-range values make the gate `unknown`
# rather than passing: `avd_percent=25` is a percentage in a field documented as
# a fraction, and accepting it recommended scaling a channel whose real
# retention (25%) was below its own 30% bar — while printing "2500%".
RATE_INPUTS = ("audit_pass_rate", "ctr", "avd_percent", "returning_viewer_rate")


def evaluate_gates(evidence: dict, thresholds: dict | None = None
                   ) -> list[StageGateResult]:
    """Walk the gates in order, stopping the moment one is not passed.

    Stopping matters: a channel whose packaging is unproven has no meaningful
    retention number, so evaluating retention anyway would produce a verdict
    about a sample of people who never arrived."""
    evidence = evidence or {}
    limits = {
        "approved_topics_min": 5,
        "published_videos_min": 3,
        "audit_pass_rate_min": 0.8,
        "impressions_min": 1000,
        "ctr_min": 0.03,
        "avd_percent_min": 0.30,
        "returning_viewer_rate_min": 0.15,
        "margin_min": 0.0,
        **(thresholds or {}),
    }

    results: list[StageGateResult] = []
    for gate, question, inputs in GATES:
        missing = [name for name in inputs
                   if (_rate(evidence.get(name)) if name in RATE_INPUTS
                       else _num(evidence.get(name))) is None]
        if missing:
            results.append(StageGateResult(
                gate=gate, status=UNKNOWN, question=question,
                missing_inputs=missing,
                reason=(f"not measured yet: {', '.join(missing)}. Unknown is not "
                        "failure — killing an experiment for a number nobody has "
                        "collected is how a system kills its own best bets")))
            break

        status, reason, value = _judge(gate, evidence, limits)
        results.append(StageGateResult(gate=gate, status=status, question=question,
                                       reason=reason, value=value))
        if status != PASS:
            break
    return results


def _judge(gate: str, evidence: dict, limits: dict) -> tuple[str, str, object]:
    if gate == "niche":
        approved = _num(evidence.get("approved_topics")) or 0.0
        ok = approved >= limits["approved_topics_min"]
        return (PASS if ok else FAIL,
                f"{approved:.0f} approved topics vs {limits['approved_topics_min']} needed",
                approved)
    if gate == "format":
        published = _num(evidence.get("published_videos")) or 0.0
        rate = _rate(evidence.get("audit_pass_rate")) or 0.0
        ok = (published >= limits["published_videos_min"]
              and rate >= limits["audit_pass_rate_min"])
        return (PASS if ok else FAIL,
                f"{published:.0f} published, audit pass rate {rate:.0%} "
                f"(need {limits['published_videos_min']} and "
                f"{limits['audit_pass_rate_min']:.0%})",
                {"published_videos": published, "audit_pass_rate": rate})
    if gate == "packaging":
        impressions = _num(evidence.get("impressions")) or 0.0
        ctr = _rate(evidence.get("ctr")) or 0.0
        if impressions < limits["impressions_min"]:
            return (UNKNOWN,
                    f"{impressions:.0f} impressions is below the "
                    f"{limits['impressions_min']:.0f} needed for a CTR to mean "
                    "anything — this is sample size, not a packaging verdict",
                    {"impressions": impressions, "ctr": ctr})
        return (PASS if ctr >= limits["ctr_min"] else FAIL,
                f"CTR {ctr:.1%} vs {limits['ctr_min']:.1%} needed over "
                f"{impressions:.0f} impressions",
                {"impressions": impressions, "ctr": ctr})
    if gate == "retention":
        avd = _rate(evidence.get("avd_percent")) or 0.0
        return (PASS if avd >= limits["avd_percent_min"] else FAIL,
                f"average view duration {avd:.0%} vs {limits['avd_percent_min']:.0%}",
                avd)
    if gate == "audience_return":
        rate = _rate(evidence.get("returning_viewer_rate")) or 0.0
        return (PASS if rate >= limits["returning_viewer_rate_min"] else FAIL,
                f"returning viewers {rate:.0%} vs "
                f"{limits['returning_viewer_rate_min']:.0%}",
                rate)
    if gate == "monetization":
        rpm = _num(evidence.get("rpm")) or 0.0
        views = _num(evidence.get("views")) or 0.0
        cost = _num(evidence.get("production_cost_usd"))
        if cost is None or cost < 0 or rpm < 0 or views < 0:
            return (UNKNOWN,
                    "rpm, views and cost must all be present and non-negative — "
                    "a negative cost turns a loss into a margin", None)
        # Guarded: both inputs can be finite while the product overflows, which
        # produced `margin $inf` and non-JSON output from the API.
        revenue = _ratio(rpm * views if rpm * views == rpm * views else None, 1000.0)
        if revenue is None:
            return (UNKNOWN, "revenue overflowed — rpm x views is not a number",
                    None)
        margin = revenue - cost
        return (PASS if margin > limits["margin_min"] else FAIL,
                f"estimated revenue ${revenue:.2f} vs cost ${cost:.2f} "
                f"(margin ${margin:.2f}). Revenue is ESTIMATED from RPM, not read "
                "from a payout report",
                {"estimated_revenue_usd": round(revenue, 2),
                 "production_cost_usd": round(cost, 2),
                 "margin_usd": round(margin, 2)})
    return (UNKNOWN, f"no rule for gate {gate!r}", None)


def decide(results: list[StageGateResult]) -> dict:
    """scale | kill | pivot | keep_measuring, with the gate that decided it."""
    if not results:
        return {"decision": "keep_measuring", "at_gate": "", "reason": "no gates run"}
    last = results[-1]
    # Identity, not arity. `len(results) == len(GATES)` alone let six copies of
    # one gate — or six gates that do not exist — recommend scaling.
    expected = [name for name, _q, _inputs in GATES]
    if (all(r.status == PASS for r in results)
            and [r.gate for r in results] == expected):
        return {"decision": "scale", "at_gate": last.gate,
                "reason": "every stage gate passed, in order"}
    if last.status == UNKNOWN:
        return {"decision": "keep_measuring", "at_gate": last.gate,
                "reason": last.reason}
    # A failure at packaging is a pivot (change the packaging); a failure at the
    # niche gate is a kill (there is nothing to package).
    pivotable = {"format", "packaging", "retention"}
    return {"decision": "pivot" if last.gate in pivotable else "kill",
            "at_gate": last.gate, "reason": last.reason}


# ── portfolio ────────────────────────────────────────────────────────────────

@dataclass
class ExperimentPortfolio:
    target: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PORTFOLIO))
    actual: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def drift(self) -> dict[str, float]:
        drifts: dict[str, float] = {}
        for lane, target in sorted(self.target.items()):
            share = _num(target)
            if share is None:
                continue
            drifts[lane] = round(self.actual.get(lane, 0.0) - share, 3)
        return drifts

    @property
    def out_of_band(self) -> list[str]:
        return [lane for lane, delta in self.drift.items()
                if abs(delta) > PORTFOLIO_TOLERANCE]

    def as_dict(self) -> dict:
        return {
            "target": dict(self.target), "actual": dict(self.actual),
            "counts": dict(self.counts), "drift": self.drift,
            "out_of_band": self.out_of_band,
            "tolerance": PORTFOLIO_TOLERANCE,
            "target_note": (
                "The 70/20/10 split is the review's SUGGESTION and it says so: "
                "the real numbers depend on the operation's resources and stage. "
                "This reports drift from the configured target; it does not "
                "claim the target is correct."
            ),
            "notes": list(self.notes),
        }


def portfolio_drift(lanes: list[str], target: dict[str, float] | None = None
                    ) -> ExperimentPortfolio:
    """Measure how the actual slate splits across proven/adjacent/asymmetric."""
    raw_target = target if isinstance(target, dict) else None
    clean_target: dict[str, float] = {}
    for name, value in (raw_target or DEFAULT_PORTFOLIO).items():
        share = _num(value)
        # An unusable share becomes 0, not a dropped lane: dropping it removed
        # the lane from `drift` and `out_of_band` entirely, so a 100%-proven
        # slate stopped reporting `proven` as skewed.
        clean_target[str(name)] = share if share is not None else 0.0
    portfolio = ExperimentPortfolio(target=clean_target or dict(DEFAULT_PORTFOLIO))

    if raw_target and len(clean_target) < len(raw_target):
        portfolio.notes.append(
            "one or more target shares were not numbers and were ignored")
    total_target = sum(portfolio.target.values())
    if abs(total_target - 1.0) > 0.01:
        portfolio.notes.append(
            f"target shares sum to {total_target:.2f}, not 1.00 — drift against "
            "a target that is not a whole is not interpretable")

    # A bare string is not a slate of lanes: iterating it counted six
    # single-letter lanes.
    if isinstance(lanes, (str, bytes)) or lanes is None:
        portfolio.notes.append("lanes must be a list — nothing was measured")
        return portfolio
    try:
        lanes = list(lanes)
    except TypeError:
        portfolio.notes.append("lanes is not iterable — nothing was measured")
        return portfolio

    total = len(lanes)
    if not total:
        portfolio.notes.append("nothing in the slate — no split to measure")
        return portfolio

    for lane in lanes:
        key = (lane if isinstance(lane, str) else "").strip().lower() or "unassigned"
        portfolio.counts[key] = portfolio.counts.get(key, 0) + 1
    portfolio.actual = {k: round(v / total, 3)
                        for k, v in sorted(portfolio.counts.items())}

    unassigned = portfolio.counts.get("unassigned", 0)
    if unassigned:
        portfolio.notes.append(
            f"{unassigned} item(s) declare no lane — an unassigned experiment is "
            "spending the proven lane's budget without saying so")
    for lane in portfolio.out_of_band:
        delta = portfolio.drift[lane]
        portfolio.notes.append(
            f"lane '{lane}' is {delta:+.0%} from its {portfolio.target[lane]:.0%} "
            "target")
    return portfolio
