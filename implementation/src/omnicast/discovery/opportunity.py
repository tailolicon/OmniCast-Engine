"""The three dimensions the niche opportunity model was missing (§3.1, §15).

The brief's formula:

    demand + supply weakness + audience fit + stack-fit + monetization
    + repeatability - production/legal/YMYL risk

The scorer had demand (`trend_momentum`), supply weakness (`gap_score`),
monetization (`rpm_potential`) and, after P0.1 group 3, a stack fit that
actually runs. Audience fit, repeatability and the risk penalty did not exist.

Each one here follows the same three rules the rest of the scorer now obeys:

  1. UNKNOWN IS NEUTRAL, NOT ZERO. A channel with no audience profile scores
     mid-scale with a note, because "we never asked" and "this does not fit"
     are different facts and scoring them alike is what makes an unresearched
     topic look like a bad one — or a good one.
  2. EVERY VERDICT CARRIES ITS REASON. A topic docked for risk says which
     phrase did it. A rejection nobody can inspect is a rejection operators
     learn to ignore.
  3. NO DIMENSION MAY RESTATE ANOTHER. Risk deliberately does NOT re-penalise
     unsupported production requirements: stack fit already returns a hard zero
     for those, and scoring one fact twice is the exact bug that cost the
     previous session its gap_score rewrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from omnicast.models.enums import Niche, TopicSource

AUDIENCE_FIT_MAX = 10.0
AUDIENCE_FIT_NEUTRAL = 5.0
REPEATABILITY_MAX = 10.0
REPEATABILITY_NEUTRAL = 5.0
RISK_PENALTY_MAX = 40.0

# Niches where bad advice damages money, health or legal standing. YMYL is not
# itself a penalty — a finance channel would take the same hit on every topic,
# which is a constant offset and therefore no signal at all. It raises the cost
# of the CLAIM SHAPES below.
YMYL_NICHES = frozenset({Niche.FINANCE, Niche.HEALTH})


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.I) for p in patterns)


# Claim shapes that are risky in a YMYL niche: promises of outcome, guarantees,
# and specific personal advice.
_YMYL_CLAIMS: dict[str, tuple[re.Pattern[str], ...]] = {
    "guaranteed_return": _rx(
        r"\bguaranteed?\b", r"\brisk[- ]free\b", r"\bcan'?t lose\b",
        r"\bdouble your (?:money|savings)\b", r"\b\d+% (?:a|per) (?:month|year) guaranteed\b"),
    "medical_cure": _rx(
        r"\bcures?\b", r"\breverse (?:diabetes|cancer|dementia|ageing|aging)\b",
        r"\bmiracle\b", r"\bbig pharma (?:doesn'?t|don'?t) want\b",
        r"\bstop taking (?:your )?(?:meds|medication)\b"),
    "personal_advice": _rx(
        r"\byou should (?:buy|sell|invest|take)\b", r"\bexactly what to buy\b",
        r"\bmy \d+ stock picks?\b", r"\bdo this instead of (?:your )?(?:doctor|advisor)\b"),
    "urgency": _rx(
        r"\bbefore it'?s too late\b", r"\bact now\b", r"\blast chance\b",
        r"\bcrash is coming\b", r"\bdo this today or\b"),
}

# Risky regardless of niche.
_GENERAL_RISK: dict[str, tuple[re.Pattern[str], ...]] = {
    "legal_exposure": _rx(
        r"\bis a (?:scam|fraud|criminal)\b", r"\bexposed?\b", r"\bleaked\b",
        r"\bsuing\b", r"\blawsuit against\b"),
    "rights_risk": _rx(
        r"\bfull (?:movie|episode|album|song)\b", r"\bfree download\b",
        r"\bcrack(?:ed)?\b", r"\bhow to pirate\b", r"\bwithout paying\b"),
}

# A topic tied to a moment cannot become a library.
_SPIKE_MARKERS = _rx(
    r"\bbreaking\b", r"\btoday\b", r"\bthis (?:week|morning)\b", r"\blive now\b",
    r"\bjust announced\b", r"\breaction to\b", r"\bwhat happened\b",
    r"\b(?:20\d\d) (?:election|super bowl|world cup|olympics)\b",
)
# ...and one that names a repeatable shape can.
_SERIES_MARKERS = _rx(
    r"\bpart \d\b", r"\bepisode \d\b", r"\bvol(?:ume)? \d\b", r"\b#\d+\b",
    r"\bexplained\b", r"\bbasics\b", r"\bguide\b", r"\bevery .* explained\b",
)


@dataclass
class AudienceProfile:
    """What we know about who this channel is for.

    Built from `ChannelProfile.audience`, which several channels already fill
    in and nothing has ever read for scoring."""

    pain_points: tuple[str, ...] = ()
    content_triggers: tuple[str, ...] = ()
    preferred_length_min: float = 0.0
    engagement_drivers: tuple[str, ...] = ()

    @classmethod
    def from_channel(cls, channel) -> "AudienceProfile":
        raw = getattr(channel, "audience", None) or {}
        if not isinstance(raw, dict):
            return cls()

        def _tuple(key: str) -> tuple[str, ...]:
            value = raw.get(key) or []
            if isinstance(value, str):
                value = [value]
            return tuple(str(v).strip().lower() for v in value if str(v).strip())

        try:
            length = float(raw.get("preferred_video_length_min") or 0.0)
        except (TypeError, ValueError):
            length = 0.0
        return cls(
            pain_points=_tuple("pain_points"),
            content_triggers=_tuple("content_triggers"),
            engagement_drivers=_tuple("engagement_drivers"),
            preferred_length_min=length,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.pain_points or self.content_triggers
                    or self.engagement_drivers or self.preferred_length_min)

    @property
    def phrases(self) -> tuple[str, ...]:
        return self.pain_points + self.content_triggers + self.engagement_drivers


@dataclass
class DimensionResult:
    score: float
    notes: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def _phrase_hits(text: str, phrases) -> list[str]:
    """Substantive words of each configured phrase, matched in the text.

    Whole-phrase matching finds almost nothing — nobody titles a video "fear of
    outliving savings". Matching the phrase's content words does find "will your
    savings outlive you", which is the same concern in a title's voice."""
    hits: list[str] = []
    lowered = text.lower()
    for phrase in phrases:
        words = [w for w in re.findall(r"[a-z]{4,}", phrase.lower())]
        if not words:
            continue
        # Prefix match on a crude stem, because titles inflect: the configured
        # pain point "fear of outliving savings" has to be recognised in "will
        # your savings OUTLIVE you". Floor of 4 characters keeps the stem from
        # degenerating into a two-letter prefix that matches everything.
        matched = [w for w in words
                   if re.search(rf"\b{re.escape(w[:max(4, len(w) - 3)])}", lowered)]
        # Require most of the phrase's content words, so "fear of outliving
        # savings" is not matched by the single word "savings" in any finance
        # title ever written.
        if matched and len(matched) >= max(1, round(len(words) * 0.6)):
            hits.append(phrase)
    return hits


def audience_fit(topic, profile: AudienceProfile) -> DimensionResult:
    """0-10: is this topic for THIS channel's audience?

    A topic can have proven demand from somebody else's audience. RPM and trend
    momentum both read that demand and neither one asks whose it is."""
    if not profile.is_configured:
        return DimensionResult(
            AUDIENCE_FIT_NEUTRAL,
            ["audience fit: no audience profile configured (neutral)"])

    text = f"{getattr(topic, 'title', '')} {getattr(topic, 'description', '') or ''}"
    notes: list[str] = []
    score = 0.0

    hits = _phrase_hits(text, profile.phrases)
    if profile.phrases:
        if hits:
            # 3 points for the first hit, 1.5 for each further one: the second
            # pain point corroborates, it does not double the fit.
            score += min(3.0 + 1.5 * (len(hits) - 1), 6.0)
        else:
            notes.append("audience fit: no configured pain point or trigger appears")
    else:
        score += 3.0
        notes.append("audience fit: no pain points configured (half credit)")

    metrics = getattr(topic, "raw_metrics", None) or {}
    duration = metrics.get("duration_minutes")
    try:
        duration = float(duration) if duration is not None else 0.0
    except (TypeError, ValueError):
        duration = 0.0
    if profile.preferred_length_min and duration > 0:
        ratio = duration / profile.preferred_length_min
        if 0.6 <= ratio <= 1.6:
            score += 4.0
        elif 0.4 <= ratio <= 2.5:
            score += 2.0
            notes.append(
                f"audience fit: {duration:.0f}m is outside the "
                f"{profile.preferred_length_min:.0f}m this audience prefers")
        else:
            notes.append(
                f"audience fit: {duration:.0f}m is far from the "
                f"{profile.preferred_length_min:.0f}m this audience prefers")
    else:
        score += 2.0  # unknown runtime or no preference — neutral half

    return DimensionResult(min(score, AUDIENCE_FIT_MAX), notes, hits)


def repeatability(topic, *, pillar_id: str = "", pillars_configured: bool = False
                  ) -> DimensionResult:
    """0-10: can this become a series, or is it one video?

    §11 asks for a channel that compounds. A topic that can only ever be one
    video costs the same to produce as one that opens a twelve-part pillar, and
    nothing in the score could tell them apart."""
    from omnicast.analytics.pillars import UNCLASSIFIED, UNCONFIGURED

    title = getattr(topic, "title", "") or ""
    notes: list[str] = []
    evidence: list[str] = []
    score = 0.0

    # 1. Does it belong to a library we are already building? (0-4)
    if pillars_configured:
        if pillar_id and pillar_id not in (UNCONFIGURED, UNCLASSIFIED):
            score += 4.0
            evidence.append(f"pillar:{pillar_id}")
        else:
            notes.append("repeatability: matches none of this channel's pillars")
    else:
        score += 2.0
        notes.append("repeatability: no content pillars configured (half credit)")

    # 2. Is it tied to a moment? (0-4)
    spike = next((p.pattern for p in _SPIKE_MARKERS if p.search(title)), "")
    source = getattr(topic, "source", None)
    if spike:
        notes.append(f"repeatability: time-bound phrasing ({spike}) — a spike, "
                     "not a library")
    elif source == TopicSource.NEWS_RSS:
        score += 1.0
        notes.append("repeatability: news-sourced topics age out of a library")
    else:
        score += 4.0

    # 3. Does the shape itself repeat? (0-2)
    series = next((p.pattern for p in _SERIES_MARKERS if p.search(title)), "")
    if series:
        score += 2.0
        evidence.append(f"series-shape:{series}")
    else:
        score += 1.0

    return DimensionResult(min(score, REPEATABILITY_MAX), notes, evidence)


def risk_penalty(topic) -> DimensionResult:
    """0-40, SUBTRACTED: production, legal and YMYL exposure.

    Deliberately narrow. The penalty attaches to the shape of the CLAIM, not to
    the niche: penalising "finance" would dock every topic on a finance channel
    by the same amount, which shifts the threshold and discriminates nothing.
    """
    title = getattr(topic, "title", "") or ""
    description = (getattr(topic, "description", "") or "")[:500]
    text = f"{title}\n{description}"
    niche = getattr(topic, "niche", None)

    notes: list[str] = []
    evidence: list[str] = []
    penalty = 0.0

    if niche in YMYL_NICHES:
        for label, patterns in _YMYL_CLAIMS.items():
            match = next((p.search(text) for p in patterns if p.search(text)), None)
            if match:
                penalty += 10.0
                evidence.append(f"ymyl:{label}:{match.group(0)!r}")
                notes.append(
                    f"risk: {label.replace('_', ' ')} in a YMYL niche "
                    f"({match.group(0)!r}) — this is the claim shape that gets "
                    "channels demonetised, not the subject")

    for label, patterns in _GENERAL_RISK.items():
        match = next((p.search(text) for p in patterns if p.search(text)), None)
        if match:
            penalty += 8.0
            evidence.append(f"{label}:{match.group(0)!r}")
            notes.append(f"risk: {label.replace('_', ' ')} ({match.group(0)!r})")

    return DimensionResult(min(penalty, RISK_PENALTY_MAX), notes, evidence)
