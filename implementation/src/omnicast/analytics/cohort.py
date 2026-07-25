"""Winner + matched-control cohort selection for competitor research.

WHY THIS EXISTS (strategic review 2026-07-23, §4.1 and §4.8; both external AI
reviews agreed):

Discovery already finds real winners the right way — per-channel median outliers
(`youtube_scanner._find_outliers`). But `competitor_intel` learned its playbooks
from `sort(views)[:N]`, which answers a different question:

  * absolute views favour BIG channels over the small channel whose video
    genuinely broke out;
  * absolute views favour OLD videos that accumulated views over months;
  * "what do high-view videos look like" is not "what made this video win" —
    describing traits common to winners without a control group is textbook
    survivorship bias. Half those traits are just the channel's house style,
    present in its flops too.

So this module produces a COHORT, not a top-N list:

  winner   — an outlier against its OWN channel's median (breakout proven)
  control  — a sibling video from the SAME channel, near in publish time and
             similar in length, that did NOT break out

A pattern only earns a place in a playbook when it separates the two groups.
Everything here is a pure function over already-fetched video dicts: no network,
no API key, fully testable, and reusable by both the playbook learner and the
NotebookLM research-packet exporter.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

# A winner must beat its channel's median by this much. Matches the discovery
# scanner's OUTLIER_MULTIPLIER family: the same definition of "won" on both
# pipelines was the point of the review finding.
WINNER_MULTIPLIER = 2.0
# A control must be an ORDINARY video for that channel — close to median, not a
# near-miss breakout (which would blur the very contrast we are measuring).
CONTROL_MAX_RATIO = 1.25
# Matching windows. Publish proximity controls for channel growth and algorithm
# era; duration proximity controls for format.
CONTROL_MAX_DAYS_APART = 120
CONTROL_DURATION_TOLERANCE = 0.5  # ±50% of the winner's duration


@dataclass(frozen=True)
class CohortVideo:
    """One video with the provenance a downstream reader needs to trust it."""

    video_id: str
    channel_id: str
    title: str
    role: str  # "winner" | "control"
    views: int
    views_per_day: float
    outlier_ratio: float
    duration_minutes: float
    published_at: str
    engagement_rate: float = 0.0
    matched_to: str = ""  # controls: the winner video_id they are paired with

    def as_row(self) -> dict:
        return {
            "video_id": self.video_id,
            "channel_id": self.channel_id,
            "title": self.title,
            "role": self.role,
            "views": self.views,
            "views_per_day": round(self.views_per_day, 1),
            "outlier_ratio": round(self.outlier_ratio, 2),
            "duration_minutes": round(self.duration_minutes, 1),
            "published_at": self.published_at,
            "engagement_rate": round(self.engagement_rate, 4),
            "matched_to": self.matched_to,
        }


@dataclass
class Cohort:
    """A research cohort plus an honest account of how it was assembled."""

    winners: list[CohortVideo] = field(default_factory=list)
    controls: list[CohortVideo] = field(default_factory=list)
    # Why the cohort is the size it is — silent truncation reads as coverage.
    notes: list[str] = field(default_factory=list)

    @property
    def is_comparable(self) -> bool:
        """Whether a winner-vs-control claim can be made at all.

        With no controls, any 'pattern' found is an uncontrolled observation —
        the caller must degrade its confidence rather than publish it as a
        finding."""
        return bool(self.winners) and bool(self.controls)

    def as_packet(self) -> dict:
        return {
            "winners": [v.as_row() for v in self.winners],
            "controls": [v.as_row() for v in self.controls],
            "winner_count": len(self.winners),
            "control_count": len(self.controls),
            "is_comparable": self.is_comparable,
            "notes": list(self.notes),
            "selection": {
                "winner_multiplier": WINNER_MULTIPLIER,
                "control_max_ratio": CONTROL_MAX_RATIO,
                "control_max_days_apart": CONTROL_MAX_DAYS_APART,
                "control_duration_tolerance": CONTROL_DURATION_TOLERANCE,
            },
        }


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _age_days(published_at: str, now: datetime) -> float:
    stamp = _parse_ts(published_at)
    if stamp is None:
        return 0.0
    return max((now - stamp).total_seconds() / 86400.0, 0.0)


def views_per_day(video: dict, now: datetime) -> float:
    """Age-normalised velocity.

    A 2-year-old video with 1M views and a 3-week-old video with 900k are not
    the same evidence; absolute views said they were."""
    age = _age_days(video.get("published_at", ""), now)
    views = float(video.get("views", 0) or 0)
    # Floor at one day so a video published hours ago cannot produce a spike
    # that dwarfs every established video in the cohort.
    return views / max(age, 1.0)


def _days_apart(a: str, b: str) -> float:
    first, second = _parse_ts(a), _parse_ts(b)
    if first is None or second is None:
        return float("inf")
    return abs((first - second).total_seconds()) / 86400.0


def _duration_matches(winner_minutes: float, candidate_minutes: float) -> bool:
    if winner_minutes <= 0:
        return True  # unknown duration cannot disqualify a control
    low = winner_minutes * (1.0 - CONTROL_DURATION_TOLERANCE)
    high = winner_minutes * (1.0 + CONTROL_DURATION_TOLERANCE)
    return low <= candidate_minutes <= high


def select_cohort(
    videos_by_channel: dict[str, list[dict]],
    *,
    max_winners: int = 12,
    controls_per_winner: int = 1,
    now: datetime | None = None,
) -> Cohort:
    """Build a winner + matched-control cohort from raw per-channel video dicts.

    Each video dict needs: video_id, title, views, duration_minutes,
    published_at; engagement_rate is optional. Channels with fewer than three
    videos are skipped — a median over one or two videos defines nothing.
    """
    now = now or datetime.now(timezone.utc)
    cohort = Cohort()
    ranked: list[tuple[float, CohortVideo, list[dict], float]] = []

    for channel_id, videos in sorted(videos_by_channel.items()):
        usable = [v for v in videos if v.get("video_id")]
        if len(usable) < 3:
            cohort.notes.append(
                f"{channel_id}: skipped, only {len(usable)} video(s) — a channel "
                "median needs at least 3"
            )
            continue
        median_views = statistics.median(float(v.get("views", 0) or 0) for v in usable)
        if median_views <= 0:
            cohort.notes.append(f"{channel_id}: skipped, median views is zero")
            continue

        for video in usable:
            ratio = float(video.get("views", 0) or 0) / median_views
            if ratio < WINNER_MULTIPLIER:
                continue
            winner = CohortVideo(
                video_id=video["video_id"],
                channel_id=channel_id,
                title=video.get("title", ""),
                role="winner",
                views=int(video.get("views", 0) or 0),
                views_per_day=views_per_day(video, now),
                outlier_ratio=ratio,
                duration_minutes=float(video.get("duration_minutes", 0) or 0),
                published_at=video.get("published_at", ""),
                engagement_rate=float(video.get("engagement_rate", 0) or 0),
            )
            ranked.append((ratio, winner, usable, median_views))

    # Strongest breakouts first — outlier ratio, NOT absolute views.
    ranked.sort(key=lambda item: item[0], reverse=True)
    if len(ranked) > max_winners:
        cohort.notes.append(
            f"{len(ranked)} winners found; kept the {max_winners} strongest by "
            "outlier ratio"
        )
        ranked = ranked[:max_winners]

    used_controls: set[str] = set()
    for _ratio, winner, siblings, median_views in ranked:
        cohort.winners.append(winner)
        candidates: list[tuple[float, CohortVideo]] = []
        for sibling in siblings:
            sid = sibling.get("video_id", "")
            if sid == winner.video_id or sid in used_controls:
                continue
            sibling_ratio = float(sibling.get("views", 0) or 0) / median_views
            if sibling_ratio > CONTROL_MAX_RATIO:
                continue  # a near-breakout is not an ordinary video
            gap = _days_apart(winner.published_at, sibling.get("published_at", ""))
            if gap > CONTROL_MAX_DAYS_APART:
                continue
            sibling_minutes = float(sibling.get("duration_minutes", 0) or 0)
            if not _duration_matches(winner.duration_minutes, sibling_minutes):
                continue
            candidates.append((
                gap,
                CohortVideo(
                    video_id=sid,
                    channel_id=winner.channel_id,
                    title=sibling.get("title", ""),
                    role="control",
                    views=int(sibling.get("views", 0) or 0),
                    views_per_day=views_per_day(sibling, now),
                    outlier_ratio=sibling_ratio,
                    duration_minutes=sibling_minutes,
                    published_at=sibling.get("published_at", ""),
                    engagement_rate=float(sibling.get("engagement_rate", 0) or 0),
                    matched_to=winner.video_id,
                ),
            ))
        # Closest in publish time wins: it shares the most channel context.
        candidates.sort(key=lambda item: item[0])
        picked = candidates[:controls_per_winner]
        if not picked:
            cohort.notes.append(
                f"{winner.video_id}: no matched control (same channel, "
                f"<={CONTROL_MAX_DAYS_APART}d apart, similar length, not itself a "
                "breakout) — winner-only evidence"
            )
        for _gap, control in picked:
            used_controls.add(control.video_id)
            cohort.controls.append(control)

    if not cohort.winners:
        cohort.notes.append("no winner cleared the outlier threshold")
    return cohort
