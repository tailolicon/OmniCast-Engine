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
  control  — a sibling video from the SAME channel, near in publish time,
             similar in length and similar in TITLE FORMAT, that did NOT
             break out

A pattern only earns a place in a playbook when it separates the two groups.
Everything here is a pure function over already-fetched video dicts: no network,
no API key, fully testable, and reusable by both the playbook learner and the
NotebookLM research-packet exporter.

P0.1 GROUP 2 (2026-07-25) — four changes, each of which was unsafe alone:

1. VELOCITY, NOT VOLUME, ON BOTH SIDES OF THE RATIO. `views_per_day` existed but
   was decoration: selection still divided raw `views` by a raw-`views` median.
   Moving only the numerator would have compared a per-day rate against a
   lifetime total — a unit mismatch that is worse than the original bug because
   it looks principled. Both sides are now per-day, and the ratio is therefore
   dimensionless again.
   Velocity brings its own bias, so it is fenced: a video younger than
   `MIN_SETTLED_AGE_DAYS` is excluded from the median AND from eligibility. A
   6-hour-old video with 10k views has a per-day rate no established video can
   match; without the fence, "winner" would have quietly come to mean "newest".
   Videos whose publish timestamp cannot be parsed have no velocity at all and
   are dropped with a note rather than silently treated as one day old.

2. COMPARABILITY IS A PROPERTY OF A PAIR. `is_comparable` used to be
   `winners and controls` — so 12 winners sharing 1 control reported as fully
   controlled, and every downstream consumer read 11 uncontrolled observations
   as verified findings. Comparability is now per winner, the cohort exposes
   `matched_pairs` / `unmatched_winners` / `control_coverage`, and callers can
   contrast on the matched pairs while labelling the rest as what they are.

3. NO CHANNEL MAY OWN THE COHORT. One prolific channel could supply all 12
   winners, and the "playbook" would be that channel's house style — the exact
   failure a control group exists to prevent, re-entering through sampling.
   `max_winners_per_channel` caps it.

4. FORMAT IS CONTROLLED FOR, CHEAPLY. Pairing a listicle winner against a plain
   statement control means the biggest difference between the groups is one we
   introduced. Controls now prefer a matching title shape (a deterministic,
   LLM-free proxy — see `shared.title_patterns`). It is a PREFERENCE, not a
   filter: a format-mismatched control beats no control, and the mismatch is
   recorded on the row instead of being hidden.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

from omnicast.shared.title_patterns import classify_title, formats_match

# A winner must beat its channel's median VELOCITY by this much. Matches the
# discovery scanner's OUTLIER_MULTIPLIER family: the same definition of "won" on
# both pipelines was the point of the review finding.
WINNER_MULTIPLIER = 2.0
# A control must be an ORDINARY video for that channel — close to median, not a
# near-miss breakout (which would blur the very contrast we are measuring).
CONTROL_MAX_RATIO = 1.25
# Matching windows. Publish proximity controls for channel growth and algorithm
# era; duration proximity controls for format.
CONTROL_MAX_DAYS_APART = 120
CONTROL_DURATION_TOLERANCE = 0.5  # ±50% of the winner's duration
# Below this age a per-day rate is noise, not evidence: the denominator is tiny
# and the video is still inside its recommendation surge.
MIN_SETTLED_AGE_DAYS = 7.0
# No single channel may contribute more than this many winners.
MAX_WINNERS_PER_CHANNEL = 3


@dataclass(frozen=True)
class CohortVideo:
    """One video with the provenance a downstream reader needs to trust it."""

    video_id: str
    channel_id: str
    title: str
    role: str  # "winner" | "control"
    views: int
    views_per_day: float
    outlier_ratio: float  # velocity vs the channel's median velocity
    duration_minutes: float
    published_at: str
    engagement_rate: float = 0.0
    matched_to: str = ""  # controls: the winner video_id they are paired with
    title_patterns: tuple[str, ...] = ()
    # Controls only. False means this pair does NOT control for title format, so
    # a format difference between the groups may be an artefact of matching.
    format_matched: bool = True

    def as_row(self) -> dict:
        row = {
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
            "title_patterns": list(self.title_patterns),
        }
        if self.role == "control":
            row["format_matched"] = self.format_matched
        return row


@dataclass
class Cohort:
    """A research cohort plus an honest account of how it was assembled."""

    winners: list[CohortVideo] = field(default_factory=list)
    controls: list[CohortVideo] = field(default_factory=list)
    # Why the cohort is the size it is — silent truncation reads as coverage.
    notes: list[str] = field(default_factory=list)

    # ── pair-level comparability ─────────────────────────────────────────────

    def controls_for(self, winner_id: str) -> list[CohortVideo]:
        return [c for c in self.controls if c.matched_to == winner_id]

    @property
    def matched_pairs(self) -> list[tuple[CohortVideo, list[CohortVideo]]]:
        """Winners that actually have something to be contrasted against.

        This — not `winners` — is the set a contrast claim may be made over."""
        pairs = [(w, self.controls_for(w.video_id)) for w in self.winners]
        return [(w, cs) for w, cs in pairs if cs]

    @property
    def matched_winners(self) -> list[CohortVideo]:
        return [w for w, _ in self.matched_pairs]

    @property
    def unmatched_winners(self) -> list[CohortVideo]:
        """Winners with no control: observations, never findings."""
        return [w for w in self.winners if not self.controls_for(w.video_id)]

    @property
    def control_coverage(self) -> float:
        """Fraction of winners that are individually controlled (0.0-1.0)."""
        if not self.winners:
            return 0.0
        return len(self.matched_winners) / len(self.winners)

    @property
    def comparability(self) -> str:
        """`full` | `partial` | `none` — the honest three-state answer.

        The old two-state `is_comparable` had no way to say "1 of 12", which is
        the case that actually occurs and the case that misled readers."""
        if not self.winners or not self.matched_pairs:
            return "none"
        return "full" if not self.unmatched_winners else "partial"

    @property
    def is_comparable(self) -> bool:
        """True only when EVERY winner has a matched control.

        Deliberately stricter than before. Callers that can handle a partial
        cohort should read `comparability` / `matched_pairs`; callers that just
        want a yes/no should get the conservative answer."""
        return self.comparability == "full"

    @property
    def format_mismatched_pairs(self) -> int:
        return sum(1 for c in self.controls if not c.format_matched)

    def as_packet(self) -> dict:
        return {
            "winners": [v.as_row() for v in self.winners],
            "controls": [v.as_row() for v in self.controls],
            "winner_count": len(self.winners),
            "control_count": len(self.controls),
            "is_comparable": self.is_comparable,
            "comparability": self.comparability,
            "control_coverage": round(self.control_coverage, 3),
            "matched_winner_count": len(self.matched_winners),
            "unmatched_winner_ids": [w.video_id for w in self.unmatched_winners],
            "format_mismatched_pairs": self.format_mismatched_pairs,
            "notes": list(self.notes),
            "selection": {
                "ratio_basis": "views_per_day",
                "winner_multiplier": WINNER_MULTIPLIER,
                "control_max_ratio": CONTROL_MAX_RATIO,
                "control_max_days_apart": CONTROL_MAX_DAYS_APART,
                "control_duration_tolerance": CONTROL_DURATION_TOLERANCE,
                "min_settled_age_days": MIN_SETTLED_AGE_DAYS,
                "max_winners_per_channel": MAX_WINNERS_PER_CHANNEL,
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


def age_days(published_at: str, now: datetime) -> float | None:
    """Age in days, or None when the timestamp cannot be trusted.

    None is not zero. Returning 0.0 for an unparseable date is what let a video
    with no usable timestamp be scored as if it had been published today."""
    stamp = _parse_ts(published_at)
    if stamp is None:
        return None
    return max((now - stamp).total_seconds() / 86400.0, 0.0)


def _age_days(published_at: str, now: datetime) -> float:
    """Back-compatible shim: unknown age reads as 0.0."""
    return age_days(published_at, now) or 0.0


def views_per_day(video: dict, now: datetime) -> float:
    """Age-normalised velocity.

    A 2-year-old video with 1M views and a 3-week-old video with 900k are not
    the same evidence; absolute views said they were."""
    age = _age_days(video.get("published_at", ""), now)
    views = float(video.get("views", 0) or 0)
    # Floor at one day so a video published hours ago cannot produce a spike
    # that dwarfs every established video in the cohort. Selection additionally
    # refuses to consider anything younger than MIN_SETTLED_AGE_DAYS.
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


def _settled(videos: list[dict], now: datetime, min_age: float) -> tuple[list[dict], int, int]:
    """Videos old enough for a per-day rate to mean anything.

    Returns (settled, dropped_too_new, dropped_no_timestamp)."""
    settled: list[dict] = []
    too_new = undated = 0
    for video in videos:
        age = age_days(video.get("published_at", ""), now)
        if age is None:
            undated += 1
            continue
        if age < min_age:
            too_new += 1
            continue
        settled.append(video)
    return settled, too_new, undated


def _row(
    video: dict,
    *,
    channel_id: str,
    role: str,
    ratio: float,
    now: datetime,
    matched_to: str = "",
    format_matched: bool = True,
) -> CohortVideo:
    title = video.get("title", "")
    return CohortVideo(
        video_id=video["video_id"],
        channel_id=channel_id,
        title=title,
        role=role,
        views=int(video.get("views", 0) or 0),
        views_per_day=views_per_day(video, now),
        outlier_ratio=ratio,
        duration_minutes=float(video.get("duration_minutes", 0) or 0),
        published_at=video.get("published_at", ""),
        engagement_rate=float(video.get("engagement_rate", 0) or 0),
        matched_to=matched_to,
        title_patterns=tuple(classify_title(title)),
        format_matched=format_matched,
    )


def select_cohort(
    videos_by_channel: dict[str, list[dict]],
    *,
    max_winners: int = 12,
    max_winners_per_channel: int = MAX_WINNERS_PER_CHANNEL,
    controls_per_winner: int = 1,
    min_settled_age_days: float = MIN_SETTLED_AGE_DAYS,
    now: datetime | None = None,
) -> Cohort:
    """Build a winner + matched-control cohort from raw per-channel video dicts.

    Each video dict needs: video_id, title, views, duration_minutes,
    published_at; engagement_rate is optional. Channels with fewer than three
    settled videos are skipped — a median over one or two videos defines
    nothing.

    Winners are chosen by VELOCITY (views/day) against the channel's median
    velocity, capped at `max_winners_per_channel` per channel so no single
    channel's house style can become "the playbook".
    """
    now = now or datetime.now(timezone.utc)
    cohort = Cohort()
    # (ratio, winner_row, sibling_videos, median_velocity)
    ranked: list[tuple[float, CohortVideo, list[dict], float]] = []

    for channel_id, videos in sorted(videos_by_channel.items()):
        with_ids = [v for v in videos if v.get("video_id")]
        usable, too_new, undated = _settled(with_ids, now, min_settled_age_days)
        if undated:
            cohort.notes.append(
                f"{channel_id}: {undated} video(s) dropped — publish timestamp "
                "missing or unparseable, so views/day cannot be computed"
            )
        if too_new:
            cohort.notes.append(
                f"{channel_id}: {too_new} video(s) dropped — younger than "
                f"{min_settled_age_days:g}d, a per-day rate that early is surge "
                "noise, not evidence"
            )
        if len(usable) < 3:
            cohort.notes.append(
                f"{channel_id}: skipped, only {len(usable)} settled video(s) — a "
                "channel median needs at least 3"
            )
            continue

        velocities = {v["video_id"]: views_per_day(v, now) for v in usable}
        median_velocity = statistics.median(velocities.values())
        if median_velocity <= 0:
            cohort.notes.append(f"{channel_id}: skipped, median views/day is zero")
            continue

        channel_winners: list[tuple[float, CohortVideo]] = []
        for video in usable:
            ratio = velocities[video["video_id"]] / median_velocity
            if ratio < WINNER_MULTIPLIER:
                continue
            channel_winners.append(
                (ratio, _row(video, channel_id=channel_id, role="winner",
                             ratio=ratio, now=now))
            )

        channel_winners.sort(key=lambda item: item[0], reverse=True)
        if len(channel_winners) > max_winners_per_channel:
            cohort.notes.append(
                f"{channel_id}: {len(channel_winners)} winners found; kept the "
                f"{max_winners_per_channel} strongest — one channel supplying the "
                "whole cohort would make its house style look like the playbook"
            )
            channel_winners = channel_winners[:max_winners_per_channel]

        for ratio, winner in channel_winners:
            ranked.append((ratio, winner, usable, median_velocity))

    # Strongest breakouts first — velocity outlier ratio, NOT absolute views.
    ranked.sort(key=lambda item: item[0], reverse=True)
    if len(ranked) > max_winners:
        cohort.notes.append(
            f"{len(ranked)} winners found; kept the {max_winners} strongest by "
            "velocity outlier ratio"
        )
        ranked = ranked[:max_winners]

    used_controls: set[str] = set()
    for _ratio, winner, siblings, median_velocity in ranked:
        cohort.winners.append(winner)
        # (format_penalty, days_apart, control_row)
        candidates: list[tuple[int, float, CohortVideo]] = []
        for sibling in siblings:
            sid = sibling.get("video_id", "")
            if sid == winner.video_id or sid in used_controls:
                continue
            sibling_ratio = views_per_day(sibling, now) / median_velocity
            if sibling_ratio > CONTROL_MAX_RATIO:
                continue  # a near-breakout is not an ordinary video
            gap = _days_apart(winner.published_at, sibling.get("published_at", ""))
            if gap > CONTROL_MAX_DAYS_APART:
                continue
            sibling_minutes = float(sibling.get("duration_minutes", 0) or 0)
            if not _duration_matches(winner.duration_minutes, sibling_minutes):
                continue
            matched = formats_match(winner.title, sibling.get("title", ""))
            candidates.append((
                0 if matched else 1,
                gap,
                _row(sibling, channel_id=winner.channel_id, role="control",
                     ratio=sibling_ratio, now=now, matched_to=winner.video_id,
                     format_matched=matched),
            ))
        # Same title shape first, then closest in publish time: a same-format
        # control removes a confound, and publish proximity shares the most
        # channel context.
        candidates.sort(key=lambda item: (item[0], item[1]))
        picked = candidates[:controls_per_winner]
        if not picked:
            cohort.notes.append(
                f"{winner.video_id}: no matched control (same channel, "
                f"<={CONTROL_MAX_DAYS_APART}d apart, similar length, not itself a "
                "breakout) — winner-only evidence"
            )
        for penalty, _gap, control in picked:
            used_controls.add(control.video_id)
            cohort.controls.append(control)
            if penalty:
                cohort.notes.append(
                    f"{winner.video_id}: control {control.video_id} has a "
                    f"different title format ({'/'.join(control.title_patterns)} "
                    f"vs {'/'.join(winner.title_patterns)}) — format is not "
                    "controlled for in this pair"
                )

    if not cohort.winners:
        cohort.notes.append("no winner cleared the outlier threshold")
    elif cohort.comparability == "partial":
        cohort.notes.append(
            f"partial control coverage: {len(cohort.matched_winners)} of "
            f"{len(cohort.winners)} winners have a control. Contrast claims are "
            "valid only over the matched pairs"
        )
    return cohort
