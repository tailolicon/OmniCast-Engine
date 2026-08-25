"""Pre-writing evidence must survive a live-page-shaped verifier."""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock

from omnicast.agents.evidence_research import (
    EvidencePack,
    SourceEvidence,
    evidence_coverage_problems,
    evidence_for_topic,
    extract_supporting_quote,
    fact_ledger_from_evidence_pack,
    fetch_source_text,
    gate_draft_against_pack,
    gate_draft_claims_against_pack,
    gate_draft_visuals_against_pack,
    gate_ledger_against_pack,
    normalize_draft_evidence_numbers,
    reverify_evidence_pack,
    sanitize_ssa_earnings_draft,
    verify_entry_against_text,
)


def _entry(**updates) -> SourceEvidence:
    values = {
        "claim": "The 2026 annual exempt amount is $24,480",
        "value": "$24,480",
        "source_name": "SSA Retirement Earnings Test Exempt Amounts",
        "source_url": "https://www.ssa.gov/oact/cola/rtea.html",
        "as_of": "2026",
        "year_sensitive": True,
        "quote": "the annual exempt amount is $24,480 in 2026",
    }
    values.update(updates)
    return SourceEvidence(**values)


PAGE = """
Social Security Administration
The retirement earnings test exempt amounts
For people under full retirement age, the annual exempt amount is $24,480
in 2026. Different rules apply in the year full retirement age is reached.
"""


def test_verified_primary_source_entry_passes():
    assert verify_entry_against_text(
        _entry(), PAGE, current_year=2026) == []


def test_blog_or_http_url_cannot_become_ymyl_evidence():
    problems = verify_entry_against_text(
        _entry(source_url="http://retirement-tips.example/rule"),
        PAGE, current_year=2026)
    assert any("allowed HTTPS primary-source" in p for p in problems)


def test_quote_and_value_must_exist_in_fetched_page():
    problems = verify_entry_against_text(
        _entry(value="$99,999", quote="a sentence the page never said"),
        PAGE, current_year=2026)
    assert any("quote does not occur" in p for p in problems)
    assert any("value" in p and "does not occur" in p for p in problems)


def test_quote_must_support_the_whole_ratio_claim_not_only_the_threshold():
    entry = _entry(
        claim=(
            "For 2026 SSA withholds $1 for every $2 above the $24,480 "
            "annual exempt amount"),
        value="$24,480",
        quote="For 2026, the annual exempt amount is $24,480.",
    )
    page = (
        "For 2026, the annual exempt amount is $24,480. "
        "Elsewhere we withhold $1 for every $2 above that amount.")

    problems = verify_entry_against_text(entry, page, current_year=2026)

    assert any("load-bearing number" in problem for problem in problems)
    assert any("withholding ratio" in problem for problem in problems)


def test_recalculation_claim_cannot_use_an_unrelated_special_rule_quote():
    entry = _entry(
        claim=(
            "Withheld benefits are not lost; SSA recalculates the monthly "
            "benefit after full retirement age"),
        value="",
        year_sensitive=False,
        quote=(
            "The special rule lets us pay a full Social Security benefit for "
            "any whole month we consider you retired."),
    )
    page = entry.quote

    problems = verify_entry_against_text(entry, page, current_year=2026)

    assert any("recalculation of withheld benefits" in p for p in problems)


def test_current_rule_cannot_hide_behind_stale_source():
    problems = verify_entry_against_text(
        _entry(as_of="2025"), PAGE, current_year=2026)
    assert any("not 2026" in p for p in problems)


def test_social_security_earnings_topic_requires_current_threshold_and_recalculation():
    topic = (
        "What Social Security withholds in 2026 before full retirement age "
        "and what happens later")
    incomplete = EvidencePack(
        topic=topic,
        entries=[
            _entry(
                evidence_id="E1",
                claim="SSA deducts $1 for every $2 above the annual limit",
                value="$1 for every $2",
                year_sensitive=False,
                quote="we deduct $1 in benefits for every $2 above the limit",
            ),
            _entry(
                evidence_id="E2",
                claim="SSA publishes annual exempt amounts in a table",
                value="",
                year_sensitive=True,
                quote="Retirement Earnings Test Exempt Amounts",
            ),
        ],
    )

    problems = evidence_coverage_problems(
        incomplete, topic, current_year=2026)

    assert any("current-year exempt amount" in p for p in problems)
    assert any("recalculation" in p for p in problems)


def test_social_security_earnings_topic_coverage_accepts_exact_current_rules():
    topic = (
        "What Social Security withholds in 2026 before full retirement age "
        "and what happens later")
    complete = EvidencePack(
        topic=topic,
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim=(
                    "SSA recalculates the benefit at full retirement age to "
                    "credit months that were withheld"),
                value="",
                year_sensitive=False,
                quote=(
                    "we will recalculate your benefit amount to give you credit "
                    "for the months we withheld benefits"),
            ),
            _entry(
                evidence_id="E3",
                claim=(
                    "SSA counts wages and net profit from self-employment, "
                    "but not pensions or investment income"),
                value="",
                year_sensitive=False,
                quote=(
                    "we count only wages from your job or net profit if "
                    "self-employed; we do not count pensions or investment income"),
            ),
        ],
    )

    assert evidence_coverage_problems(
        complete, topic, current_year=2026) == []


def test_social_security_earnings_pack_rejects_adjacent_payroll_tax_fact():
    topic = (
        "What Social Security withholds in 2026 before full retirement age "
        "and what happens later")
    pack = EvidencePack(
        topic=topic,
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim=(
                    "SSA recalculates benefits to credit months that were "
                    "withheld"),
                value="",
                year_sensitive=False,
                quote=(
                    "we will recalculate your benefit amount to give you credit "
                    "for the months we withheld benefits"),
            ),
            _entry(
                evidence_id="E3",
                claim=(
                    "The Social Security payroll tax contribution and benefit "
                    "base is $184,500"),
                value="$184,500",
                quote="the contribution and benefit base is $184,500",
            ),
        ],
    )

    assert any(
        "adjacent payroll-tax fact" in problem
        for problem in evidence_coverage_problems(
            pack, topic, current_year=2026)
    )


def test_post_writing_ledger_cannot_swap_in_an_unverified_source():
    from omnicast.compliance.fact_ledger import FactEntry, FactLedger

    pack = EvidencePack(
        topic="earnings test",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="Benefits may be recalculated at full retirement age",
                value="2026",
                source_url="https://www.ssa.gov/benefits/retirement/planner/whileworking.html",
                quote="we will recalculate your benefit amount",
            ),
        ],
    )
    good = FactLedger(entries=[FactEntry(
        claim=_entry().claim, value="$24,480",
        source_name=_entry().source_name, source_url=_entry().source_url,
        as_of="2026", year_sensitive=True)])
    assert gate_ledger_against_pack(good, pack) == []

    swapped = good.model_copy(update={"entries": [
        good.entries[0].model_copy(update={
            "source_url": "https://random-finance-blog.example/earnings-test"})
    ]})
    assert any("not verified before writing" in p
               for p in gate_ledger_against_pack(swapped, pack))


def test_post_writing_ledger_accepts_qualitative_and_derived_ratio_values():
    from omnicast.compliance.fact_ledger import FactEntry, FactLedger

    pack = EvidencePack(
        topic="earnings test",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="SSA deducts $1 in benefits for every $2 above the limit",
                value="$1 for every $2",
                year_sensitive=False,
                quote="we deduct $1 in benefits for every $2 above the limit",
            ),
            _entry(
                evidence_id="E3",
                claim="The higher limit is $65,160",
                value="$65,160",
                quote="For 2026, the higher limit is $65,160",
            ),
        ],
    )
    url = pack.entries[0].source_url
    ledger = FactLedger(entries=[
        FactEntry(
            claim="The one-for-two rule is a fifty percent rate",
            value="fifty percent / $1 for every $2",
            source_name="SSA", source_url=url, as_of="2026"),
        FactEntry(
            claim="The rule changes at full retirement age",
            value="(qualitative)",
            source_name="SSA", source_url=url, as_of="2026"),
        FactEntry(
            claim="The two verified limits",
            value="$24,480 / $65,160",
            source_name="SSA", source_url=url, as_of="2026"),
    ])

    assert gate_ledger_against_pack(ledger, pack) == []


def test_draft_gate_catches_stale_spoken_threshold_before_critic():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test in 2026",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="SSA recalculates benefits to credit withheld months",
                value="",
                year_sensitive=False,
                quote=(
                    "we will recalculate your benefit amount to give you credit "
                    "for the months we withheld benefits"),
            ),
        ],
    )
    stale = ScriptScene(
        voiceover=(
            "SSA's 2026 earnings limit is twenty-two thousand three hundred "
            "twenty dollars."),
        visual_prompt="SSA page",
    )
    draft = ScriptDraft(
        variant_id="A",
        brief_title=pack.topic,
        hook="",
        segments=[ScriptSegment(
            index=1,
            heading="The rule",
            content=stale.voiceover,
            estimated_duration_seconds=8,
            scenes=[stale],
        )],
    )

    problems = gate_draft_against_pack(draft, pack)

    assert any("22,320" in p and "not in verified evidence" in p
               for p in problems)


def test_draft_gate_does_not_treat_twelve_monthly_checks_as_a_rule_figure():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test in 2026",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="SSA describes the retirement earnings test",
                value="",
                year_sensitive=False,
                quote="The retirement earnings test applies to beneficiaries",
            ),
        ],
    )
    scene = ScriptScene(
        voiceover=(
            "Withholding may not be spread evenly across twelve monthly checks."),
        visual_prompt="calendar",
    )
    draft = ScriptDraft(
        variant_id="A", brief_title=pack.topic, hook="",
        segments=[ScriptSegment(
            index=1, heading="The timing", content=scene.voiceover,
            estimated_duration_seconds=5, scenes=[scene])])

    assert gate_draft_against_pack(draft, pack) == []


def test_qualitative_gate_blocks_calculator_repayment_and_rule_overreach():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic=(
            "What Social Security withholds while working before full "
            "retirement age"),
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim=(
                    "Benefits withheld are not lost; the monthly benefit is "
                    "increased permanently to account for withheld months"),
                value="",
                year_sensitive=False,
                quote=(
                    "your monthly benefit will be increased permanently to "
                    "account for months in which benefits were withheld"),
            ),
        ],
    )
    scene = ScriptScene(
        voiceover=(
            "Use the SSA earnings test calculator. The test only looks forward "
            "from your claiming month. Later it simply pays the money back on a "
            "different timeline. Most people never hear that."),
        visual_prompt="SSA page",
    )
    draft = ScriptDraft(
        variant_id="A", brief_title=pack.topic, hook="",
        segments=[ScriptSegment(
            index=1, heading="The claim", content=scene.voiceover,
            estimated_duration_seconds=12, scenes=[scene])])

    problems = gate_draft_claims_against_pack(draft, pack)

    assert any("calculator" in problem for problem in problems)
    assert any("one-year special rule" in problem for problem in problems)
    assert any("repayment/refund" in problem for problem in problems)
    assert any("prevalence/behavior" in problem for problem in problems)


def test_qualitative_gate_requires_fra_example_scope_and_approximate_rounding():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic=(
            "What Social Security withholds while working before full "
            "retirement age"),
        entries=[_entry(evidence_id="E1"), _entry(evidence_id="E2")],
    )
    bad = ScriptScene(
        voiceover=(
            "They earn $70,000 in the FRA year. Against $65,160, only $1,613 "
            "is withheld."),
        visual_prompt="calculation",
    )
    good = ScriptScene(
        voiceover=(
            "Assume they earn $70,000 before the month they reach full "
            "retirement age. Against $65,160, approximately $1,613 is withheld."),
        visual_prompt="calculation",
    )

    def problems(scene):
        draft = ScriptDraft(
            variant_id="A", brief_title=pack.topic, hook="",
            segments=[ScriptSegment(
                index=1, heading="HYPOTHETICAL EXAMPLE",
                content=scene.voiceover, estimated_duration_seconds=8,
                scenes=[scene])])
        return gate_draft_claims_against_pack(draft, pack)

    assert len(problems(bad)) == 2
    assert problems(good) == []


def test_visual_gate_blocks_unverified_official_form_or_calculator():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test while working",
        entries=[_entry(evidence_id="E1"), _entry(evidence_id="E2")],
    )
    scenes = [
        ScriptScene(
            voiceover="Review the rule.",
            visual_prompt="close-up of SSA-44 form"),
        ScriptScene(
            voiceover="Use the verified threshold.",
            visual_prompt="Retirement Earnings Test Calculator webpage"),
        ScriptScene(
            voiceover="Compare the two limits.",
            visual_prompt="clean two-bar threshold chart"),
    ]
    draft = ScriptDraft(
        variant_id="A", brief_title=pack.topic, hook="",
        segments=[ScriptSegment(
            index=1, heading="The rule", content="",
            estimated_duration_seconds=12, scenes=scenes)])

    problems = gate_draft_visuals_against_pack(draft, pack)

    assert any("SSA-44" in problem for problem in problems)
    assert any("Calculator" in problem for problem in problems)
    assert not any("two-bar" in problem for problem in problems)


def test_reviewed_ssa_scene_repairs_update_voice_visual_and_word_count():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test while working",
        entries=[_entry(evidence_id="E1"), _entry(evidence_id="E2")],
    )
    old = (
        "Both of those things are true at the same time, and that's the part "
        "most explanations skip entirely.")
    scene = ScriptScene(
        voiceover=old,
        visual_prompt="text: BOTH TRUE AT ONCE",
    )
    draft = ScriptDraft(
        variant_id="A", brief_title=pack.topic, hook="",
        segments=[ScriptSegment(
            index=1, heading="The boundary", content=old,
            estimated_duration_seconds=8, scenes=[scene])],
    )

    repaired, applied = sanitize_ssa_earnings_draft(draft, pack)

    assert applied == [old]
    assert repaired.segments[0].scenes[0].voiceover == (
        "Both facts belong in the same explanation.")
    assert repaired.segments[0].scenes[0].visual_prompt == (
        "two verified facts shown side by side")
    assert repaired.word_count == 7


def test_draft_gate_allows_labelled_hypothetical_inputs_but_not_fake_rule():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test in 2026",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="SSA recalculates benefits to credit withheld months",
                value="",
                year_sensitive=False,
                quote=(
                    "we will recalculate your benefit amount to give you credit "
                    "for the months we withheld benefits"),
            ),
        ],
    )
    example = ScriptSegment(
        index=1,
        heading="HYPOTHETICAL EXAMPLE — cash flow",
        content="",
        estimated_duration_seconds=15,
        scenes=[
            ScriptScene(
                voiceover="Suppose a hypothetical worker earns $25,000.",
                visual_prompt="calculator"),
            ScriptScene(
                voiceover="SSA's official limit is $22,320.",
                visual_prompt="SSA page"),
            ScriptScene(
                voiceover=(
                    "The verified $24,480 exempt amount leaves $520 over "
                    "that line in this hypothetical."),
                visual_prompt="subtraction chart"),
            ScriptScene(
                voiceover=(
                    "Say, hypothetically, the worker earns $30,000."),
                visual_prompt="hypothetical earnings label"),
            ScriptScene(
                voiceover=(
                    "That leaves $5,520 over the threshold."),
                visual_prompt="subtraction chart"),
            ScriptScene(
                voiceover=(
                    "Half of that is $2,760 withheld in this example."),
                visual_prompt="division chart"),
            ScriptScene(
                voiceover=(
                    "Earn a hypothetical $1,000 over the limit, and the "
                    "worked example shows $500 withheld."),
                visual_prompt="small worked example"),
        ],
    )
    draft = ScriptDraft(
        variant_id="A", brief_title=pack.topic, hook="", segments=[example])

    problems = gate_draft_against_pack(draft, pack)

    assert not any("$25,000" in p for p in problems)
    assert not any("$520" in p for p in problems)
    assert not any("$30,000" in p for p in problems)
    assert not any("$5,520" in p for p in problems)
    assert not any("$2,760" in p for p in problems)
    assert not any("$1,000" in p for p in problems)
    assert not any("$500" in p for p in problems)
    assert any("$22,320" in p for p in problems)


def test_claim_gate_rejects_repayment_metaphors_and_unsourced_monthly_spread():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test while working in 2026",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="SSA recalculates benefits to credit withheld months",
                value="",
                year_sensitive=False,
                quote=(
                    "we will recalculate your benefit amount to give you credit "
                    "for the months we withheld benefits"),
            ),
        ],
    )
    bad_lines = [
        "Think of the withheld money as an escrow account.",
        "It does not go into some general fund.",
        "Those dollars stay on your personal ledger.",
        "The rule repays your later self.",
        "The money gets folded into a bigger check later.",
        "SSA spreads the withholding across the year's checks.",
        "A smaller amount is withheld from each individual month.",
        "You cannot borrow against the withheld amount.",
        "Nobody at SSA sends a reassuring letter about this.",
        "People start cutting hours and turning down shifts.",
        "SSA's public rule does not specify a break-even timeline.",
        "There is no lump-sum payout.",
        "The penalty story spreads faster online.",
    ]
    segment = ScriptSegment(
        index=1,
        heading="What happens",
        content=" ".join(bad_lines),
        estimated_duration_seconds=30,
        scenes=[
            ScriptScene(voiceover=line, visual_prompt="benefit statement")
            for line in bad_lines
        ],
    )
    draft = ScriptDraft(
        variant_id="A", brief_title=pack.topic, hook="", segments=[segment])

    problems = gate_draft_claims_against_pack(draft, pack)

    assert any("repayment/refund" in problem for problem in problems)
    assert any("monthly-check withholding" in problem for problem in problems)
    assert any("administration" in problem for problem in problems)
    assert any("agency communication" in problem for problem in problems)
    assert any("prevalence/behavior" in problem for problem in problems)
    assert any("negative claim" in problem for problem in problems)


def test_ssa_sanitizer_tightens_hook_and_replaces_behavioral_padding():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security check shrinks while keep working in 2026",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="Benefits withheld while working are not lost",
                value="",
                year_sensitive=False,
                quote="benefits withheld while you work are not lost",
            ),
            _entry(
                evidence_id="E3",
                claim=(
                    "At full retirement age the monthly benefit increases "
                    "permanently to credit withheld months"),
                value="",
                year_sensitive=False,
                quote=(
                    "we will recalculate your benefit amount to give you "
                    "credit for the months we withheld benefits"),
            ),
        ],
    )
    hook_scenes = [
        ScriptScene(
            voiceover=(
                "This anonymous setup keeps talking without reaching the "
                "verified number or the actual rule for far too long."),
            visual_prompt="generic statement",
        )
        for _ in range(7)
    ]
    bad_lines = [
        "Cutting hours. Turning down shifts. Quitting a job they didn't actually need to quit.",
        "Draining savings early, out of fear the withheld benefit is gone for good.",
    ]
    segment = ScriptSegment(
        index=1,
        heading="THE FEAR VERSUS THE FAIR COUNTERPOINT",
        content=" ".join(bad_lines),
        estimated_duration_seconds=20,
        scenes=[
            ScriptScene(voiceover=line, visual_prompt="household budget")
            for line in bad_lines
        ],
    )
    draft = ScriptDraft(
        variant_id="A",
        brief_title=pack.topic,
        hook=" ".join(scene.voiceover for scene in hook_scenes),
        hook_scenes=hook_scenes,
        segments=[segment],
    )

    repaired, applied = sanitize_ssa_earnings_draft(draft, pack)
    hook_words = len(repaired.hook.split())
    spoken = " ".join(
        scene.voiceover
        for segment in repaired.segments
        for scene in segment.scenes
    )

    assert "overlong SSA earnings-test hook" in applied
    assert len(repaired.hook_scenes) == 5
    assert 45 <= hook_words <= 75
    assert "$24,480" in repaired.hook_scenes[0].voiceover
    assert "Cutting hours" not in spoken
    assert "Draining savings" not in spoken
    assert gate_draft_claims_against_pack(repaired, pack) == []


def test_verified_pack_builds_fact_ledger_without_model_rediscovery():
    from omnicast.compliance.fact_ledger import gate_fact_ledger

    pack = EvidencePack(
        topic="Social Security earnings test in 2026",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="SSA withholds $1 for every $2 above the limit",
                value="$1 for every $2",
                quote="we withhold $1 for every $2 above the annual limit",
            ),
        ],
    )
    script = (
        "According to SSA's 2026 page, the limit is $24,480. "
        "SSA withholds $1 for every $2 above that limit.\n\n"
        "[HYPOTHETICAL EXAMPLE — cash flow]\n"
        "Say, hypothetically, earnings are $30,000. "
        "That leaves $5,520 above the verified line."
    )

    ledger = fact_ledger_from_evidence_pack(
        script, pack, current_year=2026)
    report = gate_fact_ledger(script, ledger, current_year=2026)

    assert report.passed, report
    by_value = {entry.value: entry for entry in ledger.entries}
    assert by_value["$24,480"].source_url == _entry().source_url
    assert by_value["$30,000"].source_name == (
        "worked example (illustrative input)")
    assert by_value["$5,520"].source_name == (
        "worked example (illustrative input)")
    assert gate_ledger_against_pack(ledger, pack) == []


def test_verified_calculator_is_allowed_but_unverified_one_is_blocked():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    scene = ScriptScene(
        voiceover=(
            "SSA links an earnings test calculator to show how work earnings "
            "could affect benefit payments."),
        visual_prompt="SSA earnings test calculator link",
    )
    draft = ScriptDraft(
        variant_id="A",
        brief_title="Social Security while working",
        hook="",
        segments=[ScriptSegment(
            index=1,
            heading="Worksheet",
            content=scene.voiceover,
            estimated_duration_seconds=5,
            scenes=[scene],
        )],
    )
    base_entries = [
        _entry(evidence_id="E1"),
        _entry(
            evidence_id="E2",
            claim="SSA recalculates benefits to credit withheld months",
            value="",
            year_sensitive=False,
            quote=(
                "we will recalculate your benefit amount to give you credit "
                "for the months we withheld benefits"),
        ),
    ]
    missing = EvidencePack(
        topic="Social Security earnings test while working",
        entries=base_entries,
    )
    verified = EvidencePack(
        topic=missing.topic,
        entries=base_entries + [_entry(
            evidence_id="E3",
            claim=(
                "SSA links an earnings test calculator for people still "
                "working"),
            value="",
            year_sensitive=False,
            quote=(
                "you can use our earnings test calculator to see how your "
                "earnings could affect your benefit payments"),
        )],
    )

    assert any(
        "calculator is absent" in problem
        for problem in gate_draft_claims_against_pack(draft, missing)
    )
    assert gate_draft_claims_against_pack(draft, verified) == []


def test_ratio_in_evidence_allows_its_exact_percentage_equivalent():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test in 2026",
        entries=[
            _entry(
                evidence_id="E1",
                claim="SSA withholds $1 for every $2 over $24,480",
                value="$1 for every $2",
                quote="we withhold $1 for every $2 above $24,480",
            ),
            _entry(
                evidence_id="E2",
                claim="SSA recalculates benefits to credit withheld months",
                value="",
                year_sensitive=False,
                quote=(
                    "we will recalculate your benefit amount to give you credit "
                    "for the months we withheld benefits"),
            ),
        ],
    )
    scene = ScriptScene(
        voiceover="That is a 50 percent withholding rate above the line.",
        visual_prompt="ratio chart")
    draft = ScriptDraft(
        variant_id="A", brief_title=pack.topic, hook="",
        segments=[ScriptSegment(
            index=1, heading="The rate", content=scene.voiceover,
            estimated_duration_seconds=5, scenes=[scene])])

    assert gate_draft_against_pack(draft, pack) == []


def test_verified_spoken_thresholds_are_normalized_to_exact_digits():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test in 2026",
        entries=[
            _entry(evidence_id="E1"),
            _entry(
                evidence_id="E2",
                claim="The higher exempt amount is $65,160",
                value="$65,160",
                quote="the annual exempt amount is $65,160 in 2026",
            ),
        ],
    )
    scenes = [
        ScriptScene(
            voiceover=(
                "The lower amount is twenty-four thousand, four eighty."),
            visual_prompt="SSA page"),
        ScriptScene(
            voiceover=(
                "The higher amount is sixty-five thousand one hundred sixty."),
            visual_prompt="SSA page"),
    ]
    draft = ScriptDraft(
        variant_id="A", brief_title=pack.topic, hook="",
        segments=[ScriptSegment(
            index=1, heading="The two limits", content="",
            estimated_duration_seconds=10, scenes=scenes)])

    normalized = normalize_draft_evidence_numbers(draft, pack)
    voice = " ".join(
        scene.voiceover for scene in normalized.segments[0].scenes)

    assert "$24,480" in voice
    assert "$65,160" in voice
    assert not gate_draft_against_pack(normalized, pack)


def test_pipeline_verifies_evidence_before_writer_and_uses_real_duration_floor():
    from pathlib import Path

    import omnicast.pipeline.steps as steps

    source = Path(steps.__file__).read_text(encoding="utf-8")
    research = source.index("_evidence_pack, _evidence_cache_used = await evidence_for_topic(")
    writer = source.index("drafts = await _cw.execute(")
    assert research < writer
    assert "gate_draft_against_pack(draft, evidence_pack)" in source
    assert "_apply_evidence_gate(" in source
    assert "_TARGET_VO = spoken_word_floor(brief.target_duration_min)" in source
    assert "except RuntimeError:" in source
    assert "_TARGET_VO = 1300" not in source


def test_research_schema_accepts_common_model_key_variants():
    from omnicast.agents.evidence_research import _EvidenceDraft

    item = {
        "fact": "The annual exempt amount is $24,480",
        "figure": "$24,480",
        "source_name": "SSA exempt amounts",
        "url": "https://www.ssa.gov/oact/cola/rtea.html",
        "year": "2026",
        "year_sensitive": True,
        "verbatim_quote": "the annual exempt amount is $24,480 in 2026",
    }
    parsed = _EvidenceDraft.model_validate({
        "evidence_pack": [item, item, item]})
    assert len(parsed.entries) == 3
    assert parsed.entries[0].claim.startswith("The annual")
    assert parsed.entries[0].source_url.startswith("https://")


def test_research_schema_accepts_evidence_as_top_level_list():
    """Live pipeline output used ``evidence`` despite an otherwise valid pack."""
    from omnicast.agents.evidence_research import _EvidenceDraft

    item = {
        "claim": "Benefits withheld under the earnings test are recalculated",
        "value": "",
        "source_name": "SSA Benefits Planner",
        "source_url": (
            "https://www.ssa.gov/benefits/retirement/planner/whileworking.html"),
        "as_of": "2026",
        "year_sensitive": False,
        "quote": "we will recalculate your benefit amount",
    }
    parsed = _EvidenceDraft.model_validate({"evidence": [item, item, item]})
    assert len(parsed.entries) == 3


def test_research_schema_accepts_a_bare_entry_array():
    """Structured backends may emit the requested list without an object wrapper."""
    from omnicast.agents.evidence_research import _EvidenceDraft

    item = {
        "claim": "Benefits withheld under the earnings test are recalculated",
        "value": "",
        "source_name": "SSA Benefits Planner",
        "source_url": (
            "https://www.ssa.gov/benefits/retirement/planner/whileworking.html"),
        "as_of": "2026",
        "year_sensitive": False,
        "quote": "we will recalculate your benefit amount",
    }
    parsed = _EvidenceDraft.model_validate([item, item, item])
    assert len(parsed.entries) == 3


def test_source_evidence_coerces_numeric_year_and_value_to_text():
    parsed = SourceEvidence.model_validate({
        "claim": "The annual exempt amount changes for the current rule year",
        "value": 24480,
        "source_name": "SSA exempt amounts",
        "source_url": "https://www.ssa.gov/oact/cola/rtea.html",
        "as_of": 2026,
        "year_sensitive": True,
        "quote": "the annual exempt amount is shown for the year",
    })
    assert parsed.as_of == "2026"
    assert parsed.value == "24480"


class _FakeResponse:
    def __init__(self, url: str, status: int, text: str) -> None:
        self.url = httpx.URL(url)
        self.status_code = status
        self.text = text
        self.content = text.encode()
        self.headers = {"content-type": "text/plain; charset=utf-8"}
        self.request = httpx.Request("GET", url)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=self.request, response=self)


class _FakeAsyncClient:
    def __init__(self, responses: list[_FakeResponse], calls: list[str]) -> None:
        self._responses = responses
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url: str):
        self._calls.append(url)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_fetch_falls_back_to_reader_when_primary_blocks_bot(monkeypatch):
    source = "https://www.ssa.gov/benefits/retirement/planner/whileworking.html"
    reader = "https://r.jina.ai/" + source
    body = (
        "URL Source: " + source + "\n\nMarkdown Content:\n"
        "We will recalculate your benefit amount to give you credit.")
    calls: list[str] = []
    fake = _FakeAsyncClient([
        _FakeResponse(source, 403, "Forbidden"),
        _FakeResponse(reader, 200, body),
    ], calls)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: fake)

    text = await fetch_source_text(source)

    assert calls == [source, reader]
    assert "recalculate your benefit" in text


@pytest.mark.asyncio
async def test_fetch_rejects_model_proposed_host_before_network(monkeypatch):
    calls: list[str] = []
    fake = _FakeAsyncClient([], calls)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: fake)

    with pytest.raises(ValueError, match="allowed HTTPS primary-source"):
        await fetch_source_text("https://attacker.example/internal")

    assert calls == []


def test_value_phrase_is_verified_by_its_numeric_atoms():
    entry = _entry(
        claim="SSA deducts one dollar for every two dollars above the limit",
        value="$1 for every $2",
        quote=(
            "we deduct $1 from your benefit payments for every $2 you earn "
            "above the annual limit"),
    )
    page = (
        "In 2026, if you are under full retirement age for the entire year, we deduct "
        "$1 from your benefit payments for every $2 you earn above the annual "
        "limit.")
    assert verify_entry_against_text(
        entry, page, current_year=2026) == []


def test_supporting_quote_is_extracted_from_fetched_text_not_model_memory():
    entry = _entry(
        claim=(
            "SSA recalculates benefits at full retirement age to credit months "
            "that were withheld"),
        value="",
        year_sensitive=False,
        quote="This paraphrase was never printed on the page",
    )
    page = (
        "When you reach full retirement age, we will recalculate your benefit "
        "amount to give you credit for the months we reduced or withheld "
        "benefits due to your excess earnings. Starting with that month, your "
        "earnings no longer reduce your benefits.")

    quote = extract_supporting_quote(entry, page)

    assert quote
    assert quote.lower() in page.lower()
    repaired = entry.model_copy(update={
        "quote": quote,
        "quote_extracted_from_page": True,
    })
    assert verify_entry_against_text(
        repaired, page, current_year=2026) == []


def test_quote_extractor_rejects_unrelated_page_even_if_a_year_matches():
    entry = _entry(
        claim="SSA recalculates withheld retirement benefits",
        value="2026",
        quote="not a real source quote",
    )
    page = "The 2026 Medicare handbook explains hospital insurance enrollment."
    assert extract_supporting_quote(entry, page) == ""


@pytest.mark.asyncio
async def test_ssa_earnings_adapter_builds_verified_pack_without_llm(monkeypatch):
    from omnicast.agents.evidence_research import EvidenceResearchAgent

    working = (
        "If you are under full retirement age for the entire year, we deduct "
        "$1 from your benefit payments for every $2 you earn above the annual "
        "limit. For 2026, that limit is $24,480. "
            "In the year you reach full retirement age, we deduct $1 in benefits "
            "for every $3 you earn above a different limit. In 2026, this limit on "
            "your earnings is $65,160. We only count your earnings up to the "
            "month before you reach your full retirement age, not your earnings "
            "for the entire year. "
        "Starting with the month you reach full retirement age, there is no "
        "limit on how much you can earn and still receive your benefits. "
        "If your earnings will be more than the limit for the year and you will "
        "receive retirement benefits for part of the year, we have a special "
        "rule that applies to earnings for one year. The special rule lets us "
        "pay a full Social Security benefit for any whole month we consider "
        "you retired, regardless of your yearly earnings. "
        "When we figure out how much to deduct from your benefits, we count "
        "only the wages you make from your job or your net profit if you're "
        "self-employed. We include bonuses, commissions, and vacation pay. "
        "We don't count pensions, annuities, investment income, interest, "
        "veterans benefits, or other government or military retirement benefits. "
        "If you are eligible for retirement benefits this year and are still "
        "working, you can use our earnings test calculator to see how your "
        "earnings could affect your benefit payments."
    )
    exempt = (
        'It is important to note that any benefits withheld while you continue '
        'to work are not "lost". Once you reach NRA, your monthly benefit will '
        "be increased permanently to account for the months in which benefits "
        "were withheld. Exempt Amounts for 2026."
    )

    async def fake_fetch(url: str, **kwargs):
        return exempt if "rtea.html" in url else working

    monkeypatch.setattr(
        "omnicast.agents.evidence_research.fetch_source_text", fake_fetch)
    llm = AsyncMock()
    agent = EvidenceResearchAgent(llm=llm)

    pack = await agent.execute(
        "What Social Security withholds in 2026 while working before full "
        "retirement age",
        current_year=2026,
    )

    assert len(pack.entries) == 10
    assert any("net self-employment" in entry.claim for entry in pack.entries)
    assert any("earnings test calculator" in entry.claim for entry in pack.entries)
    assert {entry.value for entry in pack.entries} >= {
        "$24,480", "$65,160", "$1 for every $2", "$1 for every $3"}
    llm.complete_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_saved_pack_is_refetched_and_reverified_without_an_llm(monkeypatch):
    url = "https://www.ssa.gov/oact/cola/rtea.html"
    page = (
        "For 2026, the annual exempt amount is $24,480. "
        "When you reach full retirement age, we will recalculate your benefit "
        "amount to give you credit for months we reduced or withheld benefits.")
    calls: list[str] = []

    async def fake_fetch(source_url: str, **kwargs):
        calls.append(source_url)
        return page

    monkeypatch.setattr(
        "omnicast.agents.evidence_research.fetch_source_text", fake_fetch)
    pack = EvidencePack(
        topic="earnings test",
        entries=[
            _entry(evidence_id="E1", source_url=url),
            _entry(
                evidence_id="E2",
                claim=(
                    "SSA recalculates benefits to credit months that were "
                    "withheld"),
                value="",
                source_url=url,
                year_sensitive=False,
                quote="a model paraphrase that is not on the page",
            ),
        ],
    )

    refreshed = await reverify_evidence_pack(pack, current_year=2026)

    assert calls == [url]  # one fetch for two claims on the same page
    assert len(refreshed.entries) == 2
    assert refreshed.entries[1].quote_extracted_from_page is True


@pytest.mark.asyncio
async def test_same_topic_cache_skips_research_agent(
        monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    url = "https://www.ssa.gov/oact/cola/rtea.html"
    page = (
        "For 2026, the annual exempt amount is $24,480. "
        "The 2026 annual exempt amount is $24,480.")

    async def fake_fetch(source_url: str, **kwargs):
        return page

    monkeypatch.setattr(
        "omnicast.agents.evidence_research.fetch_source_text", fake_fetch)
    pack = EvidencePack(
        topic="earnings test",
        entries=[
            _entry(evidence_id="E1", source_url=url),
            _entry(
                evidence_id="E2",
                claim="The 2026 annual exempt amount remains $24,480",
                source_url=url,
            ),
        ],
    )
    path = tmp_path / "evidence.json"
    path.write_text(pack.model_dump_json(), encoding="utf-8")
    agent = AsyncMock()
    agent.execute.side_effect = AssertionError("research LLM should not run")

    loaded, used_cache = await evidence_for_topic(
        agent, "earnings test", path)

    assert used_cache is True
    assert len(loaded.entries) == 2
    agent.execute.assert_not_awaited()


def test_draft_gate_uses_backstage_example_metadata_not_spoken_template():
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    pack = EvidencePack(
        topic="Social Security earnings test in 2026",
        entries=[_entry(evidence_id="E1"), _entry(evidence_id="E2")],
    )
    scenes = [
        ScriptScene(
            voiceover="Denise earns $30,000 in 2026.",
            visual_prompt="Denise worksheet"),
        ScriptScene(
            voiceover="$5,520 is above the verified limit in this example.",
            visual_prompt="worked calculation"),
        ScriptScene(
            voiceover="Half is $2,760 on Denise's worksheet.",
            visual_prompt="worked calculation halved"),
    ]
    draft = ScriptDraft(
        variant_id="A",
        brief_title=pack.topic,
        hook="Denise checks her worksheet.",
        segments=[ScriptSegment(
            index=1,
            heading="DENISE'S KITCHEN-TABLE EXAMPLE",
            content=" ".join(scene.voiceover for scene in scenes),
            estimated_duration_seconds=20,
            scenes=scenes,
        )],
    )

    assert gate_draft_against_pack(draft, pack) == []


def test_fact_ledger_uses_example_metadata_without_spoken_disclaimer():
    pack = EvidencePack(
        topic="Social Security earnings test in 2026",
        entries=[_entry(evidence_id="E1"), _entry(evidence_id="E2")],
    )
    script = (
        "According to SSA, the 2026 limit is $24,480.\n\n"
        "[DENISE KITCHEN-TABLE EXAMPLE]\n"
        "Denise earns $30,000. That leaves $5,520 above the line."
    )

    ledger = fact_ledger_from_evidence_pack(
        script, pack, current_year=2026)
    by_value = {entry.value: entry for entry in ledger.entries}

    assert by_value["$30,000"].source_name == (
        "worked example (illustrative input)")
    assert by_value["$5,520"].source_name == (
        "worked example (illustrative input)")
