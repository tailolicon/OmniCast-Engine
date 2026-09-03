"""Winner/control labelling that survives an audit.

The first pass labelled by raw views against the channel median. That rewards
age (a two-year-old video has had two years to accumulate views), ignores
format (a 45-second Short and a 15-minute explainer are not the same game),
and pairs nothing — so a "winner vs control" difference could be a difference
between old and new, or between Shorts and long-form, wearing a performance
label.

This module labels by VELOCITY on SETTLED videos and builds matched pairs
inside a channel:

  * velocity  = views / days_since_publish, so age stops being the signal;
  * settled   = older than MIN_AGE_DAYS, so a video posted yesterday is not
                called a loser for not having views yet;
  * format    = Shorts and long-form are labelled in separate pools;
  * pairing   = each winner takes the nearest control from the SAME channel,
                same format, closest duration and publish date.

Nothing here promotes a finding on its own; it produces the cohort that the
statistics in `craft_forensics.compare_cohort` are then allowed to test.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

MIN_AGE_DAYS = 21          # a video needs time to find its audience
SHORT_MAX_SECONDS = 180    # YouTube Shorts + very short uploads
WINNER_RATIO = 1.5         # velocity vs the channel's settled median
CONTROL_RATIO = 0.9


@dataclass
class LabelledVideo:
    video_id: str
    channel: str
    title: str = ""
    views: int = 0
    duration_s: float = 0.0
    published_at: str = ""
    age_days: float = 0.0
    velocity: float = 0.0          # views per day
    fmt: str = "long"              # long | short
    role: str = ""                 # winner | control | "" (mid-band/unsettled)
    matched_control: str = ""      # video_id of the paired control (winners only)
    pair_duration_gap_min: float | None = None
    pair_age_gap_days: float | None = None
    note: str = ""


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _age_days(published_at: str, now: datetime | None = None) -> float:
    dt = _parse_dt(published_at)
    if dt is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def label_corpus(raw_by_channel: dict[str, list[dict]], *,
                 now: datetime | None = None) -> list[LabelledVideo]:
    """Label every video by within-channel, within-format view velocity."""
    out: list[LabelledVideo] = []
    for channel, items in raw_by_channel.items():
        rows: list[LabelledVideo] = []
        for v in items:
            vid = v.get("video_id")
            if not vid:
                continue
            dur = float(v.get("duration_seconds")
                        or (float(v.get("duration_minutes")
                                  or v.get("duration_min") or 0) * 60) or 0)
            age = _age_days(v.get("published_at") or v.get("publishedAt") or "", now)
            views = int(v.get("views") or v.get("view_count") or 0)
            rows.append(LabelledVideo(
                video_id=vid, channel=channel, title=v.get("title", ""),
                views=views, duration_s=dur,
                published_at=v.get("published_at") or v.get("publishedAt") or "",
                age_days=round(age, 1),
                velocity=round(views / age, 2) if age >= 1 else 0.0,
                fmt=("short" if (dur and dur <= SHORT_MAX_SECONDS) else "long"),
            ))

        for fmt in ("long", "short"):
            pool = [r for r in rows if r.fmt == fmt]
            settled = [r for r in pool if r.age_days >= MIN_AGE_DAYS and r.velocity > 0]
            if len(settled) < 4:
                for r in pool:
                    r.note = (f"channel/{fmt} pool too small to label "
                              f"({len(settled)} settled videos)")
                continue
            med = statistics.median([r.velocity for r in settled])
            for r in pool:
                if r.age_days < MIN_AGE_DAYS:
                    r.note = f"unsettled ({r.age_days:.0f}d < {MIN_AGE_DAYS}d)"
                    continue
                if not r.velocity:
                    r.note = "no velocity (missing views or date)"
                    continue
                ratio = r.velocity / med if med else 0.0
                if ratio >= WINNER_RATIO:
                    r.role = "winner"
                elif ratio <= CONTROL_RATIO:
                    r.role = "control"
                else:
                    r.note = f"mid-band (velocity ratio {ratio:.2f})"
        out.extend(rows)
    return out


# A pair is only a control for duration and recency if those actually match.
# Greedy nearest-neighbour with no ceiling produced a 23.1-minute winner paired
# against a 6.2-minute control and gaps up to 114 days — "matched" in name only.
MAX_DURATION_GAP_MIN = 6.0
MAX_AGE_GAP_DAYS = 60.0


def match_pairs(videos: list[LabelledVideo], *,
                max_duration_gap_min: float = MAX_DURATION_GAP_MIN,
                max_age_gap_days: float = MAX_AGE_GAP_DAYS,
                report: dict | None = None) -> list[tuple[str, str]]:
    """Pair each winner with the closest ACCEPTABLE control.

    Same channel, same format, and within the duration/date ceilings. A winner
    with no control inside the ceilings stays unpaired — an unmatched winner is
    a smaller cohort, a badly matched one is a wrong answer.
    """
    pairs: list[tuple[str, str]] = []
    dropped: list[dict] = []
    by_key: dict[tuple[str, str], list[LabelledVideo]] = {}
    for v in videos:
        by_key.setdefault((v.channel, v.fmt), []).append(v)
    for (_channel, _fmt), group in by_key.items():
        winners = [v for v in group if v.role == "winner"]
        controls = [v for v in group if v.role == "control"]
        used: set[str] = set()
        for w in winners:
            best, best_cost, best_gaps = None, None, None
            for c in controls:
                if c.video_id in used:
                    continue
                dur_gap = abs((c.duration_s or 0) - (w.duration_s or 0)) / 60.0
                age_gap = abs(c.age_days - w.age_days)
                if dur_gap > max_duration_gap_min or age_gap > max_age_gap_days:
                    continue
                cost = dur_gap + age_gap / 30.0
                if best_cost is None or cost < best_cost:
                    best, best_cost, best_gaps = c, cost, (dur_gap, age_gap)
            if best is None:
                dropped.append({"winner": w.video_id, "channel": w.channel,
                                "reason": "no control within duration/date gap"})
                w.note = (w.note or "") + " | unpaired: no control within "
                w.note += f"{max_duration_gap_min}min / {max_age_gap_days}d"
                continue
            used.add(best.video_id)
            w.matched_control = best.video_id
            w.pair_duration_gap_min = round(best_gaps[0], 2)
            w.pair_age_gap_days = round(best_gaps[1], 1)
            pairs.append((w.video_id, best.video_id))
    if report is not None:
        report["dropped_winners"] = dropped
        report["max_duration_gap_min"] = max_duration_gap_min
        report["max_age_gap_days"] = max_age_gap_days
    return pairs


def cohort_report(videos: list[LabelledVideo]) -> dict:
    """What the cohort actually contains — the shape an auditor asks for."""
    by_channel: dict[str, dict] = {}
    for v in videos:
        d = by_channel.setdefault(v.channel, {"winner": 0, "control": 0,
                                              "unlabelled": 0, "short": 0})
        if v.fmt == "short":
            d["short"] += 1
        d[v.role or "unlabelled"] += 1
    pairs = [v for v in videos if v.matched_control]
    dur_gaps = [v.pair_duration_gap_min for v in pairs
                if v.pair_duration_gap_min is not None]
    age_gaps = [v.pair_age_gap_days for v in pairs
                if v.pair_age_gap_days is not None]
    return {
        "pair_quality": {
            "max_duration_gap_min": round(max(dur_gaps), 2) if dur_gaps else None,
            "median_duration_gap_min": (round(statistics.median(dur_gaps), 2)
                                        if dur_gaps else None),
            "max_age_gap_days": round(max(age_gaps), 1) if age_gaps else None,
            "median_age_gap_days": (round(statistics.median(age_gaps), 1)
                                    if age_gaps else None),
            "unpaired_winners": sum(1 for v in videos
                                    if v.role == "winner" and not v.matched_control),
        },
        "videos": len(videos),
        "winners": sum(1 for v in videos if v.role == "winner"),
        "controls": sum(1 for v in videos if v.role == "control"),
        "matched_pairs": len(pairs),
        "channels_with_pairs": len({v.channel for v in pairs}),
        "by_channel": by_channel,
        "labelling": {"metric": "views/day", "min_age_days": MIN_AGE_DAYS,
                      "winner_ratio": WINNER_RATIO,
                      "control_ratio": CONTROL_RATIO,
                      "format_split_seconds": SHORT_MAX_SECONDS},
    }
