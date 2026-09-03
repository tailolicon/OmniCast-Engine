"""The writer no longer trusts a playbook just because a row exists (P0.1).

Before: `writer.py` read `competitor_intel` by niche, pasted `script_playbook`
into the prompt under "mirror these winning patterns", and wrapped the whole
thing in `except Exception: pass`. So three very different situations produced
identical, silent behaviour:

  * a playbook verified against a matched control group,
  * a playbook learned with NO control group (i.e. survivorship bias in prose),
  * a corrupt row, a missing DB, or a schema drift.

`[UNCONTROLLED — ...]` was only a sentence the model could ignore. These tests
pin the machine gate that replaced it, and the policy around it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from omnicast.analytics import intel_gate
from omnicast.analytics.intel_gate import (
    STATUS_ERROR,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_STALE,
    STATUS_UNCONTROLLED,
    CompetitorIntelRequired,
    evaluate,
    resolve_for_writer,
)

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)
import json


class _Row:
    def __init__(self, script_playbook="", cohort_meta="", updated_at=""):
        self.script_playbook = script_playbook
        self.cohort_meta = cohort_meta
        self.updated_at = updated_at or NOW.isoformat()


def _meta(artifact_overrides=None, **kw):
    """Row metadata WITH per-artifact provenance.

    A row without an `artifacts` block is now `STATUS_LEGACY` on purpose: it is
    the shape the old SQL produced (possibly-old artifact + newest run's meta)
    and nothing in it can show which run wrote the text."""
    artifact = {"research_run_id": "run1", "is_comparable": True,
                "generated_at": NOW.isoformat(),
                "winner_count": 8, "control_count": 8}
    artifact.update(artifact_overrides or {})
    base = {"research_run_id": "run1", "is_comparable": True,
            "generated_at": NOW.isoformat(),
            "winner_count": 8, "control_count": 8,
            "artifacts": {"script_playbook": artifact}}
    base.update(kw)
    return json.dumps(base)


def test_controlled_and_fresh_playbook_is_usable():
    decision = evaluate(_Row("PLAYBOOK", _meta()), now=NOW)
    assert decision.status == STATUS_OK
    assert decision.usable is True
    assert decision.research_run_id == "run1"


def test_no_row_is_missing_not_an_error():
    decision = evaluate(None, now=NOW)
    assert decision.status == STATUS_MISSING
    assert decision.usable is False


def test_uncontrolled_playbook_is_refused_even_though_text_exists():
    """The whole point: survivorship-bias prose must not reach the prompt just
    because the column is non-empty."""
    decision = evaluate(_Row("[UNCONTROLLED — ...]\nstuff",
                             _meta({"is_comparable": False})), now=NOW)
    assert decision.status == STATUS_UNCONTROLLED
    assert decision.usable is False
    assert "not verified" in decision.reason


def test_uncontrolled_is_caught_from_the_stamp_alone():
    """Even if cohort_meta says comparable, the stamp on the text wins — the two
    disagreeing is itself a reason not to use it."""
    decision = evaluate(_Row("[UNCONTROLLED — ...]\nstuff",
                             _meta({"is_comparable": True})), now=NOW)
    assert decision.status == STATUS_UNCONTROLLED


def test_stale_playbook_is_refused():
    old = (NOW - timedelta(days=200)).isoformat()
    decision = evaluate(_Row("PLAYBOOK", _meta({"generated_at": old}),
                             updated_at=old), now=NOW)
    assert decision.status == STATUS_STALE
    assert decision.usable is False
    assert decision.age_days > 190


def test_unreadable_metadata_is_an_error_not_a_pass():
    decision = evaluate(_Row("PLAYBOOK", "{not json"), now=NOW)
    assert decision.status == STATUS_ERROR
    assert decision.usable is False


def test_empty_playbook_with_a_healthy_row_is_missing():
    assert evaluate(_Row("", _meta()), now=NOW).status == STATUS_MISSING


# ── Per-artifact provenance beats the row's ──────────────────────────────────

def test_carried_forward_artifact_is_judged_by_its_own_run():
    """The row's cohort is fresh and controlled, but THIS artifact came from an
    older uncontrolled run. Judging it by the row would launder it."""
    meta = json.dumps({
        "research_run_id": "run_new", "is_comparable": True,
        "winner_count": 9, "control_count": 9,
        "artifacts": {"script_playbook": {
            "research_run_id": "run_old", "is_comparable": False,
            "generated_at": NOW.isoformat(), "winner_count": 3, "control_count": 0}},
    })
    decision = evaluate(_Row("some playbook", meta), now=NOW)
    assert decision.status == STATUS_UNCONTROLLED
    assert decision.research_run_id == "run_old"
    assert decision.details["control_count"] == 0


def test_carried_forward_artifact_ages_from_its_own_timestamp():
    meta = json.dumps({
        "research_run_id": "run_new", "is_comparable": True,
        "artifacts": {"script_playbook": {
            "research_run_id": "run_old", "is_comparable": True,
            "generated_at": (NOW - timedelta(days=300)).isoformat()}},
    })
    # Row was touched today; the artifact is 300 days old.
    decision = evaluate(_Row("playbook", meta, updated_at=NOW.isoformat()), now=NOW)
    assert decision.status == STATUS_STALE


# ── Policy ───────────────────────────────────────────────────────────────────

def test_unusable_intel_is_a_deterministic_skip_by_default():
    decision = resolve_for_writer(None, scope="finance", now=NOW)
    assert decision.usable is False          # skip, do not raise


def test_channel_that_requires_intel_fails_closed():
    with pytest.raises(CompetitorIntelRequired) as exc:
        resolve_for_writer(_Row("[UNCONTROLLED — x]", _meta({"is_comparable": False})),
                           required=True, scope="finance", now=NOW)
    assert "uncontrolled" in str(exc.value)


def test_required_channel_with_good_intel_passes():
    decision = resolve_for_writer(_Row("PLAYBOOK", _meta()), required=True,
                                  scope="finance", now=NOW)
    assert decision.usable is True


def test_rejection_is_logged_rather_than_swallowed(monkeypatch):
    """`except: pass` left no trace at all. Every refusal must be countable."""
    seen = []
    monkeypatch.setattr(intel_gate.logger, "warning",
                        lambda msg, **kw: seen.append((msg, kw)))
    resolve_for_writer(None, scope="finance", now=NOW)
    assert seen and seen[0][0] == "competitor intel rejected"
    assert seen[0][1]["status"] == STATUS_MISSING


def test_status_set_is_closed():
    """Callers branch on these; a new free-text status would silently fall
    through every branch."""
    from omnicast.analytics.intel_gate import STATUS_LEGACY

    assert {STATUS_OK, STATUS_MISSING, STATUS_UNCONTROLLED, STATUS_STALE,
            STATUS_ERROR, STATUS_LEGACY} == {"ok", "missing", "uncontrolled",
                                             "stale", "error", "legacy"}


# ── Rows written before provenance existed cannot be verified ────────────────

def test_row_without_any_artifact_provenance_is_legacy():
    """These rows are, by construction, "possibly-old artifact + newest run's
    metadata" — the exact laundering this gate exists to stop."""
    from omnicast.analytics.intel_gate import STATUS_LEGACY

    legacy = json.dumps({"research_run_id": "run_new", "is_comparable": True,
                         "generated_at": NOW.isoformat()})
    decision = evaluate(_Row("old playbook", legacy), now=NOW)
    assert decision.status == STATUS_LEGACY
    assert decision.usable is False


def test_artifacts_block_missing_this_artifact_is_legacy():
    from omnicast.analytics.intel_gate import STATUS_LEGACY

    meta = json.dumps({"research_run_id": "r", "is_comparable": True,
                       "generated_at": NOW.isoformat(),
                       "artifacts": {"title_playbook": {}}})
    assert evaluate(_Row("playbook", meta), now=NOW).status == STATUS_LEGACY


@pytest.mark.parametrize("artifacts", [
    ["script_playbook"],                       # a list
    {"script_playbook": "run_old"},            # a string where a dict belongs
    {"script_playbook": 7},
])
def test_corrupt_provenance_is_an_error_not_maximum_trust(artifacts):
    """A non-dict record used to raise AttributeError out of `evaluate` and all
    the way out of the writer's prompt builder."""
    meta = json.dumps({"artifacts": artifacts})
    decision = evaluate(_Row("playbook", meta), now=NOW)
    assert decision.status == STATUS_ERROR
    assert decision.usable is False


def test_future_timestamp_is_not_permanently_fresh():
    """`max(age, 0.0)` made "2099-01-01" read as age 0."""
    meta = json.dumps({"artifacts": {"script_playbook": {
        "generated_at": "2099-01-01T00:00:00+00:00", "is_comparable": True}}})
    assert evaluate(_Row("playbook", meta), now=NOW).usable is False
