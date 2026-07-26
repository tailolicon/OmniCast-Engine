"""Phase B pins — senior-finance content engine (flagship The Retirement Desk).

Covers the four new capabilities and their fail-closed behaviour:
  * finance_explainer_v1 rubric: selection, weights, deterministic YMYL caps
  * fact-citation ledger: extraction, coverage, recency, orphan detection
  * upload compliance: finance YMYL text checks (was health-only)
  * production router: INFOGRAPHIC becomes a REAL chart only when chart_render
    is declared AND backed by matplotlib
"""

from __future__ import annotations

import json
from pathlib import Path

from omnicast.agents.critic import VO_DIMS as EXPL_VO, _rubric_dims
from omnicast.agents.rubrics import finance_explainer as fe
from omnicast.compliance.fact_ledger import (
    FactEntry,
    FactLedger,
    extract_numeric_claims,
    gate_fact_ledger,
    render_markdown,
)
from omnicast.config.niches import get_niche_config
from omnicast.media import production_router as pr
from omnicast.upload.compliance import ComplianceChecker

ROOT = Path(__file__).resolve().parents[2]


# ── Rubric selection + weights ────────────────────────────────────────────────


class TestFinanceRubric:
    def test_dims_sum_to_70_30(self):
        assert sum(fe.VO_DIMS.values()) == 70
        assert sum(fe.PROD_DIMS.values()) == 30
        assert fe.VO_PASS == 53 and fe.PROD_PASS == 23

    def test_rubric_selected_by_rubric_id(self):
        vod, prod, vp, pp = _rubric_dims(False, fe.RUBRIC_ID)
        assert vod is fe.VO_DIMS and prod is fe.PROD_DIMS

    def test_default_explainer_unchanged_without_rubric_id(self):
        vod, _, _, _ = _rubric_dims(False)
        assert vod is EXPL_VO

    def test_narrative_wins_over_rubric_id(self):
        # A narrative channel with a stray rubric_id must stay on the horror set
        # — content_format is the stronger routing signal.
        vod, _, _, _ = _rubric_dims(True, fe.RUBRIC_ID)
        assert "continuity" in vod

    def test_accuracy_is_the_heaviest_vo_dim(self):
        assert fe.VO_DIMS["accuracy_trust"] == max(fe.VO_DIMS.values())


class TestFinanceSlopSignals:
    def test_persona_claim_caps_accuracy_and_compliance(self):
        flags, caps = fe.finance_slop_signals(
            "As a financial advisor, I tell my clients to relax about the market.")
        assert any("PERSONA" in f.upper() for f in flags)
        assert caps["accuracy_trust"] <= 4
        assert caps["niche_compliance"] <= 1

    def test_guarantee_language_zeroes_compliance(self):
        _, caps = fe.finance_slop_signals("This fund has guaranteed returns of 8%.")
        assert caps["niche_compliance"] == 0

    def test_personalized_advice_capped(self):
        _, caps = fe.finance_slop_signals("You should claim at 62 to beat the system.")
        assert caps["niche_compliance"] <= 2

    def test_clean_educational_text_no_caps(self):
        flags, caps = fe.finance_slop_signals(
            "According to SSA's 2026 fact sheet, the earnings limit is $23,400. "
            "For this example retiree, claiming at 67 keeps the full benefit.")
        assert not flags and not caps

    def test_spoken_source_attribution_is_not_flagged(self):
        flags, _ = fe.finance_slop_signals(
            "The FBI's 2025 IC3 report counted 2 billion dollars in losses.")
        assert not flags


# ── Niche config wiring ───────────────────────────────────────────────────────


class TestSeniorNicheConfig:
    def test_registry_entry_exists_with_rubric(self):
        cfg = get_niche_config("finance", "retirement_senior")
        assert cfg.rubric_id == fe.RUBRIC_ID
        assert cfg.content_format == "explainer"
        assert any("ssa.gov" in s.lower() or "social security" in s.lower()
                   for s in cfg.proof_sources)

    def test_channel_config_points_at_the_niche(self):
        raw = json.loads((ROOT / "channels" / "senior_wealth_us.json")
                         .read_text(encoding="utf-8"))
        assert raw["niche_config_key"] == "finance.retirement_senior"
        assert "chart_render" in raw["supported_production"]

    def test_other_niches_have_no_rubric_override(self):
        assert get_niche_config("finance", "retirement").rubric_id == ""


# ── Fact-citation ledger ──────────────────────────────────────────────────────

SCRIPT = (
    "Claiming at 62 instead of 67 costs this retiree $612 every month. "
    "According to SSA's 2026 fact sheet, the earnings limit is $23,400. "
    "That is a 30% permanent reduction."
)


def _entry(**kw) -> FactEntry:
    base = dict(claim="the earnings limit is $23,400", value="$23,400",
                source_name="SSA 2026 Fact Sheet",
                source_url="https://www.ssa.gov/news/press/factsheets/",
                as_of="2026", year_sensitive=True, section="HOOK")
    base.update(kw)
    return FactEntry(**base)


class TestFactExtraction:
    def test_extracts_dollars_percents_ages_years(self):
        claims = extract_numeric_claims(SCRIPT)
        cores = {"".join(ch for ch in c if ch.isdigit()) for c in claims}
        assert {"612", "2026", "23400", "30", "62", "67"} <= cores

    def test_small_bare_integers_are_structure_not_facts(self):
        assert extract_numeric_claims("Here are 3 steps and one form.") == []


class TestFactGate:
    def test_fail_closed_on_empty_ledger(self):
        report = gate_fact_ledger(SCRIPT, FactLedger(entries=[]))
        assert not report.passed
        assert report.claim_count > 0 and report.uncovered

    def test_full_coverage_passes(self):
        ledger = FactLedger(entries=[
            _entry(),
            _entry(claim="claiming at 62 instead of 67 costs $612 every month",
                   value="$612", year_sensitive=False,
                   source_name="SSA benefit reduction table", as_of="2026"),
            _entry(claim="a 30% permanent reduction", value="30%",
                   year_sensitive=False, as_of="2026",
                   source_name="SSA benefit reduction table"),
        ])
        report = gate_fact_ledger(SCRIPT, ledger, current_year=2026)
        assert report.passed, report.notes + report.uncovered

    def test_stale_year_sensitive_figure_blocks(self):
        ledger = FactLedger(entries=[
            _entry(as_of="2024"),
            _entry(claim="claiming at 62 instead of 67 costs $612 every month",
                   value="$612", year_sensitive=False, as_of="2026"),
            _entry(claim="a 30% permanent reduction", value="30%",
                   year_sensitive=False, as_of="2026"),
        ])
        report = gate_fact_ledger(SCRIPT, ledger, current_year=2026)
        assert not report.passed and report.stale_entries

    def test_missing_source_blocks(self):
        ledger = FactLedger(entries=[_entry(source_name="")])
        report = gate_fact_ledger(SCRIPT, ledger, current_year=2026)
        assert not report.passed
        assert any("missing source_name" in v for v in report.invalid_entries)

    def test_orphan_entry_blocks(self):
        # An entry about a figure that never appears in the script = the ledger
        # describes a different draft (or a hallucinated row).
        ledger = FactLedger(entries=[
            _entry(), _entry(claim="the limit is $99,999", value="$99,999",
                             year_sensitive=False, as_of="2026"),
        ])
        report = gate_fact_ledger(SCRIPT, ledger, current_year=2026)
        assert not report.passed and report.orphan_entries

    def test_script_without_numbers_passes_vacuously(self):
        report = gate_fact_ledger("A calm chat about paperwork.",
                                  FactLedger(entries=[]))
        assert report.passed and report.claim_count == 0

    def test_markdown_lists_every_entry(self):
        ledger = FactLedger(entries=[_entry()]).stamp(SCRIPT, "test-model")
        md = render_markdown(ledger, gate_fact_ledger(SCRIPT, ledger,
                                                      current_year=2026))
        assert "SSA 2026 Fact Sheet" in md and ledger.script_sha256 in md


# ── Upload compliance: finance YMYL ──────────────────────────────────────────


class TestFinanceUploadCompliance:
    def test_missing_disclaimer_flagged(self):
        v = ComplianceChecker._check_ymyl_finance_text(
            "When To Claim Social Security", "The earnings limit changed for 2026.")
        assert any("disclaimer" in x for x in v)

    def test_disclaimered_educational_text_clean(self):
        v = ComplianceChecker._check_ymyl_finance_text(
            "When To Claim Social Security",
            "Educational only — not financial, tax, or legal advice. "
            "Verify at ssa.gov before acting.")
        assert v == []

    def test_guarantee_language_flagged(self):
        v = ComplianceChecker._check_ymyl_finance_text(
            "Retirement Income", "Guaranteed returns. Not financial advice.")
        assert any("prohibited promise" in x for x in v)

    def test_persona_claim_flagged(self):
        v = ComplianceChecker._check_ymyl_finance_text(
            "My 401k Advice", "As a financial advisor, trust me. Educational only.")
        assert any("persona" in x for x in v)

    def test_non_finance_text_ignored(self):
        assert ComplianceChecker._check_ymyl_finance_text(
            "Best Hiking Trails", "Bring water.") == []

    def test_check_text_includes_finance(self):
        v = ComplianceChecker.check_text(
            "Social Security Secrets", "Guaranteed returns forever!")
        assert any("finance/YMYL" in x for x in v)


# ── Production router: real chart mode ───────────────────────────────────────

_CHART_TEXT = "In 2026 the earnings limit grew by 4% compared to last year."


class TestChartRouting:
    def test_infographic_without_capability_stays_approximated(self):
        route = pr.route_scene(0, _CHART_TEXT, capabilities=set())
        assert route.mode == pr.INFOGRAPHIC
        assert route.visual_type == "generated_image"
        assert not route.is_rendered_as_itself
        assert route.approximation_gap

    def test_infographic_with_chart_render_is_real(self):
        route = pr.route_scene(0, _CHART_TEXT, capabilities={"chart_render"})
        assert route.mode == pr.INFOGRAPHIC
        assert route.visual_type == "chart"
        assert route.is_rendered_as_itself
        assert route.approximation_gap == ""

    def test_capability_requires_matplotlib_backing(self, monkeypatch):
        ch = type("C", (), {"supported_production": ["chart_render"]})()
        monkeypatch.setattr(pr, "chart_render_available", lambda: False)
        assert "chart_render" not in pr.capabilities_from_channel(ch)
        monkeypatch.setattr(pr, "chart_render_available", lambda: True)
        assert "chart_render" in pr.capabilities_from_channel(ch)

    def test_chart_render_available_matches_chart_gen(self):
        from omnicast.media.providers import chart_gen
        assert pr.chart_render_available() == chart_gen.available()
