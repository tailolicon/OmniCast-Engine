"""The unified competitor research dossier (strategic review §4.5).

WHY:

OmniCast produced the pieces — cohort, title playbook, thumbnail playbook,
script playbook, production blueprint, schedule, comments — and never assembled
them. Each piece carried its own private caveats in its own format, so the only
place they could be reconciled was a human's head, and the parts that were
measured looked exactly like the parts that were assumed.

THE ONE RULE: EVERY FIELD DECLARES ITS EPISTEMIC STATUS.

    measured  — computed from data we actually fetched, evidence attached
    inferred  — derived from measured data by a rule, evidence attached
    assumed   — a house default; nothing observed
    missing   — we tried and could not get it, with the reason
    withheld  — measurable in principle, but the sample was too thin to claim

`missing` and `withheld` are separate because they call for different actions:
`missing` is a bug or an outage to fix, `withheld` is a sample to grow.

And per §4.7: nothing from the public API may be presented as internal
analytics. Impressions, CTR, retention, average view duration and subscriber
conversion are NOT AVAILABLE for competitors, so they appear here as explicit
`missing` entries rather than being quietly estimated into a number that looks
like YouTube Studio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

MEASURED = "measured"
INFERRED = "inferred"
ASSUMED = "assumed"
MISSING = "missing"
WITHHELD = "withheld"

STATUSES = (MEASURED, INFERRED, ASSUMED, MISSING, WITHHELD)

# Fields the public YouTube API does not expose for other people's channels.
# Listed explicitly so the dossier is honest about the shape of its own hole —
# a reader must not have to notice an absence.
UNAVAILABLE_FOR_COMPETITORS = {
    "impressions": "not exposed by the public API for other channels",
    "click_through_rate": "not exposed by the public API for other channels",
    "retention_curve": "not exposed by the public API for other channels",
    "average_view_duration": "not exposed by the public API for other channels",
    "returning_viewers": "not exposed by the public API for other channels",
    "subscriber_conversion": "not exposed by the public API for other channels",
    "revenue": "not exposed by the public API for other channels",
}


@dataclass
class DossierField:
    name: str
    value: object = None
    status: str = MISSING
    source: str = ""
    evidence: list = field(default_factory=list)
    confidence: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status,
            "source": self.source,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "note": self.note,
        }


@dataclass
class Recommendation:
    """An action, and the dossier fields it is allowed to rest on.

    `supported_by` is validated against the dossier on build: a recommendation
    that cites a field which is missing, assumed or withheld is DOWNGRADED, not
    dropped, and says why. Silently dropping it hides the reason the system
    cannot advise; silently keeping it is advice with no evidence."""

    action: str
    supported_by: list[str] = field(default_factory=list)
    rationale: str = ""
    strength: str = "supported"  # supported | weak | unsupported

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "supported_by": list(self.supported_by),
            "rationale": self.rationale,
            "strength": self.strength,
        }


@dataclass
class Dossier:
    scope: dict = field(default_factory=dict)
    fields: list[DossierField] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    generated_at: str = ""

    def get(self, name: str) -> DossierField | None:
        return next((f for f in self.fields if f.name == name), None)

    def by_status(self, status: str) -> list[str]:
        return [f.name for f in self.fields if f.status == status]

    @property
    def coverage(self) -> float:
        """Share of fields that are measured or inferred from measurement."""
        if not self.fields:
            return 0.0
        solid = sum(1 for f in self.fields if f.status in (MEASURED, INFERRED))
        return round(solid / len(self.fields), 3)

    def as_dict(self) -> dict:
        return {
            "scope": dict(self.scope),
            "generated_at": self.generated_at,
            "coverage": self.coverage,
            "status_summary": {status: self.by_status(status) for status in STATUSES},
            "fields": [f.as_dict() for f in self.fields],
            "recommendations": [r.as_dict() for r in self.recommendations],
        }


def _add(fields: list[DossierField], **kwargs) -> None:
    fields.append(DossierField(**kwargs))


def build_dossier(
    *,
    scope: dict,
    cohort=None,
    playbooks: dict | None = None,
    blueprint: dict | None = None,
    schedule=None,
    comments=None,
    pillar_summary: dict | None = None,
    generated_at: str = "",
) -> Dossier:
    """Assemble one artifact from whatever this research run actually produced.

    Everything is optional. A missing input becomes a `missing` field with a
    reason, never an absent key — an absent key is indistinguishable from a
    field nobody thought of."""
    fields: list[DossierField] = []
    playbooks = playbooks or {}

    # ── cohort ───────────────────────────────────────────────────────────────
    if cohort is not None and getattr(cohort, "winners", None):
        packet = cohort.as_packet()
        _add(fields, name="cohort", value={
            "winners": packet["winner_count"],
            "controls": packet["control_count"],
            "comparability": packet["comparability"],
            "control_coverage": packet["control_coverage"],
        }, status=MEASURED, source="youtube.videos.list + analytics.cohort",
            evidence=[w["video_id"] for w in packet["winners"]],
            confidence=packet["control_coverage"],
            note=("winner/control pairs; contrast claims are valid only over the "
                  f"{packet['matched_winner_count']} matched pairs"))
    else:
        _add(fields, name="cohort", status=MISSING,
             note="no winner cleared the outlier threshold for this competitor set")

    # ── playbooks ────────────────────────────────────────────────────────────
    for name in ("title_playbook", "thumbnail_playbook", "script_playbook"):
        text = (playbooks.get(name) or "").strip()
        if not text:
            _add(fields, name=name, status=MISSING,
                 note="not produced by this run (no usable input or the LLM call failed)")
            continue
        uncontrolled = text.startswith("[UNCONTROLLED")
        partial = text.startswith("[PARTIALLY CONTROLLED")
        _add(fields, name=name, value=text,
             status=INFERRED,
             source="LLM contrast over the cohort",
             confidence=0.3 if uncontrolled else (0.6 if partial else 0.8),
             note=("winner-only: not verified against controls" if uncontrolled
                   else "partially controlled" if partial
                   else "contrasted against matched controls"))

    # ── production blueprint ─────────────────────────────────────────────────
    if blueprint:
        assumed = list(blueprint.get("assumed_fields") or [])
        _add(fields, name="production_blueprint", value=blueprint,
             status=MEASURED if not assumed else INFERRED,
             source="analytics.video_intel over winner transcripts",
             confidence=blueprint.get("confidence"),
             evidence=list(blueprint.get("notes") or [])[:5],
             note=(f"house defaults, not measurements: {', '.join(assumed)}"
                   if assumed else "every field measured"))
    else:
        _add(fields, name="production_blueprint", status=MISSING,
             note="no winner transcript was usable, so nothing could be measured")

    # ── schedule ─────────────────────────────────────────────────────────────
    if schedule is not None and getattr(schedule, "videos_analysed", 0):
        data = schedule.as_dict()
        _add(fields, name="publishing_schedule", value=data, status=MEASURED,
             source="published_at on the scanned competitor videos",
             evidence=data["habitual_slots"],
             note=data["timezone_note"])
        if data["slot_performance"]:
            _add(fields, name="slot_performance", value=data["slot_performance"],
                 status=INFERRED,
                 source="views/day grouped by publish slot",
                 note=data["causal_note"])
        else:
            _add(fields, name="slot_performance", status=WITHHELD,
                 note="no slot held enough videos to rank; the sample cannot "
                      "support a best-time-to-post claim")
    else:
        _add(fields, name="publishing_schedule", status=MISSING,
             note="no video carried a usable publish timestamp")
        _add(fields, name="slot_performance", status=MISSING,
             note="depends on publishing_schedule")

    # ── comments ─────────────────────────────────────────────────────────────
    if comments is not None and getattr(comments, "signals", None):
        data = comments.as_dict()
        _add(fields, name="audience_signals", value=data, status=MEASURED,
             source="youtube.commentThreads.list + analytics.comment_intel",
             evidence=[s["signal"] for s in data["signals"]],
             note=data["sample"]["caveat"])
    elif comments is not None:
        _add(fields, name="audience_signals", value=(comments.as_dict()
                                                     if hasattr(comments, "as_dict")
                                                     else None),
             status=WITHHELD,
             note="comments were fetched but nothing matched a signal phrase; "
                  "silence is not agreement")
    else:
        _add(fields, name="audience_signals", status=MISSING,
             note="comments were not fetched for this run")

    # ── pillars ──────────────────────────────────────────────────────────────
    if pillar_summary:
        classified = pillar_summary.get("classified", 0)
        total = pillar_summary.get("total", 0) or 1
        _add(fields, name="content_pillars", value=pillar_summary,
             status=MEASURED if classified else WITHHELD,
             source="analytics.pillars over the channel's configured pillars",
             confidence=round(classified / total, 3),
             note=("configured pillars matched"
                   if classified else
                   "pillars are configured but no video matched one — the "
                   "keyword lists likely do not describe this competitor set"))
    else:
        _add(fields, name="content_pillars", status=MISSING,
             note="no content pillars are configured for this channel, so intel "
                  "cannot be scoped below the niche level")

    # ── the honest hole (§4.7) ───────────────────────────────────────────────
    for name, reason in UNAVAILABLE_FOR_COMPETITORS.items():
        _add(fields, name=name, status=MISSING, source="youtube public api",
             note=f"{reason} — any figure claiming otherwise is an estimate and "
                  "must be labelled as one")

    dossier = Dossier(
        scope=dict(scope),
        fields=fields,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
    )
    dossier.recommendations = _recommend(dossier)
    return dossier


def _recommend(dossier: Dossier) -> list[Recommendation]:
    """Recommendations that name the field they rest on, then get graded on it.

    Traceability is the requirement from §4.5: a recommendation nobody can trace
    back to evidence is indistinguishable from a guess, and the reader has no
    way to tell which of the two they are looking at."""
    candidates = [
        Recommendation(
            action="Adopt the winner title formulas for this scope",
            supported_by=["title_playbook", "cohort"],
            rationale="Formulas that separated winners from matched controls."),
        Recommendation(
            action="Match the niche's habitual publishing slot",
            supported_by=["publishing_schedule"],
            rationale=("Publishing when the niche publishes is a distribution "
                       "habit, not a causal claim about the hour.")),
        Recommendation(
            action="Answer the audience's unanswered questions in the next script",
            supported_by=["audience_signals"],
            rationale="Questions with likes and no reply are demand nobody served."),
        Recommendation(
            action="Copy the measured hook type and runtime",
            supported_by=["production_blueprint"],
            rationale="Measured from winner transcripts, not from a template."),
    ]

    graded: list[Recommendation] = []
    for rec in candidates:
        statuses = []
        for name in rec.supported_by:
            found = dossier.get(name)
            statuses.append(found.status if found else MISSING)
        if all(s == MEASURED for s in statuses):
            rec.strength = "supported"
        elif any(s in (MISSING,) for s in statuses):
            rec.strength = "unsupported"
            rec.rationale += (
                " [UNSUPPORTED: " +
                ", ".join(f"{n} is {s}" for n, s in zip(rec.supported_by, statuses)
                          if s == MISSING) + "]")
        else:
            rec.strength = "weak"
            rec.rationale += (
                " [WEAK: " +
                ", ".join(f"{n} is {s}" for n, s in zip(rec.supported_by, statuses)
                          if s != MEASURED) + "]")
        graded.append(rec)
    return graded
