"""Round-4 fixes: the containment work reaches production, not just tests.

Every failure here was a case of "the mechanism exists and is well tested, but
nothing in production can reach it":

  * `competitor_intel_required` was declared on `TopicBrief` only, and no
    production brief builder set it — so the fail-closed branch was unreachable
    outside hand-built unit tests.
  * `shadow_row()` had no caller, `topics` stores one `score` column, and
    `DiscoveryResult` is in-memory — so the corpus the promotion gate needs did
    not exist.
  * On the main API path the router is `ChannelArchitectAgent`, not
    `TopicScorer`, so a corpus recording only the scorer's lane would calibrate
    a decision nobody makes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omnicast.config.channel import ChannelProfile
from omnicast.discovery import shadow_log
from omnicast.discovery.brief_generator import BriefGenerator
from omnicast.discovery.models import ScoredTopic, TopicRawData
from omnicast.models.enums import Market, Niche, TopicSource


def _channel(**kw):
    return ChannelProfile(
        channel_id="fin_us", name="Finance US", niche=Niche.FINANCE,
        market=Market.US, **kw)


def _scored(title="T", **metrics):
    raw = TopicRawData(title=title, source=TopicSource.YOUTUBE_COMPETITOR,
                       niche=Niche.FINANCE, market=Market.US, raw_metrics=metrics)
    return ScoredTopic(raw=raw, trend_momentum=24, gap_score=12, rpm_potential=15,
                       novelty_score=5, stack_fit=7.5, total_score=79,
                       auto_approved=True, total_score_v1=79.0,
                       total_score_v2=63.5, gap_score_v1=35.0)


# ── The per-channel policy is reachable from a channel JSON ─────────────────

def test_channel_profile_declares_the_policy():
    assert _channel().competitor_intel_required is False
    assert _channel(competitor_intel_required=True).competitor_intel_required is True


def test_channel_json_round_trips_the_policy(tmp_path: Path):
    """It has to survive the file, not just the constructor — channels are
    configured as JSON on disk."""
    payload = {"channel_id": "fin_us", "name": "Finance US", "niche": "finance",
               "market": "US", "competitor_intel_required": True}
    (tmp_path / "fin_us.json").write_text(json.dumps(payload), encoding="utf-8")
    loaded = ChannelProfile(**json.loads((tmp_path / "fin_us.json").read_text()))
    assert loaded.competitor_intel_required is True


def test_brief_generator_carries_the_policy_through():
    strict = BriefGenerator.generate(_scored(), channel=_channel(
        competitor_intel_required=True))
    lenient = BriefGenerator.generate(_scored(), channel=_channel())
    assert strict.competitor_intel_required is True
    assert lenient.competitor_intel_required is False


def test_channel_architect_brief_carries_the_policy():
    from omnicast.agents.channel_architect import TopicOpportunity

    opp = TopicOpportunity(
        title="T", sub_niche="retirement", audience_segment="a", pain_point="p",
        content_angle="c", demand_score=30, audience_fit=30, opportunity=20,
        total_score=80)
    brief = opp.to_brief(_channel(competitor_intel_required=True))
    assert brief.competitor_intel_required is True


def test_every_production_brief_builder_sets_the_flag():
    """A new builder that forgets it silently reopens the hole."""
    import inspect

    from omnicast.agents import channel_architect
    from omnicast.discovery import brief_generator
    from omnicast.pipeline import steps

    for module in (brief_generator, steps, channel_architect):
        source = inspect.getsource(module)
        if "TopicBrief(" in source:
            assert "competitor_intel_required" in source, (
                f"{module.__name__} builds a TopicBrief without the intel policy")


# ── The shadow corpus survives the request ──────────────────────────────────

def test_rows_carry_both_generations_and_the_deciding_component():
    rows = shadow_log.rows_for_run([_scored(outlier_ratio=8.0)],
                                   channel_id="fin_us", run_id="r1")
    assert len(rows) == 1
    row = rows[0]
    assert row["total_v1"] == 79.0 and row["total_v2"] == 63.5
    assert row["channel_id"] == "fin_us" and row["discovery_run_id"] == "r1"
    assert row["decided_by"] == "topic_scorer"
    assert row["selected"] is None      # not known until the router has run


def test_marking_selection_records_the_real_router():
    """Without this the corpus shows how the two generations WOULD rank topics,
    but not whether either ranking matched what got produced."""
    rows = shadow_log.rows_for_run([_scored(title="picked"), _scored(title="dropped")])
    shadow_log.mark_selected(rows, ["Picked"], decided_by="channel_architect")
    by_title = {r["title"]: r for r in rows}
    assert by_title["picked"]["selected"] is True
    assert by_title["dropped"]["selected"] is False
    assert all(r["decided_by"] == "channel_architect" for r in rows)


def test_rows_are_appended_and_readable(tmp_path: Path):
    log = tmp_path / "shadow.jsonl"
    assert shadow_log.append_rows(shadow_log.rows_for_run([_scored()]), log) == 1
    assert shadow_log.append_rows(shadow_log.rows_for_run([_scored()]), log) == 1
    assert len(shadow_log.read_rows(log)) == 2


def test_a_corrupt_line_costs_one_row_not_the_file(tmp_path: Path):
    log = tmp_path / "shadow.jsonl"
    shadow_log.append_rows(shadow_log.rows_for_run([_scored()]), log)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("{not json\n[]\n")
    shadow_log.append_rows(shadow_log.rows_for_run([_scored()]), log)
    assert len(shadow_log.read_rows(log)) == 2


def test_telemetry_failure_never_breaks_a_run(tmp_path: Path, monkeypatch):
    """A discovery run that dies because its logging failed is worse than one
    with no logging."""
    import builtins

    real_open = builtins.open

    def _explode(path, *a, **kw):
        if str(path).endswith("shadow.jsonl"):
            raise OSError("disk is full")
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", _explode)
    assert shadow_log.append_rows([{"a": 1}], tmp_path / "shadow.jsonl") == 0


async def test_orchestrator_writes_a_corpus_for_every_run(tmp_path, monkeypatch):
    from omnicast.discovery.orchestrator import DiscoveryOrchestrator
    from omnicast.discovery.scorer import TopicScorer

    log = tmp_path / "shadow.jsonl"
    monkeypatch.setattr(shadow_log, "default_log_path", lambda: log)

    class _Scanner:
        source = TopicSource.YOUTUBE_COMPETITOR

        async def scan(self):
            from omnicast.discovery.models import SourceResult

            return SourceResult(source=self.source, topics=[
                TopicRawData(title="A", source=self.source, niche=Niche.FINANCE,
                             market=Market.US, raw_metrics={"outlier_ratio": 8.0})])

    orchestrator = DiscoveryOrchestrator(
        scanners=[_Scanner()], scorer=TopicScorer(scoring_mode="shadow"))
    await orchestrator.run()

    rows = shadow_log.read_rows(log)
    assert len(rows) == 1
    assert rows[0]["total_v1"] > 0 and rows[0]["total_v2"] > 0
    assert orchestrator.run_id and rows[0]["discovery_run_id"] == orchestrator.run_id


# ── The learner cannot lose a concurrent update ─────────────────────────────

def test_competitor_intel_read_merge_write_is_one_transaction(tmp_path: Path):
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import CompetitorIntel

    path = tmp_path / "vault.db"
    vault_db.init_db(path)

    seen: list = []

    def _build(previous):
        seen.append(previous)
        return CompetitorIntel(niche="finance", title_playbook="A",
                               cohort_meta="{}", updated_at="2026-07-25")

    vault_db.replace_competitor_intel("finance", _build, path)
    assert seen == [None]

    def _build2(previous):
        seen.append(previous)
        return CompetitorIntel(niche="finance", title_playbook="B",
                               cohort_meta="{}", updated_at="2026-07-26")

    vault_db.replace_competitor_intel("finance", _build2, path)
    # The second builder SAW the first write — that is the guarantee the split
    # read/write connections could not give.
    assert seen[1] is not None and seen[1].title_playbook == "A"
    assert vault_db.get_competitor_intel("finance", path).title_playbook == "B"


def test_a_failing_build_leaves_the_row_untouched(tmp_path: Path):
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import CompetitorIntel

    path = tmp_path / "vault.db"
    vault_db.init_db(path)
    vault_db.replace_competitor_intel(
        "finance",
        lambda prev: CompetitorIntel(niche="finance", title_playbook="GOOD",
                                     cohort_meta="{}", updated_at="2026-07-25"),
        path)

    def _boom(previous):
        raise RuntimeError("digest failed")

    with pytest.raises(RuntimeError):
        vault_db.replace_competitor_intel("finance", _boom, path)
    assert vault_db.get_competitor_intel("finance", path).title_playbook == "GOOD"
