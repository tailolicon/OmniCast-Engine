"""Machine gate between learned competitor playbooks and the writer.

WHY THIS EXISTS

`competitor_intel` stamps `[UNCONTROLLED — ...]` on any playbook learned without
a matched control group. That stamp is TEXT. The writer was pasting the playbook
into the prompt under the heading "mirror these winning patterns" — so an
uncontrolled playbook, a playbook from a run whose transcripts all failed, and a
verified one all reached the model the same way, differing only by a sentence the
model was free to ignore.

Worse, the whole lookup sat inside `try: ... except Exception: pass`. A corrupt
row, a missing DB, a schema drift — every one of them became "no problem here",
with nothing logged. Any gate placed inside that block would have failed open in
exactly the situations it existed to catch.

So the decision is made here, once, as data:

    decision = evaluate(intel, ...)
    if decision.usable: <inject>
    else:               <skip, log decision.status, honour the channel policy>

`status` is a closed set, not a free-text note, so callers can branch on it and
metrics can count it. `usable` is the single boolean the writer needs, and it is
False unless the playbook is both controlled and fresh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()

# Marker written by competitor_intel when no control group could be matched.
UNCONTROLLED_MARKER = "[UNCONTROLLED"
# A playbook older than this describes an algorithm era that has moved on.
DEFAULT_MAX_AGE_DAYS = 90

# Closed set of outcomes. Anything not in here is a bug, not a new case.
STATUS_OK = "ok"
STATUS_MISSING = "missing"              # nothing learned yet for this scope
STATUS_UNCONTROLLED = "uncontrolled"    # learned, but with no control group
STATUS_STALE = "stale"                  # learned too long ago to trust
STATUS_ERROR = "error"                  # row exists but could not be read
STATUS_LEGACY = "legacy"                # row predates per-artifact provenance


@dataclass(frozen=True)
class IntelDecision:
    status: str
    playbook: str = ""
    reason: str = ""
    research_run_id: str = ""
    age_days: float | None = None
    details: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.status == STATUS_OK and bool(self.playbook.strip())

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "usable": self.usable,
            "reason": self.reason,
            "research_run_id": self.research_run_id,
            "age_days": self.age_days,
            **self.details,
        }


def _parse_meta(raw: str) -> tuple[dict, str]:
    if not raw:
        return {}, ""
    try:
        parsed = json.loads(raw)
        return (parsed, "") if isinstance(parsed, dict) else ({}, "cohort_meta is not an object")
    except Exception as exc:
        return {}, f"cohort_meta unreadable: {type(exc).__name__}"


def _age_days(updated_at, now: datetime) -> float | None:
    """Age in days, or None when the timestamp cannot be read.

    Callers must treat None as UNKNOWN, never as fresh. Catches broadly on
    purpose: a datetime object, an ORM value, or a non-ISO string all used to
    escape as a TypeError out of `evaluate` and past the very caller this
    module exists to make explicit."""
    if not updated_at:
        return None
    if isinstance(updated_at, datetime):
        stamp = updated_at
    else:
        try:
            stamp = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        except Exception:
            return None
    if not stamp.tzinfo:
        stamp = stamp.replace(tzinfo=timezone.utc)
    try:
        days = (now - stamp).total_seconds() / 86400.0
    except Exception:
        return None
    if days < -1.0:
        # A timestamp in the future is a broken clock or a bad write, not a
        # very fresh artifact. `max(..., 0.0)` made "2099-01-01" permanently
        # fresh.
        return None
    return max(days, 0.0)


def _is_comparable(value) -> bool | None:
    """Tri-state read of a comparability flag.

    `value is False` was an identity test: JSON `0`, `"false"` and `"no"` all
    slipped through as "not disproven" and the playbook was accepted."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # Only the two flag-shaped numbers are a flag. A count accidentally
        # written into this field (2, -1) must not read as "controlled".
        if value in (0, 1):
            return bool(value)
        return None
    text = str(value).strip().lower()
    if text in {"false", "0", "no", "n"}:
        return False
    if text in {"true", "1", "yes", "y"}:
        return True
    return None


def evaluate(
    intel,
    *,
    artifact: str = "script_playbook",
    max_age_days: int | None = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> IntelDecision:
    """Decide whether one learned artifact may be fed to a generator.

    `intel` is a vault CompetitorIntel row (or None). Pure — no DB, no clock
    unless you let it default."""
    now = now or datetime.now(timezone.utc)
    if max_age_days is None:
        max_age_days = DEFAULT_MAX_AGE_DAYS

    if intel is None:
        return IntelDecision(STATUS_MISSING, reason="no competitor intel row for this scope")

    try:
        playbook = (getattr(intel, artifact, "") or "").strip()
    except Exception as exc:
        # A lazy-loading ORM attribute can raise on access; that is a read
        # failure, not an absent playbook.
        return IntelDecision(STATUS_ERROR,
                             reason=f"reading {artifact} failed: {type(exc).__name__}")
    meta, meta_error = _parse_meta(getattr(intel, "cohort_meta", "") or "")

    if meta_error:
        # A row we cannot read is not a row we may act on.
        return IntelDecision(STATUS_ERROR, reason=meta_error)

    # PER-ARTIFACT provenance wins over the row's, and it wins AS A UNIT. A run
    # that failed to produce a script playbook carries the previous one forward;
    # judging that older text by this run's cohort would hand a stale artifact
    # fresh credentials. Mixing the two — artifact run id, row timestamp — does
    # the same thing one field at a time, which is how a 400-day-old playbook
    # read as fresh.
    artifacts = meta.get("artifacts")
    if artifacts is None:
        # A row written before per-artifact provenance existed. By construction
        # those rows are "possibly-old artifact + newest run's metadata" — the
        # exact shape whose laundering this module exists to stop — and nothing
        # in them distinguishes a carried-forward playbook from a fresh one. It
        # cannot be verified, so it is not used. Re-running the learner writes a
        # row that can be.
        return IntelDecision(
            STATUS_LEGACY, playbook=playbook,
            reason="row predates per-artifact provenance — cannot tell which "
                   "research run produced this text; re-learn to use it",
        )
    if not isinstance(artifacts, dict):
        return IntelDecision(
            STATUS_ERROR,
            reason=f"cohort_meta.artifacts is {type(artifacts).__name__}, not an object")
    if artifact not in artifacts:
        return IntelDecision(
            STATUS_LEGACY, playbook=playbook,
            reason=f"no provenance recorded for {artifact} in this row")
    source_meta = artifacts.get(artifact)
    if not isinstance(source_meta, dict):
        # A non-dict record used to raise AttributeError straight out of
        # evaluate(), past resolve_for_writer, and out of the writer's prompt
        # builder — the one path this module promised to make explicit.
        return IntelDecision(
            STATUS_ERROR,
            reason=f"provenance for {artifact} is "
                   f"{type(source_meta).__name__}, not an object")

    run_id = str(source_meta.get("research_run_id", "") or "").strip()
    if not run_id:
        # The invariant this module exists to hold is "every artifact is
        # traceable to the research run that produced it". A record with a
        # timestamp and is_comparable but no run id satisfied every other check
        # and came back usable — provenance you cannot follow is not provenance.
        return IntelDecision(
            STATUS_LEGACY, playbook=playbook,
            reason=f"provenance for {artifact} carries no research_run_id — "
                   "the artifact cannot be traced to a run")
    age = _age_days(source_meta.get("generated_at"), now)
    comparable = _is_comparable(source_meta.get("is_comparable"))
    artifact_meta = source_meta

    if not playbook:
        return IntelDecision(STATUS_MISSING, reason=f"{artifact} is empty",
                             research_run_id=run_id, age_days=age)

    if playbook.startswith(UNCONTROLLED_MARKER) or comparable is False:
        return IntelDecision(
            STATUS_UNCONTROLLED,
            playbook=playbook,
            reason="learned without a matched control group — patterns are not "
                   "verified to separate winners from the channel's usual output",
            research_run_id=run_id,
            age_days=age,
            details={"winner_count": artifact_meta.get("winner_count",
                                                       meta.get("winner_count")),
                     "control_count": artifact_meta.get("control_count",
                                                        meta.get("control_count"))},
        )

    if age is None:
        # Unknown age is not fresh. An artifact whose provenance carries no
        # readable timestamp cannot be shown to be current, and "cannot be shown
        # to be current" is exactly what the stale lane is for.
        return IntelDecision(
            STATUS_STALE, playbook=playbook,
            reason="no readable timestamp on this artifact — age unknown, so it "
                   "cannot be shown to be current",
            research_run_id=run_id,
        )

    if age > max_age_days:
        return IntelDecision(
            STATUS_STALE, playbook=playbook,
            reason=f"learned {age:.0f} days ago (limit {max_age_days})",
            research_run_id=run_id, age_days=age,
        )

    if comparable is None:
        # Nothing recorded whether a control group existed. Unverifiable is not
        # verified — the row predates provenance, or the run never wrote it.
        return IntelDecision(
            STATUS_UNCONTROLLED, playbook=playbook,
            reason="no comparability recorded for this artifact — cannot show it "
                   "was learned against a control group",
            research_run_id=run_id, age_days=age,
        )

    return IntelDecision(STATUS_OK, playbook=playbook, reason="controlled and fresh",
                         research_run_id=run_id, age_days=age,
                         details={"winner_count": artifact_meta.get(
                                      "winner_count", meta.get("winner_count")),
                                  "control_count": artifact_meta.get(
                                      "control_count", meta.get("control_count"))})


class CompetitorIntelRequired(RuntimeError):
    """Raised when a channel declares it will not ship without verified intel."""


def resolve_for_writer(
    intel,
    *,
    artifact: str = "script_playbook",
    required: bool = False,
    scope: str = "",
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> IntelDecision:
    """Gate + policy in one call, with the logging the old `except: pass` ate.

    Not usable and not required → deterministic skip, logged at warning so it
    shows up in metrics instead of vanishing.
    Not usable and required     → raise; the channel said it would rather stop
    than write from unverified patterns."""
    decision = evaluate(intel, artifact=artifact, max_age_days=max_age_days, now=now)
    if decision.usable:
        logger.info("competitor intel accepted", scope=scope, artifact=artifact,
                    **decision.as_dict())
        return decision

    logger.warning("competitor intel rejected", scope=scope, artifact=artifact,
                   **decision.as_dict())
    if required:
        raise CompetitorIntelRequired(
            f"{scope or 'channel'} requires verified competitor intel for "
            f"{artifact}, but it is {decision.status}: {decision.reason}"
        )
    return decision
