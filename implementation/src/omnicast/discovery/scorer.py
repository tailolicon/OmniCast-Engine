"""Topic scoring engine.

Scores raw topics 0-100 across 5 dimensions:
- Trend Momentum: 0-30 (is anyone asking for this? — growth/outlier signal)
- Gap Score:      0-25 (is the space already served? — saturation signal)
- RPM Potential:  0-20 (market RPM floor)
- Novelty vs KB:  0-10 (ChromaDB similarity check, decay-aware)
- Stack Fit:      0-15 (can WE actually make this well?)

WHY THE DIMENSIONS MOVED (strategic review §4, P0 item 4)

`outlier_ratio` used to drive BOTH trend_momentum (`min(ratio*3, 30)`) and
gap_score (tiered 20/28/35). One measurement was therefore counted twice, and a
single YouTube outlier could contribute 65 of the 100 available points on its
own — enough to clear the 70 auto-approve line with nothing else agreeing. Worse,
the two dimensions are supposed to answer OPPOSITE questions:

    trend momentum → "is there demand?"     (high ratio = yes)
    gap score      → "is it already served?" (high ratio says nothing about this;
                                              if anything a monster outlier means
                                              a big channel just covered it)

So gap_score no longer reads outlier_ratio at all. It reads saturation signals:
how big the incumbent is, how many competitor videos already cover the topic,
and whether the audience engaged harder than that channel's norm (unmet demand).
Absent data stays NEUTRAL — "we don't know how crowded this is" must not score
the same as "we checked and it's empty".

The 15 points freed from gap became STACK FIT. Demand for something we cannot
produce well is not opportunity: a topic needing live footage, a face on camera,
or a runtime our pipeline does not do is a topic we will ship badly. Nothing in
the old score could say so.

Thresholds (recalibrated — the old ones assumed the double-count):
  >= 70: auto_approved
  50-69: needs_review (Telegram alert)
  < 50:  discard
A YouTube outlier now needs at least two dimensions agreeing to auto-approve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

from omnicast.discovery.models import ScoredTopic, TopicRawData
from omnicast.models.enums import Market, Niche, TopicSource

logger = structlog.get_logger()

# RPM floor by market (USD)
MARKET_RPM: dict[Market, float] = {
    Market.US: 15.0,
    Market.UK: 12.0,
    Market.AU: 10.0,
    Market.CA: 10.0,
    Market.JP: 8.0,
    Market.KR: 7.0,
}

GAP_MAX = 25.0
STACK_FIT_MAX = 15.0
# Neutral = "unknown", deliberately mid-scale. Used when no stack profile is
# configured, so an unconfigured system neither rewards nor punishes fit.
STACK_FIT_NEUTRAL = 7.5
# Baseline for a YouTube outlier before saturation evidence moves it.
YOUTUBE_GAP_BASE = 12.0

# Saturation-only gap defaults per source (0-25). Ordering preserved from the
# original 0-40 scale: podcast > reddit > trends > news.
SOURCE_GAP: dict[TopicSource, float] = {
    TopicSource.GOOGLE_TRENDS: 15.0,
    TopicSource.REDDIT: 19.0,
    TopicSource.PODCAST: 22.0,
    TopicSource.NEWS_RSS: 12.0,
}


# v1 gap constants, kept verbatim so shadow mode compares against what actually
# shipped rather than against a reconstruction of it.
V1_SOURCE_GAP: dict[TopicSource, float] = {
    TopicSource.GOOGLE_TRENDS: 25.0,
    TopicSource.REDDIT: 30.0,
    TopicSource.PODCAST: 35.0,
    TopicSource.NEWS_RSS: 20.0,
}


SCORING_MODES = ("v1", "shadow", "v2")

# Which composition of v2 is running. Bumped when the DIMENSIONS of v2 change,
# not when their implementation is tuned.
#
# Revision 2 (brief §3.1/§15) completes the opportunity formula:
#   demand + supply weakness + audience fit + stack-fit + monetization
#   + repeatability - production/legal/YMYL risk
#
# This matters operationally: shadow rows written under revision 1 describe a
# different function, and averaging the two corpora would calibrate a scorer
# that never existed. `scoring_calibration` refuses a mixed corpus for exactly
# this reason. v2 is still not deciding anything — see SHADOW_MODE_NOTE.
SCORING_V2_REVISION = 2

# v2 revision 2 rebalance. The four original dimensions keep their native scales
# (so `ScoredTopic` field bounds and every existing test still hold) and are
# rescaled into the new budget here, where the arithmetic is visible:
#
#   trend 30 -> 25 | gap 25 -> 20 | rpm 20 -> 15 | novelty 10 -> 8
#   stack 15 -> 12 | + audience 10 | + repeatability 10   = 100
#   risk: 0 to -40, subtracted after, clamped at 0.
V2_WEIGHTS = {
    "trend": 25.0 / 30.0,
    "gap": 20.0 / 25.0,
    "rpm": 15.0 / 20.0,
    "novelty": 8.0 / 10.0,
    "stack": 12.0 / 15.0,
}


def _num(value) -> float | None:
    """Coerce a raw metric to a float, or None when it is not a number.

    Scanner metrics arrive from JSON, JSONL round-trips and third-party APIs,
    so `None`, `""`, `"n/a"` and NaN all turn up. Both previous behaviours were
    wrong in the same direction: truthiness silently mis-scored them, and the
    `is not None` fix turned them into a `ValueError` out of `score_batch` —
    i.e. one malformed field aborting the whole discovery run. Unparseable is
    UNKNOWN, and unknown is neutral."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None  # NaN/inf are not measurements
    return result


def _band_label(high: float) -> str:
    return "∞" if high == float("inf") else f"{high:.0f}"


def _as_set(value) -> set[str]:
    """Normalise a collection-shaped metric to a set of lowercase strings.

    A scalar `"face_cam"` where a list was expected used to iterate CHARACTERS,
    so the hard production veto silently stopped vetoing. `_num` hardened the
    scalar metrics; the collection-shaped ones assumed their shape."""
    if value is None:
        return set()
    if isinstance(value, (str, bytes)):
        text = value.decode() if isinstance(value, bytes) else value
        return {text.strip().lower()} if text.strip() else set()
    try:
        return {str(v).strip().lower() for v in value if str(v).strip()}
    except TypeError:
        return {str(value).strip().lower()}


def _boundary_pattern(word: str) -> str:
    """Whole-word match that still works for keywords like "c++" or ".net"."""
    escaped = re.escape(word.lower())
    prefix = r"\b" if word[:1].isalnum() or word[:1] == "_" else ""
    suffix = r"\b" if word[-1:].isalnum() or word[-1:] == "_" else r"(?!\w)"
    return f"{prefix}{escaped}{suffix}"


def _clamp(value: float, high: float, low: float = 0.0) -> float:
    """Bound a dimension to its budget.

    `min(x, high)` alone let a below-median podcast (listen_score 20) or a
    downvoted Reddit post produce a NEGATIVE momentum. `ScoredTopic` declares
    ge=0, so pydantic raised and one bad topic aborted the whole discovery run
    in `score_batch`. A weak signal must score zero, not explode."""
    return float(max(low, min(value, high)))


def _configured_scoring_mode() -> str:
    """Read the active generation from settings; fall back to the safe one.

    Import is local and defensive on purpose: the scorer is a pure-ish unit and
    must stay constructible in tests and scripts that have no .env."""
    try:
        from omnicast.config.settings import get_settings

        return get_settings().omnicast_scoring_mode
    except Exception:
        return "shadow"


@dataclass
class StackProfile:
    """What this operation can actually produce well.

    Every field is optional; an empty profile scores neutral rather than
    guessing. Populate it from the channel config to make stack fit real."""

    niches: set[Niche] = field(default_factory=set)
    markets: set[Market] = field(default_factory=set)
    # Runtime our pipeline is tuned for, in minutes.
    duration_minutes: tuple[float, float] = (0.0, 0.0)
    # Title/format shapes we have shipped successfully (see youtube_scanner's
    # _classify_title tags: "number", "question", "listicle", "how_to", ...).
    proven_title_patterns: set[str] = field(default_factory=set)
    # Production requirements we cannot meet (e.g. "face_cam", "live_footage",
    # "interview"). Matched against raw_metrics["production_requirements"].
    unsupported_requirements: set[str] = field(default_factory=set)
    # Topics we will not make regardless of demand.
    blocked_keywords: set[str] = field(default_factory=set)

    @property
    def is_configured(self) -> bool:
        return bool(
            self.niches or self.markets or any(self.duration_minutes)
            or self.proven_title_patterns or self.unsupported_requirements
            or self.blocked_keywords
        )


class TopicScorer:
    """Score raw topics using 4 dimensions.

    kb_client is optional. If None, novelty_score defaults to 5 (neutral).
    """

    def __init__(self, kb_client=None, stack_profile: StackProfile | None = None,
                 scoring_mode: str | None = None, audience_profile=None,
                 pillars=None) -> None:
        """
        kb_client: KBClient instance for novelty check.
        If None, skip novelty check (novelty_score = 5).
        stack_profile: what this operation can produce. If None, stack fit is
        neutral — an unconfigured system must not silently penalise everything.
        scoring_mode: "v1" | "shadow" | "v2". None reads
        settings.omnicast_scoring_mode, which defaults to "shadow" — v2 is
        recorded on every topic but v1 keeps deciding until the new boundary is
        calibrated. See SHADOW_MODE_NOTE below.
        """
        from omnicast.discovery.opportunity import AudienceProfile

        self._kb = kb_client
        self._stack = stack_profile or StackProfile()
        # Both default to "not configured", which each dimension scores as
        # NEUTRAL with a note — never as zero.
        self._audience = audience_profile or AudienceProfile()
        self._pillars = list(pillars or [])
        mode = scoring_mode or _configured_scoring_mode()
        if mode not in SCORING_MODES:
            # Fail towards containment, loudly. An unrecognised mode used to fall
            # through the else branch and activate v2 — the one generation that
            # is not allowed to decide yet.
            raise ValueError(
                f"scoring_mode must be one of {SCORING_MODES}, got {mode!r}")
        self._mode = mode

    async def score(self, topic: TopicRawData) -> ScoredTopic:
        """Score a topic under BOTH generations; the active one decides."""
        trend = self._calc_trend_momentum(topic)
        rpm = self._calc_rpm_potential(topic.market)
        novelty = await self._calc_novelty(topic)

        gap_v2 = self._calc_gap_score(topic)
        stack_fit, notes = self._calc_stack_fit(topic)
        fit, repeat, risk = self._calc_opportunity(topic)
        notes = list(notes) + fit.notes + repeat.notes + risk.notes

        weights = V2_WEIGHTS
        total_v2 = _clamp(
            trend * weights["trend"] + gap_v2 * weights["gap"]
            + rpm * weights["rpm"] + novelty * weights["novelty"]
            + stack_fit * weights["stack"] + fit.score + repeat.score
            - risk.score,
            100,
        )

        gap_v1 = self._calc_gap_score_v1(topic)
        total_v1 = min(trend + gap_v1 + rpm + novelty, 100)

        v1_decides = self._mode in {"v1", "shadow"}
        deciding = total_v1 if v1_decides else total_v2
        version = "v1" if v1_decides else "v2"

        if self._mode == "shadow":
            notes = list(notes)
            notes.append(
                f"shadow: v2={total_v2:.1f} vs v1={total_v1:.1f} "
                f"(delta {total_v2 - total_v1:+.1f}); v1 is deciding"
            )

        return ScoredTopic(
            raw=topic,
            trend_momentum=trend,
            gap_score=gap_v2,
            rpm_potential=rpm,
            novelty_score=novelty,
            stack_fit=stack_fit,
            # `total_score` stays the number the rest of the system already
            # reads, and it always matches the flags below.
            total_score=deciding,
            auto_approved=deciding >= 70,
            needs_review=50 <= deciding < 70,
            score_notes=notes,
            scoring_version=version,
            total_score_v1=total_v1,
            total_score_v2=total_v2,
            gap_score_v1=gap_v1,
            audience_fit=fit.score,
            repeatability=repeat.score,
            risk_penalty=risk.score,
            scoring_v2_revision=SCORING_V2_REVISION,
        )

    def _calc_opportunity(self, topic: TopicRawData):
        """Audience fit, repeatability and risk — the missing half of §3.1.

        Kept in `discovery.opportunity` so each is a pure function of the topic
        plus declared configuration, testable without constructing a scorer."""
        from omnicast.analytics.pillars import classify_pillar
        from omnicast.discovery.opportunity import (
            audience_fit,
            repeatability,
            risk_penalty,
        )

        pillar_id = ""
        if self._pillars:
            pillar_id = classify_pillar(
                topic.title, topic.description or "", self._pillars).pillar_id

        return (
            audience_fit(topic, self._audience),
            repeatability(topic, pillar_id=pillar_id,
                          pillars_configured=bool(self._pillars)),
            risk_penalty(topic),
        )

    async def score_batch(self, topics: list[TopicRawData]) -> list[ScoredTopic]:
        """Score multiple topics. Return sorted by total_score descending."""
        scored = [await self.score(t) for t in topics]
        return sorted(scored, key=lambda s: s.total_score, reverse=True)

    @staticmethod
    def _calc_trend_momentum(topic: TopicRawData) -> float:
        """Calculate trend momentum (0-30).

        Heuristics by source:
        - YOUTUBE_COMPETITOR: outlier_ratio → min(ratio * 3, 30)
        - GOOGLE_TRENDS: growth_pct → min(growth_pct / 10, 30)
        - REDDIT: (score / 100) → min(score_norm, 30)
        - PODCAST: listen_score → min((listen_score - 50) * 0.6, 30)
        - NEWS_RSS: mention_count → min(mention_count * 2, 30)
        """
        metrics = topic.raw_metrics or {}
        source = topic.source

        if source == TopicSource.YOUTUBE_COMPETITOR:
            # This branch was the one `_clamp` missed. A negative outlier_ratio
            # produced a negative momentum, which trips ScoredTopic's ge=0 and
            # aborts score_batch for every other topic in the run.
            ratio = _num(metrics.get("outlier_ratio"))
            return _clamp((ratio or 0.0) * 3, 30)
        elif source == TopicSource.GOOGLE_TRENDS:
            growth = _num(metrics.get("growth_pct")) or 0.0
            return _clamp(growth / 10, 30)
        elif source == TopicSource.REDDIT:
            score = _num(metrics.get("score")) or 0.0
            return _clamp(score / 100, 30)
        elif source == TopicSource.PODCAST:
            listen = _num(metrics.get("listen_score"))
            listen = 50.0 if listen is None else listen
            return _clamp((listen - 50) * 0.6, 30)
        elif source == TopicSource.NEWS_RSS:
            mentions = _num(metrics.get("mention_count")) or 0.0
            return _clamp(mentions * 2, 30)
        else:
            return 0.0

    @staticmethod
    def _calc_gap_score_v1(topic: TopicRawData) -> float:
        """The ORIGINAL gap score (0-40), preserved for shadow comparison.

        This is the double-counting version: it re-reads `outlier_ratio`, which
        `_calc_trend_momentum` has already scored in full. It is kept — and only
        kept — so shadow mode can measure the real delta against the behaviour
        that shipped. Do not call it from new code."""
        source = topic.source
        metrics = topic.raw_metrics or {}
        if source == TopicSource.YOUTUBE_COMPETITOR:
            ratio = _num(metrics.get("outlier_ratio")) or 0.0
            if ratio >= 8:
                return 35.0
            elif ratio >= 4:
                return 28.0
            return 20.0
        return V1_SOURCE_GAP.get(source, 10.0)

    @staticmethod
    def _calc_gap_score(topic: TopicRawData) -> float:
        """Calculate gap score (0-25) — SATURATION only.

        Deliberately blind to `outlier_ratio`: that is demand, it is already
        scored in full by trend_momentum, and reading it twice let one
        measurement supply 65 of 100 points.

        For a YouTube outlier the space looks EMPTIER when:
        - the incumbent is small (a 20k-median channel breaking out means the
          big players have not taken this yet);
        - few other competitor videos already cover the topic
          (`similar_competitor_videos`);
        - the audience engaged harder than that channel's norm — people wanted
          more than the channel usually gives them.
        And FULLER when a million-view-median channel already owns it, or the
        topic is visibly covered across the competitor set.

        Missing signals contribute NOTHING in either direction. "Unknown" is not
        "empty" — that conflation is what makes an unresearched topic look like
        a discovery.
        """
        source = topic.source
        metrics = topic.raw_metrics or {}

        if source != TopicSource.YOUTUBE_COMPETITOR:
            return SOURCE_GAP.get(source, 6.0)

        score = YOUTUBE_GAP_BASE

        # 1. Incumbent scale.
        median = _num(metrics.get("channel_median_views"))
        if median is not None:
            # A parsed number, not truthiness: a channel whose median really is
            # 0 is a measured fact, and treating it as "we never checked" is the
            # same conflation this docstring forbids two paragraphs up. An
            # unparseable value stays unknown rather than raising.
            if median < 50_000:
                score += 8
            elif median < 250_000:
                score += 4
            elif median >= 1_000_000:
                score -= 4

        # 2. How many competitor videos already cover this topic.
        covered = _num(metrics.get("similar_competitor_videos"))
        if covered is not None:
            covered = int(covered)
            if covered == 0:
                score += 6
            elif covered <= 2:
                score += 2
            elif covered >= 5:
                score -= 8

        # 3. Engagement lift vs the channel's own norm (per-view, so not a
        #    restatement of the view outlier).
        rate = _num(metrics.get("engagement_rate"))
        channel_rate = _num(metrics.get("channel_avg_engagement"))
        if rate is not None and channel_rate:
            # A measured engagement_rate of exactly 0.0 is the strongest possible
            # "nobody engaged" signal; truthiness was scoring it as no-data,
            # i.e. better than a rate of 0.01.
            lift = rate / channel_rate
            if lift >= 1.3:
                score += 4
            elif lift <= 0.7:
                score -= 4

        return max(0.0, min(score, GAP_MAX))

    def _calc_stack_fit(self, topic: TopicRawData) -> tuple[float, list[str]]:
        """Calculate stack fit (0-15) — can WE make this well?

        Nothing in the previous score asked this, so the pipeline happily
        auto-approved topics needing a face on camera, live footage, or a
        runtime it does not produce. Returns the score plus the reasons, because
        'rejected for fit' is only actionable if it says which constraint hit.
        """
        profile = self._stack
        metrics = topic.raw_metrics or {}
        notes: list[str] = []

        if not profile.is_configured:
            return STACK_FIT_NEUTRAL, ["stack fit: no profile configured (neutral)"]

        title_lower = (topic.title or "").lower()
        for raw_word in profile.blocked_keywords:
            # A blank entry (trailing comma in channel config) built the pattern
            # `(?!\w)`, which matches anywhere — every topic vetoed. A non-str
            # entry raised AttributeError out of score_batch.
            word = str(raw_word).strip()
            if not word:
                continue
            # Word boundaries, not substring: `{"gun"}` was zeroing the title
            # "Begun: the retirement crisis". A hard veto has to be precise or
            # operators stop trusting it and stop configuring it. The boundary
            # is applied only on the sides that ARE word characters, otherwise a
            # keyword like "c++" becomes unmatchable — \b after '+' requires a
            # word character to follow it.
            if re.search(_boundary_pattern(word), title_lower):
                return 0.0, [f"stack fit 0: blocked keyword '{word}'"]

        requirements = _as_set(metrics.get("production_requirements"))
        unsupported = requirements & _as_set(profile.unsupported_requirements)
        if unsupported:
            return 0.0, [f"stack fit 0: needs {sorted(unsupported)} which we cannot produce"]

        score = 0.0

        # Niche (6) — the single biggest driver of whether the output is good.
        if profile.niches:
            if topic.niche in profile.niches:
                score += 6
            else:
                notes.append(f"off-niche: {topic.niche}")
        else:
            score += 3  # unknown → half credit, not full

        # Market (3).
        if profile.markets:
            if topic.market in profile.markets:
                score += 3
            else:
                notes.append(f"off-market: {topic.market}")
        else:
            score += 1.5

        # Runtime (4).
        low, high = profile.duration_minutes
        duration = _num(metrics.get("duration_minutes"))
        # A zero on EITHER side means "open-ended on that side", not "dimension
        # off": (0, 20) is "up to 20 minutes" and (10, 0) is "at least 10". The
        # first fix only handled the first case, so (10, 0) silently disabled
        # the check again and a 1-minute short scored as unknown.
        band_configured = bool(low) or bool(high)
        effective_low = low if low else 0.0
        effective_high = high if high else float("inf")
        if band_configured and duration is not None and duration > 0:
            low, high = effective_low, effective_high
            if low <= duration <= high:
                score += 4
            elif low * 0.6 <= duration <= (high * 1.5 if high != float("inf") else high):
                score += 2
                notes.append(f"runtime {duration:.0f}m is outside our "
                             f"{low:.0f}-{_band_label(high)}m band")
            else:
                notes.append(
                    f"runtime {duration:.0f}m is far outside our "
                    f"{low:.0f}-{_band_label(high)}m band")
        else:
            score += 2  # unknown runtime → neutral half

        # Proven format (2).
        if profile.proven_title_patterns:
            patterns = _as_set(metrics.get("title_patterns"))
            if patterns & _as_set(profile.proven_title_patterns):
                score += 2
            elif patterns:
                notes.append("title format is one we have not shipped before")
            else:
                score += 1
        else:
            score += 1

        return max(0.0, min(score, STACK_FIT_MAX)), notes

    @staticmethod
    def _calc_rpm_potential(market: Market) -> float:
        """Calculate RPM potential (0-20).

        = min(MARKET_RPM[market], 20)
        """
        return min(MARKET_RPM.get(market, 7.0), 20.0)

    async def _calc_novelty(self, topic: TopicRawData) -> float:
        """Calculate novelty vs knowledge base (0-10).

        If kb_client is None → return 5 (neutral).
        Otherwise:
        - Query KB "scripts" collection with topic.title
        - If best match similarity > 0.85 → 0 (duplicate)
        - If similarity 0.7-0.85 → 3 (related)
        - If similarity < 0.7 → 10 (novel)
        """
        if self._kb is None:
            return 5

        try:
            result = await self._kb.query(
                collection="scripts",
                query_text=topic.title,
                n_results=1,
            )

            if not result or not result.get("distances"):
                return 10  # No matches = novel

            distance = result["distances"][0][0]
            similarity = 1 - distance

            if similarity > 0.85:
                return 0  # Duplicate
            elif similarity >= 0.7:
                return 3  # Related
            else:
                return 10  # Novel

        except Exception as exc:
            logger.warning(
                "Novelty check failed",
                topic=topic.title,
                error=str(exc),
            )
            return 5  # Neutral on error
