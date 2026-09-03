"""The writer's competitor-intel gate is actually wired (P0.1 audit round 2).

An audit reverted BOTH halves of the writer's gate — the `competitor_intel_required`
read and the vault-load-failure branch — and the entire suite stayed green,
because every test exercised `intel_gate` directly and none exercised the
writer. A rule nothing can fail is not a rule. These tests fail if the wiring
is removed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import omnicast.agents.writer as writer_mod
from omnicast.analytics.intel_gate import (
    STATUS_ERROR,
    STATUS_LEGACY,
    STATUS_OK,
    STATUS_UNCONTROLLED,
    CompetitorIntelRequired,
)
from omnicast.models.enums import Market, Niche
from omnicast.models.script import TopicBrief

NOW = datetime.now(timezone.utc)


class _Row:
    def __init__(self, playbook, *, comparable=True, age_days=1.0):
        stamped = (NOW - timedelta(days=age_days)).isoformat()
        self.script_playbook = playbook
        self.updated_at = stamped
        self.cohort_meta = json.dumps({
            "research_run_id": "run1",
            "generated_at": stamped,
            "is_comparable": comparable,
            "artifacts": {"script_playbook": {
                "research_run_id": "run1",
                "generated_at": stamped,
                "is_comparable": comparable,
                "winner_count": 8, "control_count": 8}},
        })


def _brief(required=False):
    return TopicBrief(title="t", niche=Niche.FINANCE, market=Market.US,
                      competitor_intel_required=required)


def _vault(monkeypatch, row=None, error=None):
    def _load(scope):
        if error:
            raise error
        return row

    monkeypatch.setattr(writer_mod, "_load_competitor_intel", _load)


def test_verified_playbook_is_accepted(monkeypatch):
    _vault(monkeypatch, row=_Row("REAL PLAYBOOK"))
    decision = writer_mod.resolve_competitor_playbook(_brief())
    assert decision.status == STATUS_OK
    assert decision.usable is True
    assert decision.playbook == "REAL PLAYBOOK"


def test_uncontrolled_playbook_is_refused(monkeypatch):
    _vault(monkeypatch, row=_Row("[UNCONTROLLED — x]\nstuff", comparable=False))
    decision = writer_mod.resolve_competitor_playbook(_brief())
    assert decision.status == STATUS_UNCONTROLLED
    assert decision.usable is False


def test_legacy_row_is_refused(monkeypatch):
    """Rows written before per-artifact provenance cannot be shown to match
    their metadata, so they are not used."""

    class _Legacy:
        script_playbook = "old playbook"
        cohort_meta = json.dumps({"research_run_id": "r", "is_comparable": True})
        updated_at = NOW.isoformat()

    _vault(monkeypatch, row=_Legacy())
    assert writer_mod.resolve_competitor_playbook(_brief()).status == STATUS_LEGACY


def test_vault_failure_is_reported_as_error_not_missing(monkeypatch):
    """`None` would have reported STATUS_MISSING — 'nothing learned yet' — for
    what is actually a broken read, and metrics would have counted it as one."""
    _vault(monkeypatch, error=RuntimeError("db is gone"))
    decision = writer_mod.resolve_competitor_playbook(_brief())
    assert decision.status == STATUS_ERROR
    assert "db is gone" in decision.reason
    assert decision.usable is False


def test_required_channel_raises_on_unusable_intel(monkeypatch):
    """This is the branch the audit proved was dead code: the flag was read with
    getattr() off a model that drops extras, so it was always False."""
    _vault(monkeypatch, row=_Row("[UNCONTROLLED — x]", comparable=False))
    with pytest.raises(CompetitorIntelRequired):
        writer_mod.resolve_competitor_playbook(_brief(required=True))


def test_required_channel_raises_on_vault_failure(monkeypatch):
    _vault(monkeypatch, error=RuntimeError("db is gone"))
    with pytest.raises(CompetitorIntelRequired):
        writer_mod.resolve_competitor_playbook(_brief(required=True))


def test_required_channel_passes_with_verified_intel(monkeypatch):
    _vault(monkeypatch, row=_Row("REAL PLAYBOOK"))
    assert writer_mod.resolve_competitor_playbook(_brief(required=True)).usable


def test_optional_channel_never_raises(monkeypatch):
    """Default policy is a deterministic skip, not a pipeline stop."""
    for row, error in ((None, None), (_Row("x", comparable=False), None),
                       (None, RuntimeError("boom"))):
        _vault(monkeypatch, row=row, error=error)
        assert writer_mod.resolve_competitor_playbook(_brief()).usable is False


def test_stale_playbook_is_refused(monkeypatch):
    _vault(monkeypatch, row=_Row("PLAYBOOK", age_days=400))
    assert writer_mod.resolve_competitor_playbook(_brief()).usable is False
