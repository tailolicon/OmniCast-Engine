"""Shadow-mode calibration for topic scoring v1 → v2.

WHY THIS EXISTS

v2 removed a real double-count: `outlier_ratio` fed both `trend_momentum` and
`gap_score`, so one measurement could supply 65 of 100 points. But removing it
moves the approve/review boundary, and by an amount that depends on the
competitor channel's size — at outlier ratio 8 the same topic lands anywhere
from 59.5 to 75.5. Picking a new threshold by intuition would just replace one
unexamined number with another.

So v2 runs in shadow (see `settings.omnicast_scoring_mode`) and this module
turns the collected rows into the two things a go/no-go decision actually needs:

  1. ROUTING IMPACT — how many topics would change lane, and in which direction.
     "The average score dropped 8 points" is not decision-grade; "31% of
     auto-approves become reviews" is.

  2. DECOUPLING PROOF — the Pearson correlation between `trend_momentum` and
     `gap_score`. This is the check that the original fix actually worked, and
     no unit test can perform it, because unit tests hold outlier_ratio fixed.

On (2): v2 stopped reading `outlier_ratio` in gap, but gap now rewards a small
`channel_median_views` (+8) — and a small channel is also where a high outlier
ratio is easiest to achieve, since the denominator is small and the variance
large. If both dimensions still load on the same latent factor (channel size),
the decoupling is nominal and the double-count came back through the side door.
`corr_v2` near zero is the evidence that it did not; a `corr_v2` close to
`corr_v1` means it did.

Everything here is a pure function over plain rows — no DB, no settings, no
network. Feed it `shadow_row(scored)` output collected from a real discovery run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Correlation above this between trend and gap means the two dimensions are
# still measuring the same underlying thing. 0.35 is a judgement call, stated
# openly so it can be argued with rather than buried in an if-statement.
DECOUPLING_CORR_LIMIT = 0.35
# Eta is on [0, 1] and, unlike Pearson, has no sign — it answers "does gap move
# with trend at all, in any shape". Set a little looser than the linear limit
# because binning always picks up some noise.
DECOUPLING_ETA_LIMIT = 0.45
# Below this many rows, none of the numbers below mean anything.
MIN_ROWS_FOR_VERDICT = 50
# A routing shift this large is a re-plan of the content calendar, not a tweak.
# It does not block v2 forever — it blocks promoting it without a human looking.
MAX_LANE_CHURN_PCT = 25.0


def action_of(total: float) -> str:
    """The routing lane a total score lands in. Thresholds match TopicScorer."""
    if total >= 70:
        return "approve"
    if total >= 50:
        return "review"
    return "discard"


def shadow_row(scored) -> dict:
    """Flatten one ScoredTopic into a calibration row.

    Kept separate from `ScoredTopic` so harvesting never depends on pydantic
    versions or on the topic still being in memory — write these to JSONL from a
    discovery run and calibrate later."""
    return {
        "title": getattr(scored.raw, "title", ""),
        "source": str(getattr(scored.raw, "source", "")),
        "market": str(getattr(scored.raw, "market", "")),
        "trend_momentum": float(scored.trend_momentum),
        "gap_score": float(scored.gap_score),
        "gap_score_v1": float(getattr(scored, "gap_score_v1", 0.0)),
        "rpm_potential": float(scored.rpm_potential),
        "novelty_score": float(scored.novelty_score),
        "stack_fit": float(getattr(scored, "stack_fit", 0.0)),
        "audience_fit": float(getattr(scored, "audience_fit", 0.0)),
        "repeatability": float(getattr(scored, "repeatability", 0.0)),
        "risk_penalty": float(getattr(scored, "risk_penalty", 0.0)),
        # Which composition of v2 produced total_v2. Without it, rows from two
        # revisions look identical in the corpus and calibration would fit a
        # blend of two scorers, neither of which ever ran.
        "v2_revision": int(getattr(scored, "scoring_v2_revision", 1)),
        "total_v1": float(getattr(scored, "total_score_v1", 0.0)),
        "total_v2": float(getattr(scored, "total_score_v2", 0.0)),
        "outlier_ratio": float((getattr(scored.raw, "raw_metrics", {}) or {})
                               .get("outlier_ratio", 0.0) or 0.0),
        "channel_median_views": float((getattr(scored.raw, "raw_metrics", {}) or {})
                                      .get("channel_median_views", 0.0) or 0.0),
    }


def _num(value) -> float | None:
    """Coerce a harvested field to a float, or None if it is not a number.

    Harvest files are JSONL written by long-running jobs: truncated lines,
    `"n/a"` and nulls are normal. Raising on them turned a malformed line into
    a crashed report instead of a counted, declared drop."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def correlation_ratio(xs: list[float], ys: list[float], bins: int = 5) -> float | None:
    """Eta: the share of `ys`' variance explained by `xs`, at group resolution.

    Pearson only sees straight lines, and gap is a step function of channel
    size — a deterministic U-shaped dependence scored r = -0.03, comfortably
    "decoupled". Eta groups the x axis and asks whether y's mean moves between
    groups, which any functional relationship does.

    Grouping went wrong twice before landing here, in opposite directions:

      * BY RANK — split tied x values across groups and credited their
        y-variance to x. A corpus where trend saturates at 30.0 for 40 rows
        scored eta 1.0 against a true 0.018, and shuffling the same rows
        changed the answer.
      * BY EQUAL-WIDTH VALUE — collapsed under a skewed x. One outlier at 900
        put the other 59 rows in a single bin, so a gap that really was a
        function of trend scored 0.09, i.e. "decoupled". A false green light.

    So: points are grouped by EXACT x value (ties always travel together), then
    consecutive distinct values are merged until each group holds roughly n/bins
    points. That is tie-safe, order-independent and unaffected by outliers.

    Returns None when the question is unanswerable — too few points, constant x
    (explains nothing by definition), constant y, or every group a singleton.
    With one point per group eta is 1.0 by construction, which is an artifact of
    the method, not a finding: this is a screen, not a proof."""
    n = len(xs)
    if n < 10 or n != len(ys) or bins < 2:
        return None
    grand_mean = sum(ys) / n
    total_ss = sum((y - grand_mean) ** 2 for y in ys)
    if total_ss == 0:
        return None  # y never varied

    by_value: dict[float, list[float]] = {}
    for x, y in zip(xs, ys, strict=True):
        by_value.setdefault(x, []).append(y)
    if len(by_value) < 2:
        return None  # x never varied

    target = n / bins
    groups: list[list[float]] = []
    current: list[float] = []
    for value in sorted(by_value):
        current.extend(by_value[value])
        if len(current) >= target:
            groups.append(current)
            current = []
    if current:
        if groups:
            groups[-1].extend(current)
        else:
            groups.append(current)
    if len(groups) < 2 or max(len(g) for g in groups) < 2:
        return None

    between_ss = sum(
        len(g) * (sum(g) / len(g) - grand_mean) ** 2 for g in groups
    )
    return round(math.sqrt(min(between_ss / total_ss, 1.0)), 4)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson r. None when undefined (too few points, or a constant series)."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denom = math.sqrt(sum(d * d for d in dx)) * math.sqrt(sum(d * d for d in dy))
    if denom == 0:
        return None  # a dimension that never varies cannot correlate with anything
    return round(sum(a * b for a, b in zip(dx, dy, strict=True)) / denom, 4)


# The double-count only ever existed on this source: `outlier_ratio` fed both
# dimensions there. Everywhere else gap is a per-source constant, and pooling
# those constants in drags the correlation towards zero — i.e. the check would
# pass by dilution, on a corpus dominated by RSS/Reddit rows.
DOUBLE_COUNT_SOURCE_HINT = "youtube_competitor"


@dataclass
class CalibrationReport:
    rows: int = 0
    usable_rows: int = 0
    dropped_rows: int = 0
    youtube_rows: int = 0
    # Every v2 revision present in the corpus. More than one means the rows
    # describe different scoring functions.
    v2_revisions: set[int] = field(default_factory=set)
    # lane -> lane -> count, e.g. transitions["approve"]["review"]
    transitions: dict[str, dict[str, int]] = field(default_factory=dict)
    changed_lane: int = 0
    mean_delta: float = 0.0
    median_delta: float = 0.0
    p10_delta: float = 0.0
    p90_delta: float = 0.0
    # Pooled across every source — reported for completeness only.
    corr_trend_gap_v1: float | None = None
    corr_trend_gap_v2: float | None = None
    # Restricted to the source where the double-count actually lived. THIS is
    # the number the verdict is based on.
    corr_trend_gap_v1_youtube: float | None = None
    corr_trend_gap_v2_youtube: float | None = None
    # Shape-agnostic dependence. Pearson cannot see a step or U-shaped
    # relationship, and gap is a step function of channel size.
    eta_trend_gap_v2_youtube: float | None = None
    youtube_changed_lane: int = 0
    # Rows carrying a human label or a published outcome.
    labelled_rows: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def changed_lane_pct(self) -> float:
        return (round(100.0 * self.changed_lane / self.usable_rows, 1)
                if self.usable_rows else 0.0)

    @property
    def youtube_changed_lane_pct(self) -> float:
        """Churn on the source that actually moved. The pooled figure hides it:
        50 YouTube rows at 64% churn under 200 unchanged RSS rows pooled to
        12.8%, which reads as calm."""
        return (round(100.0 * self.youtube_changed_lane / self.youtube_rows, 1)
                if self.youtube_rows else 0.0)

    @property
    def decoupled(self) -> bool | None:
        """Did v2 actually separate demand from saturation?

        Judged on YouTube rows alone, because that is the only source where the
        two dimensions were ever coupled. None = not enough evidence to say,
        which is a distinct answer from False; conflating them is how an
        unmeasured change gets shipped."""
        if self.youtube_rows < MIN_ROWS_FOR_VERDICT:
            return None
        if self.corr_trend_gap_v2_youtube is None:
            return None
        if abs(self.corr_trend_gap_v2_youtube) > DECOUPLING_CORR_LIMIT:
            return False
        if self.eta_trend_gap_v2_youtube is None:
            return None
        # Eta catches the dependence Pearson is blind to.
        return self.eta_trend_gap_v2_youtube <= DECOUPLING_ETA_LIMIT

    @property
    def coupling_reduced(self) -> bool | None:
        """Did v2's coupling actually come DOWN from v1's on the same corpus?

        Separate from `decoupled`, which is a statement about v2 alone. None
        when v1's gap never varied in this sample (e.g. every row in one ratio
        tier), which is a missing before-picture rather than a bad result."""
        if self.corr_trend_gap_v1_youtube is None or self.corr_trend_gap_v2_youtube is None:
            return None
        return abs(self.corr_trend_gap_v2_youtube) < abs(self.corr_trend_gap_v1_youtube)

    @property
    def single_revision(self) -> bool:
        """Whether every row was scored by the SAME composition of v2.

        A corpus spanning two revisions describes two different functions. Its
        deltas, its lane churn and its correlations are all averages over a
        scorer that never existed, and the verdict drawn from them would be
        about nothing. Mixed corpora must be re-harvested, not blended."""
        return len(self.v2_revisions) <= 1

    @property
    def migration_is_stable(self) -> bool:
        """Whether swapping v1 for v2 is a SAFE migration — nothing more.

        Requires: enough YouTube rows, a proven drop in coupling, and a routing
        shift small enough that promoting v2 is not a blind re-plan of the
        content calendar.

        This answers "does the change behave predictably", NOT "does v2 pick
        better topics". Those are different questions and only one of them is
        measurable from scores alone — see `ready_to_promote`."""
        return (
            self.single_revision
            and bool(self.decoupled)
            # Measurable and worse than v1 is a hard no. Unmeasurable (None) is
            # not, or a corpus where every row sits in one v1 tier could never
            # promote anything.
            and self.coupling_reduced is not False
            and self.usable_rows >= MIN_ROWS_FOR_VERDICT
            and self.dropped_rows == 0
            and self.changed_lane_pct < MAX_LANE_CHURN_PCT
            and self.youtube_changed_lane_pct < MAX_LANE_CHURN_PCT
        )

    @property
    def has_quality_evidence(self) -> bool:
        """Whether any row carries an outcome or a human label.

        A corpus of pure scores cannot show that v2 chooses better topics — it
        can only show the two generations disagree. `labelled` (human verdict)
        or `outcome` (what the published video actually did) is the only thing
        that turns a migration check into a quality one."""
        return self.labelled_rows > 0

    @property
    def ready_to_promote(self) -> bool:
        """Whether v2 may take over `auto_approved`.

        Deliberately stricter than `migration_is_stable`: a stable migration to
        a WORSE scorer is still a downgrade. The earlier version of this
        property was the stability check under a name that read like a quality
        verdict, so a corpus with no quality signal at all could return True."""
        return self.migration_is_stable and self.has_quality_evidence

    def as_dict(self) -> dict:
        return {
            "rows": self.rows,
            "transitions": self.transitions,
            "changed_lane": self.changed_lane,
            "changed_lane_pct": self.changed_lane_pct,
            "mean_delta": self.mean_delta,
            "median_delta": self.median_delta,
            "p10_delta": self.p10_delta,
            "p90_delta": self.p90_delta,
            "usable_rows": self.usable_rows,
            "dropped_rows": self.dropped_rows,
            "youtube_rows": self.youtube_rows,
            "corr_trend_gap_v1": self.corr_trend_gap_v1,
            "corr_trend_gap_v2": self.corr_trend_gap_v2,
            "corr_trend_gap_v1_youtube": self.corr_trend_gap_v1_youtube,
            "corr_trend_gap_v2_youtube": self.corr_trend_gap_v2_youtube,
            "coupling_reduced": self.coupling_reduced,
            "v2_revisions": sorted(self.v2_revisions),
            "single_revision": self.single_revision,
            "migration_is_stable": self.migration_is_stable,
            "has_quality_evidence": self.has_quality_evidence,
            "labelled_rows": self.labelled_rows,
            "eta_trend_gap_v2_youtube": self.eta_trend_gap_v2_youtube,
            "youtube_changed_lane_pct": self.youtube_changed_lane_pct,
            "decoupling_corr_limit": DECOUPLING_CORR_LIMIT,
            "decoupled": self.decoupled,
            "ready_to_promote": self.ready_to_promote,
            "notes": list(self.notes),
        }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * pct
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return round(ordered[int(position)], 2)
    weight = position - low
    return round(ordered[low] * (1 - weight) + ordered[high] * weight, 2)


def summarize(rows: list[dict]) -> CalibrationReport:
    """Turn collected shadow rows into a go/no-go report."""
    report = CalibrationReport(rows=len(rows))
    if not rows:
        report.notes.append("no rows: run discovery in shadow mode first")
        return report

    deltas: list[float] = []
    trends: list[float] = []
    gaps_v1: list[float] = []
    gaps_v2: list[float] = []
    yt_trends: list[float] = []
    yt_gaps_v1: list[float] = []
    yt_gaps_v2: list[float] = []

    for row in rows:
        # A row without both totals cannot be compared. Defaulting the missing
        # side to 0.0 used to turn a corpus of scoreless rows into
        # "0% changed lane, ready to promote" — a green light built from
        # nothing at all.
        v1 = _num(row.get("total_v1"))
        v2 = _num(row.get("total_v2"))
        if v1 is None or v2 is None:
            report.dropped_rows += 1
            continue
        # ABSENT = revision 1: rows harvested before the field existed were all
        # written by the original v2 composition. PRESENT BUT UNPARSEABLE is a
        # different thing entirely and must not collapse into the same default —
        # a truncated `v2_revision` on precisely the revision-2 rows would turn
        # "re-harvest under one revision, do NOT promote" into a green light.
        # Every other unparseable field costs the row; so does this one. Checked
        # BEFORE the row is counted, so the rollback dance is unnecessary here.
        if "v2_revision" in row:
            revision = _num(row.get("v2_revision"))
            if revision is None:
                report.dropped_rows += 1
                continue
            report.v2_revisions.add(int(revision))
        else:
            report.v2_revisions.add(1)

        report.usable_rows += 1
        deltas.append(v2 - v1)

        from_lane, to_lane = action_of(v1), action_of(v2)
        report.transitions.setdefault(from_lane, {})
        report.transitions[from_lane][to_lane] = \
            report.transitions[from_lane].get(to_lane, 0) + 1
        if from_lane != to_lane:
            report.changed_lane += 1

        trend = _num(row.get("trend_momentum"))
        gap_v1 = _num(row.get("gap_score_v1"))
        gap_v2 = _num(row.get("gap_score"))
        if trend is None or gap_v1 is None or gap_v2 is None:
            report.dropped_rows += 1
            report.usable_rows -= 1
            deltas.pop()
            report.transitions[from_lane][to_lane] -= 1
            if from_lane != to_lane:
                report.changed_lane -= 1
            continue
        trends.append(trend)
        gaps_v1.append(gap_v1)
        gaps_v2.append(gap_v2)

        if row.get("labelled") is not None or row.get("outcome") is not None:
            report.labelled_rows += 1

        if DOUBLE_COUNT_SOURCE_HINT in str(row.get("source", "")).lower():
            report.youtube_rows += 1
            yt_trends.append(trend)
            yt_gaps_v1.append(gap_v1)
            yt_gaps_v2.append(gap_v2)
            if from_lane != to_lane:
                report.youtube_changed_lane += 1

    if not report.usable_rows:
        report.notes.append(
            f"all {report.rows} rows lacked total_v1/total_v2 — nothing to compare"
        )
        return report

    report.mean_delta = round(sum(deltas) / len(deltas), 2)
    report.median_delta = _percentile(deltas, 0.5)
    report.p10_delta = _percentile(deltas, 0.10)
    report.p90_delta = _percentile(deltas, 0.90)
    report.corr_trend_gap_v1 = pearson(trends, gaps_v1)
    report.corr_trend_gap_v2 = pearson(trends, gaps_v2)
    report.corr_trend_gap_v1_youtube = pearson(yt_trends, yt_gaps_v1)
    report.corr_trend_gap_v2_youtube = pearson(yt_trends, yt_gaps_v2)
    report.eta_trend_gap_v2_youtube = correlation_ratio(yt_trends, yt_gaps_v2)

    if report.dropped_rows:
        report.notes.append(
            f"{report.dropped_rows} of {report.rows} rows dropped for missing "
            "total_v1/total_v2 — fix the harvest before trusting this report"
        )
    if report.usable_rows < MIN_ROWS_FOR_VERDICT:
        report.notes.append(
            f"only {report.usable_rows} usable rows — need {MIN_ROWS_FOR_VERDICT}"
        )
    if not report.single_revision:
        report.notes.append(
            f"corpus spans v2 revisions {sorted(report.v2_revisions)} — these are "
            "different scoring functions, so every statistic here describes a "
            "blend that never ran. Re-harvest under one revision; do NOT promote"
        )
    if report.youtube_rows < MIN_ROWS_FOR_VERDICT:
        report.notes.append(
            f"only {report.youtube_rows} youtube_competitor rows — the decoupling "
            f"verdict needs {MIN_ROWS_FOR_VERDICT} of them, because that is the "
            "only source where the double-count existed"
        )
    if report.corr_trend_gap_v2_youtube is None and report.youtube_rows:
        report.notes.append(
            "youtube correlation undefined: trend or gap never varied in that subset"
        )
    elif (report.corr_trend_gap_v2_youtube is not None
          and abs(report.corr_trend_gap_v2_youtube) > DECOUPLING_CORR_LIMIT):
        report.notes.append(
            f"trend and gap still correlate at r={report.corr_trend_gap_v2_youtube} "
            f"on youtube rows (limit {DECOUPLING_CORR_LIMIT}) — the double-count "
            "likely returned through channel size; do NOT promote v2"
        )
    if report.coupling_reduced is False:
        report.notes.append(
            f"coupling did not fall: v1 r={report.corr_trend_gap_v1_youtube}, "
            f"v2 r={report.corr_trend_gap_v2_youtube} — v2 is not an improvement "
            "on the axis it was built to fix"
        )
    if (report.youtube_rows >= MIN_ROWS_FOR_VERDICT
            and report.eta_trend_gap_v2_youtube is not None
            and report.eta_trend_gap_v2_youtube > DECOUPLING_ETA_LIMIT
            and abs(report.corr_trend_gap_v2_youtube or 0.0) <= DECOUPLING_CORR_LIMIT):
        report.notes.append(
            f"gap tracks trend non-linearly on youtube rows "
            f"(eta={report.eta_trend_gap_v2_youtube}, limit {DECOUPLING_ETA_LIMIT}) "
            "even though the linear correlation looks clean — the dependence is "
            "step-shaped, via channel size"
        )
    if report.migration_is_stable and not report.has_quality_evidence:
        report.notes.append(
            "migration looks stable, but NO row carries a label or an outcome — "
            "this corpus can show v2 behaves predictably, not that it chooses "
            "better topics. Promotion stays blocked until quality evidence exists"
        )
    for label, pct in (("overall", report.changed_lane_pct),
                       ("youtube_competitor", report.youtube_changed_lane_pct)):
        if pct >= MAX_LANE_CHURN_PCT:
            report.notes.append(
                f"{pct}% of {label} topics change lane — promoting v2 would "
                "visibly re-plan what gets produced; needs a human decision"
            )
    return report
