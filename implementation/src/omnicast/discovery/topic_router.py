"""Which component decides what gets made — one answer, in one place.

THE DECISION

Two components ranked topics, on two different code paths, and they disagreed
about whether the other one mattered:

  * `DiscoveryOrchestrator` → `TopicScorer` → `BriefGenerator`, which briefs
    only `action == "approve"`. Here the scorer's lanes are binding.
  * The main API discovery path → `ChannelArchitectAgent.analyze(all_raw, ...)`.
    Here every raw topic reached the LLM and the scorer's verdict was computed,
    logged and thrown away.

That is not two policies. It is one policy applied on one path and skipped on
the other — so the lanes the calibration work measures were, on the busier
path, deciding nothing.

Resolved as: **TopicScorer admits, ChannelArchitect ranks.**

The split follows what each component can actually know. The scorer is
deterministic, cheap, auditable, and holds the facts that do not need judgement
— is the space saturated, can we physically produce this, does the market pay,
have we made it already. The Architect is an LLM and holds the one thing the
scorer cannot compute: whether a topic fits THIS channel's audience and pain
point. Using the LLM to re-derive saturation and RPM from raw metrics is both
more expensive and less reliable than the arithmetic already done.

So the discard lane becomes binding on both paths, and the Architect ranks the
survivors. Two safeguards, because admission is a real gate:

  * the lane comes from the DECIDING scoring generation (v1 while shadow mode
    is on), never from the uncalibrated one;
  * if gating would leave the Architect nothing to rank, the run falls back to
    the ungated list and says so loudly. An empty content calendar is a worse
    failure than a permissive one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

ROUTER_SCORER_GATE = "scorer_gate"
ROUTER_ARCHITECT_ONLY = "architect_only"


def configured_router() -> str:
    """Active router policy; falls back to the gated default without settings."""
    try:
        from omnicast.config.settings import get_settings

        return get_settings().omnicast_topic_router
    except Exception:
        return ROUTER_SCORER_GATE


@dataclass
class Admission:
    """What the scorer let through, and what it held back."""

    admitted: list = field(default_factory=list)   # TopicRawData for the ranker
    rejected_titles: list[str] = field(default_factory=list)
    policy: str = ROUTER_SCORER_GATE
    fell_back: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_titles)

    def as_dict(self) -> dict:
        return {
            "policy": self.policy,
            "admitted": len(self.admitted),
            "rejected": self.rejected_count,
            "fell_back": self.fell_back,
            "notes": list(self.notes),
        }


def admit(scored, all_raw, *, policy: str | None = None) -> Admission:
    """Decide which raw topics reach the ranker.

    `scored` are `ScoredTopic`s from `TopicScorer`; `all_raw` is the ungated
    list the Architect used to receive. Pure — no settings read unless `policy`
    is omitted, no network, no LLM."""
    policy = policy or configured_router()
    result = Admission(policy=policy)

    if policy == ROUTER_ARCHITECT_ONLY:
        result.admitted = list(all_raw)
        result.notes.append(
            "architect_only: every raw topic reaches the ranker and the scorer's "
            "verdict is ignored on this path")
        return result

    keep = []
    for item in scored:
        # `action` reads `total_score`, which is always the DECIDING
        # generation's — never the uncalibrated one.
        if getattr(item, "action", "discard") == "discard":
            result.rejected_titles.append(getattr(item.raw, "title", ""))
        else:
            keep.append(item.raw)

    if not keep and scored:
        # Only a GATE that emptied the list is a fallback case. A scan that
        # found nothing is not the gate being strict, and reporting it as a
        # fallback would blame the threshold for an empty upstream.
        result.admitted = list(all_raw)
        result.fell_back = True
        result.rejected_titles = []
        result.notes.append(
            f"scorer discarded all {len(scored)} topics — falling back to the "
            "ungated list so the run still produces something; check the "
            "scoring thresholds")
        logger.warning("topic gate admitted nothing; falling back",
                       scored=len(scored))
        return result

    result.admitted = keep
    if result.rejected_titles:
        result.notes.append(
            f"scorer_gate: {len(result.rejected_titles)} topic(s) below the "
            "discard threshold never reached the ranker")
    logger.info("topic gate applied", policy=policy, admitted=len(keep),
                rejected=len(result.rejected_titles))
    return result
