"""Competitor publishing schedule — measured, and refusing to claim causation.

WHY (strategic review §4.6):

`upload/scheduler.py` picks slots from a hard-coded per-market table. The
scanner has had `published_at` on every video the whole time. So the system
already held the data to answer "when does this niche actually publish, and what
performs" and never looked at it.

What this module measures:

  * a weekday x hour heatmap of publishing activity;
  * upload cadence — median gap between uploads, and the longest silence;
  * cadence per content pillar (§4.2 — a channel's flagship series and its
    filler run on different clocks);
  * per-slot performance, in views/day, so an old video does not out-rank a
    recent one for reasons unrelated to its slot.

TWO REFUSALS, BOTH LOAD-BEARING:

1. NO CAUSAL CLAIM. "The best videos went out at 08:00" does not mean 08:00
   caused anything: channels put their most-promoted, best-produced video in
   their habitual slot, so slot correlates with effort. Every performance
   result carries `causal: False` and a note saying so, and the recommendation
   is phrased as "match the niche's habit", not "publish at 8 to win".

2. NO SLOT REPORTED BELOW `MIN_VIDEOS_PER_SLOT`. With 50 videos spread over 168
   weekday-hour cells, the winning cell is usually a cell with one video in it.
   Ranking those is ranking noise.

TIMEZONE. `published_at` from the YouTube API is UTC. Viewers are not in UTC and
neither are creators. Every hour here is UTC and labelled as such; converting to
a market timezone is a real improvement and a separate change, not something to
fudge silently by adding an offset.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Below this, a slot's "performance" is one video's luck.
MIN_VIDEOS_PER_SLOT = 3
# Below this many videos overall, cadence statistics are not worth reporting.
MIN_VIDEOS_FOR_CADENCE = 5

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _views_per_day(video: dict, now: datetime) -> float | None:
    stamp = _parse(video.get("published_at", ""))
    if stamp is None:
        return None
    age = max((now - stamp).total_seconds() / 86400.0, 1.0)
    return float(video.get("views", 0) or 0) / age


@dataclass
class ScheduleProfile:
    """Everything measurable about when a competitor set publishes."""

    videos_analysed: int = 0
    videos_skipped: int = 0
    timezone_note: str = "all hours are UTC — viewer-local time was not derived"
    heatmap: dict[str, int] = field(default_factory=dict)      # "Tue 14" -> count
    weekday_counts: dict[str, int] = field(default_factory=dict)
    hour_counts: dict[int, int] = field(default_factory=dict)
    median_gap_days: float | None = None
    longest_gap_days: float | None = None
    uploads_per_week: float | None = None
    pillar_cadence: dict[str, dict] = field(default_factory=dict)
    slot_performance: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def habitual_slots(self) -> list[str]:
        """The slots this niche actually uses most — a habit, not a cause."""
        return [slot for slot, _count in
                sorted(self.heatmap.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]

    def as_dict(self) -> dict:
        return {
            "videos_analysed": self.videos_analysed,
            "videos_skipped": self.videos_skipped,
            "timezone_note": self.timezone_note,
            "heatmap": dict(self.heatmap),
            "weekday_counts": dict(self.weekday_counts),
            "hour_counts": {str(k): v for k, v in self.hour_counts.items()},
            "median_gap_days": self.median_gap_days,
            "longest_gap_days": self.longest_gap_days,
            "uploads_per_week": self.uploads_per_week,
            "pillar_cadence": dict(self.pillar_cadence),
            "slot_performance": list(self.slot_performance),
            "habitual_slots": self.habitual_slots,
            "causal": False,
            "causal_note": (
                "Slot performance is CORRELATION ONLY. Channels put their "
                "best-produced, most-promoted videos in their habitual slot, so "
                "slot and effort move together. Use this to match the niche's "
                "publishing habit, not as evidence that an hour causes views."
            ),
            "notes": list(self.notes),
        }


def analyse_schedule(
    videos: list[dict],
    *,
    pillar_of=None,
    now: datetime | None = None,
) -> ScheduleProfile:
    """Measure the publishing schedule of a set of competitor videos.

    `videos` need `published_at`; `views` is used for slot performance when
    present. `pillar_of` is an optional callable video -> pillar id (see
    `analytics.pillars`), so cadence can be reported per pillar without this
    module knowing anything about how pillars are defined.
    """
    now = now or datetime.now(timezone.utc)
    profile = ScheduleProfile()

    dated: list[tuple[datetime, dict]] = []
    for video in videos or []:
        stamp = _parse(video.get("published_at", ""))
        if stamp is None:
            profile.videos_skipped += 1
            continue
        dated.append((stamp, video))

    if profile.videos_skipped:
        profile.notes.append(
            f"{profile.videos_skipped} video(s) had no usable publish timestamp "
            "and were excluded")

    if not dated:
        profile.notes.append("no video carried a usable publish timestamp")
        return profile

    dated.sort(key=lambda item: item[0])
    profile.videos_analysed = len(dated)

    heat: Counter[str] = Counter()
    weekdays: Counter[str] = Counter()
    hours: Counter[int] = Counter()
    for stamp, _video in dated:
        weekday = WEEKDAYS[stamp.weekday()]
        heat[f"{weekday} {stamp.hour:02d}"] += 1
        weekdays[weekday] += 1
        hours[stamp.hour] += 1
    profile.heatmap = dict(heat)
    profile.weekday_counts = dict(weekdays)
    profile.hour_counts = dict(hours)

    # ── cadence ──────────────────────────────────────────────────────────────
    if len(dated) >= MIN_VIDEOS_FOR_CADENCE:
        gaps = [(b[0] - a[0]).total_seconds() / 86400.0
                for a, b in zip(dated, dated[1:])]
        gaps = [g for g in gaps if g >= 0]
        if gaps:
            profile.median_gap_days = round(statistics.median(gaps), 2)
            profile.longest_gap_days = round(max(gaps), 2)
            span_days = (dated[-1][0] - dated[0][0]).total_seconds() / 86400.0
            if span_days > 0:
                profile.uploads_per_week = round(len(dated) / (span_days / 7.0), 2)
    else:
        profile.notes.append(
            f"cadence not reported: {len(dated)} videos is below the "
            f"{MIN_VIDEOS_FOR_CADENCE} needed for a gap distribution")

    # ── cadence per pillar ───────────────────────────────────────────────────
    if pillar_of is not None:
        by_pillar: dict[str, list[datetime]] = defaultdict(list)
        for stamp, video in dated:
            by_pillar[pillar_of(video)].append(stamp)
        for pillar_id, stamps in sorted(by_pillar.items()):
            entry: dict = {"videos": len(stamps)}
            if len(stamps) >= 2:
                pillar_gaps = [(b - a).total_seconds() / 86400.0
                               for a, b in zip(stamps, stamps[1:])]
                entry["median_gap_days"] = round(statistics.median(pillar_gaps), 2)
            else:
                entry["median_gap_days"] = None
                entry["note"] = "one video — no interval to measure"
            profile.pillar_cadence[pillar_id] = entry

    # ── per-slot performance ─────────────────────────────────────────────────
    velocity_by_slot: dict[str, list[float]] = defaultdict(list)
    for stamp, video in dated:
        velocity = _views_per_day(video, now)
        if velocity is None:
            continue
        velocity_by_slot[f"{WEEKDAYS[stamp.weekday()]} {stamp.hour:02d}"].append(velocity)

    thin = 0
    for slot, velocities in velocity_by_slot.items():
        if len(velocities) < MIN_VIDEOS_PER_SLOT:
            thin += 1
            continue
        profile.slot_performance.append({
            "slot_utc": slot,
            "videos": len(velocities),
            "median_views_per_day": round(statistics.median(velocities), 1),
        })
    profile.slot_performance.sort(
        key=lambda row: (-row["median_views_per_day"], row["slot_utc"]))
    if thin:
        profile.notes.append(
            f"{thin} slot(s) held fewer than {MIN_VIDEOS_PER_SLOT} videos and were "
            "not ranked — a one-video slot is noise, not a best time to post")
    if not profile.slot_performance:
        profile.notes.append(
            "no slot cleared the minimum sample: this competitor set cannot "
            "support a best-time-to-post claim")
    return profile
