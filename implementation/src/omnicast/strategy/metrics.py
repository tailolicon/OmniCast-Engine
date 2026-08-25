"""Shorts->long funnel, audience journey and long-term metrics.

Covers strategic review §11.3, §11.4 and §11.6.

§11.6 IS MOSTLY ABOUT WHAT WE CANNOT COMPUTE YET, AND THAT IS THE POINT.

The review lists twelve long-term metrics. Some fall straight out of data the
system already holds (views per viewer, library compounding, revenue per
production hour). Several need YouTube Analytics fields the collector does
fetch for OUR channels (returning viewers, subscriber conversion, browse
dependency). A few need instrumentation nobody has built (series continuation,
comment quality, brand trust).

Every one of them is reported with a status and, when it is absent, WHAT WOULD
BE NEEDED. A dashboard that shows nine metrics and silently omits three teaches
its reader that there are nine. That is how "we only optimise views" survives a
redesign that was supposed to end it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MEASURED = "measured"
INFERRED = "inferred"
MISSING = "missing"

# §11.4, in order. Each stage wants different content, CTA and packaging, so the
# stage a viewer is in is a routing decision, not a label.
JOURNEY_STAGES: tuple[tuple[str, str, str], ...] = (
    ("cold", "has never seen this channel",
     "packaging must carry the whole promise; assume no context and no trust"),
    ("casual", "watched once, did not subscribe",
     "give a reason to expect more of the same; name the series"),
    ("subscriber", "subscribed, watches occasionally",
     "deliver the promised cadence; a subscriber who is surprised is churning"),
    ("returning", "comes back without being served the video",
     "reward the habit: continuity, callbacks, the next episode"),
    ("core_fan", "watches nearly everything",
     "depth over reach; this is who tentpoles and long-form are for"),
    ("community", "comments, shares, buys",
     "ask for something: the CTA is allowed to cost them effort"),
)

# What each §11.6 metric needs. Written down so a missing metric names its own
# unblocking step instead of just being absent.
METRIC_REQUIREMENTS: dict[str, str] = {
    "returning_viewers": "YouTube Analytics returningViewers dimension for our channel",
    "subscriber_conversion": "subscribersGained per video from YouTube Analytics",
    "views_per_viewer": "views and unique viewers over the same window",
    "series_continuation_rate": "a declared series id per video, then next-video views",
    "search_longevity": "traffic-source split over time (trafficSourceType=YT_SEARCH)",
    "browse_dependency": "traffic-source split (trafficSourceType=BROWSE_FEATURES)",
    "shorts_to_long_conversion": "shorts and long-form linked by declared target video",
    "comment_quality": "comment text plus a quality rubric nobody has defined yet",
    "library_compounding": "views of videos older than 90 days, over time",
    "revenue_per_production_hour": "estimated revenue and recorded production hours",
    "cost_per_retained_minute": "production cost and total watch-time minutes",
    "brand_trust": "not instrumented — needs survey or sentiment methodology",
}


@dataclass
class Metric:
    name: str
    value: object = None
    status: str = MISSING
    detail: str = ""

    def as_dict(self) -> dict:
        return {"metric": self.name, "value": self.value, "status": self.status,
                "detail": self.detail}


@dataclass
class LongTermMetrics:
    metrics: list[Metric] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def get(self, name: str) -> Metric | None:
        return next((m for m in self.metrics if m.name == name), None)

    @property
    def coverage(self) -> float:
        if not self.metrics:
            return 0.0
        solid = sum(1 for m in self.metrics if m.status in (MEASURED, INFERRED))
        return round(solid / len(self.metrics), 3)

    def as_dict(self) -> dict:
        return {
            "metrics": [m.as_dict() for m in self.metrics],
            "coverage": self.coverage,
            "missing": [m.name for m in self.metrics if m.status == MISSING],
            "note": (
                "Views is not on this list on purpose. Every metric here answers "
                "whether the LIBRARY is compounding; a dashboard that quietly "
                "drops the ones it cannot compute teaches its reader that the "
                "list was shorter than it is."
            ),
            "notes": list(self.notes),
        }


from omnicast.shared.numbers import num as _num  # noqa: E402
from omnicast.shared.numbers import ratio as _ratio  # noqa: E402


def _dict(value) -> dict:
    """Only a real mapping. `x or {}` let a list through and raised on `.get`."""
    return value if isinstance(value, dict) else {}


from omnicast.shared.numbers import flag as _flag  # noqa: E402


def classify_journey_stage(signals: dict) -> tuple[str, str]:
    """(stage, why) for one viewer cohort, from whatever signals exist.

    Coarse on purpose. The public API gives us cohort-level data, not per-viewer
    histories, so this classifies a COHORT and says which signal decided it —
    a per-viewer claim would be a fabrication dressed as personalisation."""
    signals = _dict(signals)
    videos = _num(signals.get("videos_watched"))
    if videos is None and signals.get("videos_watched") is not None:
        # An unusable count is not "never watched". Saying so out loud beats
        # classifying an infinite watch history as a cold viewer.
        return "cold", "watch count was not a usable number — treated as unknown"
    videos = videos or 0.0
    subscribed = _flag(signals.get("subscribed"))
    commented = _flag(signals.get("commented")) or _flag(signals.get("purchased"))
    returned = _flag(signals.get("returned_without_recommendation"))

    if commented:
        return "community", "commented or purchased"
    if videos >= 10:
        return "core_fan", f"{videos:.0f} videos watched"
    if returned:
        return "returning", "came back without being served the video"
    if subscribed:
        return "subscriber", "subscribed"
    if videos >= 1:
        return "casual", f"{videos:.0f} video(s) watched, not subscribed"
    return "cold", "no watch history with this channel"


def shorts_to_long_funnel(shorts: list[dict], longs: list[dict]) -> dict:
    """§11.3 — measure the funnel, and refuse to invent the link.

    A short converts to a long-form video only if somebody DECLARED which long
    video it points at. Inferring the link from timing or topic overlap would
    manufacture a conversion rate out of a coincidence, and the resulting number
    would be indistinguishable from a real one."""
    shorts = [s for s in (shorts or []) if isinstance(s, dict)]
    longs = [v for v in (longs or []) if isinstance(v, dict)]
    long_ids = {str(v.get("video_id") or "") for v in longs if v.get("video_id")}

    linked = [s for s in shorts
              if str(s.get("targets_video_id") or "") in long_ids]
    linked_ids = {id(s) for s in linked}
    unlinked = [s for s in shorts if id(s) not in linked_ids]

    roles: dict[str, int] = {}
    for short in shorts:
        role = str(short.get("role") or "undeclared").strip().lower()
        roles[role] = roles.get(role, 0) + 1

    result = {
        "shorts": len(shorts),
        "long_form": len(longs),
        "linked_shorts": len(linked),
        "unlinked_shorts": len(unlinked),
        "roles": dict(sorted(roles.items())),
        "conversion_rate": None,
        "status": MISSING,
        "notes": [],
    }

    if not linked:
        result["notes"].append(
            "no short declares a target long-form video, so there is no funnel "
            "to measure. The link is not inferrable: guessing it from timing or "
            "topic overlap would turn a coincidence into a conversion rate")
        return result

    clicks = sum(max(_num(s.get("clicks_to_target")) or 0.0, 0.0) for s in linked)
    views = sum(max(_num(s.get("views")) or 0.0, 0.0) for s in linked)
    if views <= 0:
        result["notes"].append("linked shorts report no views — nothing to divide by")
        return result
    if clicks <= 0:
        result["notes"].append(
            "linked shorts report no click-through data; YouTube does not expose "
            "short->long clicks on the public API, so this needs the Analytics "
            "API for our own channel")
        return result

    # A conversion rate is definitionally <= 1: more clicks than views means the
    # inputs disagree, not that the funnel converts at 10000%.
    converted = _ratio(clicks, views, high=1.0)
    if converted is None:
        result["notes"].append(
            f"{clicks:.0f} clicks against {views:.0f} views is not a conversion "
            "rate — the two counts do not describe the same thing")
        return result
    result["conversion_rate"] = round(converted, 4)
    result["status"] = MEASURED
    return result


def measure_long_term(*, channel_metrics: dict | None = None,
                      library: list[dict] | None = None,
                      production: dict | None = None) -> LongTermMetrics:
    """Compute what the available data supports; name what is missing and why."""
    report = LongTermMetrics()
    channel_metrics = _dict(channel_metrics)
    library = [v for v in (library or []) if isinstance(v, dict)] \
        if isinstance(library, (list, tuple)) else []
    production = _dict(production)

    def add(name: str, value=None, status: str = MISSING, detail: str = ""):
        report.metrics.append(Metric(
            name=name, value=value, status=status,
            detail=detail or (f"needs: {METRIC_REQUIREMENTS[name]}"
                              if status == MISSING and name in METRIC_REQUIREMENTS
                              else detail)))

    # ── computable from what the system already holds ────────────────────────
    per_viewer = _ratio(channel_metrics.get("views"),
                        channel_metrics.get("unique_viewers"))
    if per_viewer is not None:
        add("views_per_viewer", round(per_viewer, 3), MEASURED,
            "views / unique viewers over the same window")
    else:
        add("views_per_viewer")

    if library:
        # A row whose view count is unusable is DROPPED and counted, not
        # clamped to zero: clamping produced "100% of views come from the back
        # catalogue" from one malformed row, reported as measured.
        bad_rows = sum(1 for v in library if _num(v.get("views")) is None
                       or (_num(v.get("views")) or 0.0) < 0)
        usable = [v for v in library
                  if (_num(v.get("views")) or -1.0) >= 0]
        usable_old = [v for v in usable if (_num(v.get("age_days")) or 0) >= 90]
        old_views = sum(_num(v.get("views")) or 0.0 for v in usable_old)
        total_views = sum(_num(v.get("views")) or 0.0 for v in usable)
        if bad_rows:
            report.notes.append(
                f"{bad_rows} library row(s) had an unusable view count and were "
                "excluded from library_compounding")
        # `high=1.0`: a share of total views cannot exceed 1. A negative view
        # count on one row used to produce "1000% of views come from the back
        # catalogue", reported as MEASURED.
        share = _ratio(old_views, total_views, high=1.0)
        if share is not None:
            add("library_compounding", round(share, 3), MEASURED,
                f"{len(usable_old)} of {len(usable)} usable videos are older than "
                "90 days and "
                "carry this share of total views — a library that compounds keeps "
                "earning from its back catalogue")
        else:
            add("library_compounding", None, MISSING,
                "library has no usable view counts to compound")
    else:
        add("library_compounding")

    per_hour = _ratio(production.get("estimated_revenue_usd"),
                      production.get("production_hours"))
    if per_hour is not None:
        add("revenue_per_production_hour", round(per_hour, 2), INFERRED,
            "revenue is ESTIMATED from RPM, not read from a payout report")
    else:
        add("revenue_per_production_hour")

    per_minute = _ratio(production.get("production_cost_usd"),
                        channel_metrics.get("watch_time_minutes"))
    if per_minute is not None:
        add("cost_per_retained_minute", round(per_minute, 5), MEASURED,
            "production cost / total watch-time minutes")
    else:
        add("cost_per_retained_minute")

    # ── available from YouTube Analytics for OUR channel, if collected ───────
    for name, key in (("returning_viewers", "returning_viewers"),
                      ("subscriber_conversion", "subscriber_conversion"),
                      ("search_longevity", "search_share"),
                      ("browse_dependency", "browse_share")):
        value = _num(channel_metrics.get(key))
        if value is not None:
            add(name, value, MEASURED, f"from channel metrics field '{key}'")
        else:
            add(name)

    # ── not instrumented ─────────────────────────────────────────────────────
    for name in ("series_continuation_rate", "shorts_to_long_conversion",
                 "comment_quality", "brand_trust"):
        add(name)

    if report.coverage < 0.5:
        report.notes.append(
            f"only {report.coverage:.0%} of the §11.6 metrics can be computed "
            "from the data currently collected — the missing ones each name what "
            "would unblock them")
    return report
