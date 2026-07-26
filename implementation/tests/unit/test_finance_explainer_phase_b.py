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


class TestCodexAuditFixes:
    """Pins for the 2026-07-26 codex adversarial audit findings."""

    # Finding 2 — typed tokens: kind collisions and as_of masking
    def test_percent_not_covered_by_age_entry(self):
        script = "The fund charges a 6.2% fee."
        ledger = FactLedger(entries=[
            _entry(claim="full retirement age is 67, early claiming at 62",
                   value="62", year_sensitive=False, as_of="2026")])
        report = gate_fact_ledger(script, ledger, current_year=2026)
        assert any("6.2" in u for u in report.uncovered)

    def test_money_not_covered_by_attribution_year(self):
        script = "The penalty is $2,026 per year."
        ledger = FactLedger(entries=[
            _entry(claim="a penalty exists", value="", as_of="2026",
                   year_sensitive=False, source_name="IRS 2026")])
        report = gate_fact_ledger(script, ledger, current_year=2026)
        assert any("2,026" in u for u in report.uncovered)

    # Finding 3 — recency is deterministic, future years rejected
    def test_future_as_of_is_invalid(self):
        ledger = FactLedger(entries=[_entry(as_of="2027")])
        report = gate_fact_ledger(SCRIPT, ledger, current_year=2026)
        assert any("future" in v for v in report.invalid_entries)

    def test_year_sensitive_inferred_from_claim_text(self):
        # Model says year_sensitive=False, but "earnings limit" is a rule-year
        # figure — the heuristic must overrule the model.
        ledger = FactLedger(entries=[_entry(year_sensitive=False, as_of="2024")])
        report = gate_fact_ledger("The earnings limit is $23,400.", ledger,
                                  current_year=2026)
        assert report.stale_entries

    # Finding 5 — extraction forms
    def test_extraction_decimals_ordinal_days_word_percent(self):
        from omnicast.compliance.fact_ledger import numeric_tokens
        toks = {(t.kind, t.value) for t in numeric_tokens(
            "The multiplier is 1.027. File by July 10th. Costs eight percent.")}
        assert ("plain", 1.027) in toks
        assert ("day", 10.0) in toks
        assert ("percent", 8.0) in toks

    # Findings 1/6 — render precheck + full chart audit
    def test_render_precheck_missing_and_mismatched(self, tmp_path):
        from omnicast.compliance.fact_ledger import render_precheck
        lf = tmp_path / "fact_ledger.json"
        ok, why = render_precheck(lf, "text")
        assert not ok and "missing" in why
        lf.write_text(json.dumps({
            "gate": {"passed": True},
            "ledger": {"script_sha256": "deadbeef"},
        }), encoding="utf-8")
        ok, why = render_precheck(lf, "text")
        assert not ok and "different script" in why

    def test_render_precheck_pass(self, tmp_path):
        from omnicast.compliance.fact_ledger import render_precheck, script_sha256
        lf = tmp_path / "fact_ledger.json"
        lf.write_text(json.dumps({
            "gate": {"passed": True},
            "ledger": {"script_sha256": script_sha256("the script")},
        }), encoding="utf-8")
        ok, why = render_precheck(lf, "the script")
        assert ok, why

    def _ledger_data(self, script: str) -> dict:
        from omnicast.compliance.fact_ledger import script_sha256
        return {
            "gate": {"passed": True},
            "ledger": {
                "script_sha256": script_sha256(script),
                "entries": [
                    {"claim": "limit was $22,320 in 2025 and $23,400 in 2026",
                     "value": "$23,400", "source_name": "SSA 2026", "as_of": "2026"},
                    {"claim": "the old limit", "value": "$22,320",
                     "source_name": "SSA 2025", "as_of": "2025"},
                ],
            },
        }

    def test_chart_audit_clean_spec_passes(self):
        from omnicast.compliance.fact_ledger import audit_chart_spec
        script = "Limit rose from $22,320 to $23,400."
        spec = {"labels": ["2025", "2026"], "values": [22320, 23400],
                "title": "Earnings limit", "source": "SSA 2026"}
        assert audit_chart_spec(spec, self._ledger_data(script), script) == []

    def test_chart_audit_catches_unsourced_label_and_title(self):
        from omnicast.compliance.fact_ledger import audit_chart_spec
        script = "Limit rose from $22,320 to $23,400."
        spec = {"labels": ["Age 62", "Age 67"], "values": [22320, 23400],
                "title": "2031 limits", "source": "SSA 2026"}
        failures = audit_chart_spec(spec, self._ledger_data(script), script)
        assert any("62" in f for f in failures)
        assert any("2031" in f for f in failures)

    def test_chart_audit_requires_gate_and_sha(self):
        from omnicast.compliance.fact_ledger import audit_chart_spec
        script = "Limit is $23,400."
        data = self._ledger_data(script)
        data["gate"]["passed"] = False
        failures = audit_chart_spec({"labels": [], "values": []}, data, script)
        assert any("gate" in f for f in failures)
        data = self._ledger_data(script)
        failures = audit_chart_spec({"labels": [], "values": []}, data, "other text")
        assert any("sha mismatch" in f for f in failures)

    # Finding 4 — fatal caps force rejection at the critic
    def test_fatal_caps_helper(self):
        assert not fe.fatal_caps({})
        assert fe.fatal_caps({"niche_compliance": 0})
        assert fe.fatal_caps({"accuracy_trust": 4})
        assert not fe.fatal_caps({"anti_ai_cliche": 3})

    # Finding 8 — regex evasions and over-breadth
    def test_persona_evasions_caught(self):
        for text in ("I'm your CPA, relax.",
                     "I've advised retirees for twenty years; our clients agree."):
            _, caps = fe.finance_slop_signals(text)
            assert fe.fatal_caps(caps), text

    def test_guarantee_with_interposed_number_caught(self):
        for text in ("Guaranteed 8% returns.", "I guarantee an 8% return."):
            _, caps = fe.finance_slop_signals(text)
            assert caps.get("niche_compliance") == 0, text

    def test_educational_frames_not_flagged(self):
        for text in ("Whether you should claim at 62 depends on your record.",
                     "As a CPA would tell you, verify this independently."):
            flags, caps = fe.finance_slop_signals(text)
            assert not caps, (text, flags)

    # Finding 9 — upload classification
    def test_iraq_is_not_finance(self):
        assert not ComplianceChecker._looks_finance_ymyl("Best hiking trails in Iraq")

    def test_guarantee_flagged_even_outside_finance_niche(self):
        v = ComplianceChecker._check_ymyl_finance_text(
            "Miracle course", "Guaranteed 8% returns for everyone!")
        assert any("prohibited promise" in x for x in v)

    def test_partial_disclaimer_phrase_not_enough(self):
        v = ComplianceChecker._check_ymyl_finance_text(
            "Retirement interview", "A talk with a licensed professional.")
        assert any("disclaimer" in x for x in v)


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
