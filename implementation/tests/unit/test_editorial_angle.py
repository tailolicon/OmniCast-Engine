"""An angle has to be a claim, and the script has to keep it.

Both halves matter and both were missing. Asked for a "thesis", a model
returns the topic with a verb glued on, and every downstream gate passes it —
the approved video that the operator rejected scored 8.23 while arguing
nothing at all.
"""

from __future__ import annotations

import pytest

from omnicast.agents.editorial_angle import (
    EditorialAngle,
    EditorialAnglePlanner,
    _EditorialAngleDraft,
    angle_is_delivered,
    check_angle,
)

GOOD = EditorialAngle(
    thesis="The earnings test is not a tax, and treating it as one costs "
           "working retirees years of benefits they get back later",
    against="Most people believe money withheld by the earnings test is gone "
            "for good",
    stake="A retiree who quits work to dodge it gives up income for nothing",
    turn="The moment they see the withheld months returned at full retirement age",
    walk_away="Withheld is not lost — it comes back recalculated",
    evidence_ids=("SSA-RS-2026-01", "SSA-EARN-2026"),
)


def test_a_real_argument_passes():
    assert check_angle(GOOD) == []


def test_a_conditional_thesis_about_an_unpassed_bill_is_a_claim():
    # Live failure 2026-08-01: a news-frame thesis in modal mood ("would not
    # hand… would only stop…") was rejected twice as "no assertive verb"
    # because _CLAIM_VERBS only listed indicative verbs. Every rule-change
    # video argues about a hypothetical, so modals must count as claims.
    news = EditorialAngle(
        thesis="Repealing the earnings limit would not hand retirees new "
               "money; it would only stop withholding benefits that current "
               "rules already restore later",
        against="If this bill passes, working retirees finally stop losing "
                "benefit money",
        stake="Retirees planning 2026 around an unpassed bill spend money "
              "that cannot arrive before 2027",
        turn="The identically named 2000 Act already repealed the test above "
             "full retirement age",
        walk_away="Judge the bill as simplification, not found money",
        evidence_ids=("N1", "N3"))
    assert not [p for p in check_angle(news) if "assertive verb" in p]


def test_a_topic_with_a_verb_is_not_a_thesis():
    bad = EditorialAngle(
        thesis="What the 2026 earnings test is and how it works",
        against="x", stake="y", turn="z", walk_away="w", evidence_ids=("a",))
    problems = check_angle(bad)
    assert any("topic" in p for p in problems)


def test_a_question_commits_to_nothing():
    bad = EditorialAngle(
        thesis="Does the earnings test really reduce your lifetime benefit?",
        against="x", stake="y", turn="z", walk_away="w", evidence_ids=("a",))
    assert any("question" in p for p in check_angle(bad))


def test_hedging_to_death_is_not_a_position():
    bad = EditorialAngle(
        thesis="The right filing age is different for everyone and it depends "
               "on your own situation",
        against="x", stake="y", turn="z", walk_away="w", evidence_ids=("a",))
    assert any("hedges" in p for p in check_angle(bad))


def test_ymyl_a_thesis_may_not_instruct_the_viewer_to_act():
    """The line this niche cannot cross. An angle wants to cross it, because
    'you should claim at 70' is a far punchier thesis than anything true."""
    bad = EditorialAngle(
        thesis="You should claim Social Security at 70 because the credits "
               "are worth more than the early years",
        against="x", stake="y", turn="z", walk_away="w", evidence_ids=("a",))
    assert any("YMYL" in p for p in check_angle(bad))


def test_ymyl_check_covers_the_walk_away_line_too():
    bad = EditorialAngle(
        thesis=GOOD.thesis, against=GOOD.against, stake=GOOD.stake,
        turn=GOOD.turn,
        walk_away="Make sure you file before your birthday",
        evidence_ids=("a",))
    assert any("walk-away instructs" in p for p in check_angle(bad))


def test_an_argument_needs_something_to_argue_with():
    bad = EditorialAngle(thesis=GOOD.thesis, against="", stake="y", turn="z",
                         walk_away="w", evidence_ids=("a",))
    assert any("push against" in p for p in check_angle(bad))


def test_against_that_merely_restates_the_thesis_is_rejected():
    bad = EditorialAngle(thesis=GOOD.thesis, against=GOOD.thesis, stake="y",
                         turn="z", walk_away="w", evidence_ids=("a",))
    assert any("restates" in p for p in check_angle(bad))


def test_a_claim_with_no_evidence_is_an_opinion():
    bad = EditorialAngle(thesis=GOOD.thesis, against=GOOD.against,
                         stake=GOOD.stake, turn=GOOD.turn,
                         walk_away=GOOD.walk_away, evidence_ids=())
    assert any("ledger evidence" in p for p in check_angle(bad))


def test_a_correct_explanation_that_never_argues_the_claim_fails_delivery():
    """This is the shape of the rejected video: every fact right, the thesis
    nowhere."""
    script = (
        "Today we are looking at Social Security rules for 2026. "
        "The annual limit changed this year. Benefits are calculated from your "
        "highest thirty five years of indexed wages. There are forms to file "
        "and deadlines to watch. Many rules apply to different situations. "
        "Thanks for watching and we will see you next time. "
    ) * 6
    problems = angle_is_delivered(GOOD, script)
    assert any("explains the topic" in p for p in problems)


def test_a_script_that_argues_its_claim_passes():
    script = (
        "The earnings test is not a tax. That is the whole point of today. "
        "Money withheld by the earnings test is not lost, and a working "
        "retiree who quits to dodge the earnings test gives up income for "
        "nothing. " +
        "We will walk through what withheld actually means. " * 8 +
        "At full retirement age the withheld months are returned, "
        "recalculated. The earnings test withheld amount comes back. " +
        "So remember: withheld is not lost — it comes back recalculated."
    )
    assert angle_is_delivered(GOOD, script) == []


def test_a_claim_buried_in_the_last_minute_still_fails():
    script = ("Here is some general background about retirement planning. " * 40
              + "The earnings test is not a tax and withheld money is not lost; "
                "it comes back recalculated at full retirement age.")
    assert any("does not surface early" in p
               for p in angle_is_delivered(GOOD, script))


_LEDGER = {"ledger": {"entries": [
    {"value": "benefit recalculation at FRA", "claim": "recalculated at FRA",
     "source_name": "SSA Publication No. 05-10069",
     "source_url": "https://www.ssa.gov/pubs/EN-05-10069.pdf"},
    {"value": "$24,480", "claim": "2026 exempt amount",
     "source_name": "SSA 2026 RTEA",
     "source_url": "https://www.ssa.gov/oact/cola/rtea.html"},
    {"value": "$7,760", "claim": "Carol's withheld benefit",
     "source_name": "worked example (hypothetical)", "source_url": ""},
]}}


def test_evidence_ids_must_resolve_to_the_ledger():
    """Otherwise the field is decoration: check_angle can only see that the
    tuple is non-empty, so any three strings would pass as 'evidence'."""
    from omnicast.agents.editorial_angle import verify_evidence

    ok = EditorialAngle(thesis=GOOD.thesis, against=GOOD.against,
                        stake=GOOD.stake, turn=GOOD.turn,
                        walk_away=GOOD.walk_away,
                        evidence_ids=("benefit recalculation at FRA", "$24,480"))
    assert verify_evidence(ok, _LEDGER) == []

    bad = EditorialAngle(thesis=GOOD.thesis, against=GOOD.against,
                         stake=GOOD.stake, turn=GOOD.turn,
                         walk_away=GOOD.walk_away,
                         evidence_ids=("SSA-DEFINITELY-REAL-2026",))
    assert any("matches no ledger entry" in p for p in verify_evidence(bad, _LEDGER))


def test_a_hypothetical_cannot_ground_a_claim():
    """The rejected video's chart credited "SSA 2025" for figures that were
    invented for the example. The same confusion at thesis level would let the
    channel argue from its own illustration."""
    from omnicast.agents.editorial_angle import verify_evidence

    a = EditorialAngle(thesis=GOOD.thesis, against=GOOD.against,
                       stake=GOOD.stake, turn=GOOD.turn,
                       walk_away=GOOD.walk_away, evidence_ids=("$7,760",))
    assert any("worked example" in p for p in verify_evidence(a, _LEDGER))


def test_the_gate_runs_before_generation_not_after():
    """A validated angle is worth a second; discovering it was a topic after a
    30-minute generation is worth nothing. Pinned at source level for the same
    reason the writer's own gate is: an audit once reverted both halves of an
    equivalent check and the suite stayed green."""
    from pathlib import Path

    import omnicast.agents.editorial_angle as ea

    cli = (Path(ea.__file__).resolve().parents[3] / "scripts"
           / "run_phase2_finance.py").read_text(encoding="utf-8")
    i_check = cli.index("check_angle(angle_obj)")
    i_run = cli.index("await _step_script(")
    assert i_check < i_run, "the angle must be validated before generation runs"
    assert "angle_is_delivered" in cli, "nothing verifies the draft kept the claim"
    # the constraint leads the accumulated steering text
    assert "as_prompt_block() + \"\\n\" + brief_text" in cli


def test_prompt_block_carries_the_constraint_and_the_ymyl_line():
    block = GOOD.as_prompt_block()
    assert GOOD.thesis in block and GOOD.against in block
    assert "not tell the viewer what to do" in block.replace("Do NOT", "not")


def test_full_editorial_angle_requires_counterpoint_reactions_and_questions():
    """A thesis alone still produces a correct bulletin. The full contract
    carries the narrator's interpretation through the whole video."""
    problems = check_angle(GOOD, require_full=True)
    joined = " ".join(problems)
    assert "counterpoint" in joined
    assert "reaction" in joined
    assert "driving question" in joined
    assert "ending question" in joined


def test_full_angle_rejects_fabricated_experience_but_allows_attitude():
    fake = EditorialAngle(
        thesis=GOOD.thesis, against=GOOD.against, stake=GOOD.stake,
        turn=GOOD.turn, walk_away=GOOD.walk_away,
        evidence_ids=GOOD.evidence_ids,
        counterpoint="Cash flow can still be painful in the meantime",
        narrator_attitude="In my practice, my clients always get this wrong",
        reaction_beats=("This number is frustrating", "The recalculation changes the story"),
        felt_metaphor="A locked drawer rather than a shredder",
        metaphor_callback="The drawer opens again later",
        driving_questions=("What is held back?", "What happens at full retirement age?"),
        ending_question="Does withheld still sound the same as lost?",
    )
    assert any("fabricated" in p for p in check_angle(fake, require_full=True))

    honest = EditorialAngle(
        thesis=fake.thesis, against=fake.against, stake=fake.stake,
        turn=fake.turn, walk_away=fake.walk_away,
        evidence_ids=fake.evidence_ids,
        counterpoint=fake.counterpoint,
        narrator_attitude="calmly irritated by a rule whose name misleads people",
        reaction_beats=fake.reaction_beats,
        felt_metaphor=fake.felt_metaphor,
        metaphor_callback=fake.metaphor_callback,
        driving_questions=fake.driving_questions,
        ending_question=fake.ending_question,
    )
    assert check_angle(honest, require_full=True) == []


@pytest.mark.asyncio
async def test_automatic_planner_can_only_select_supplied_evidence_ids():
    from unittest.mock import AsyncMock

    from omnicast.agents.editorial_angle import _EditorialAngleDraft
    from omnicast.llm.client import LLMClient, LLMResponse
    from omnicast.models.enums import Market, Niche, TopicSource
    from omnicast.models.script import TopicBrief

    llm = AsyncMock(spec=LLMClient)
    llm.complete_structured.return_value = (
        LLMResponse(content="{}", model="test", input_tokens=1,
                    output_tokens=1, cost_usd=0, stop_reason="end_turn"),
        _EditorialAngleDraft(
            thesis="The earnings test is not a tax, and its misleading name "
                   "turns a temporary hold into a permanent-loss story",
            against="Every withheld benefit dollar is gone forever",
            stake="A retiree may judge work from a false lifetime-loss model",
            turn="The supplied SSA rule says withheld months are recalculated later",
            walk_away="Withheld and permanently lost are different claims",
            evidence_ids=["E1"],
            counterpoint="The temporary cash-flow loss can still hurt",
            narrator_attitude="calmly irritated by a name that hides the mechanism",
            reaction_beats=[
                "After E1, pause on how different withheld sounds from lost",
                "After the recalculation, acknowledge that timing still matters",
            ],
            felt_metaphor="A locked drawer, not a shredder",
            metaphor_callback="Return to the drawer when the recalculation appears",
            driving_questions=[
                "What is actually withheld?",
                "What happens to it at full retirement age?",
            ],
            ending_question="Does withheld still sound like permanently lost?",
        ),
    )
    brief = TopicBrief(
        title="The Social Security earnings test",
        niche=Niche.FINANCE, market=Market.US, source=TopicSource.MANUAL,
        key_points=["SSA says withheld months are recalculated at full retirement age"],
    )

    planned = await EditorialAnglePlanner(llm).execute(brief)
    assert planned.evidence_ids == ("E1",)
    sent = llm.complete_structured.call_args.kwargs["messages"][1]["content"]
    assert "E1: SSA says withheld months" in sent
    assert "ONLY ids from ALLOWED INPUT ANCHORS" in sent
    assert "thesis, against, stake, turn" in sent
    assert "walk_away, evidence_ids" in sent
    assert "stake is the concrete cost" in sent
    assert "turn is the evidence-led reveal" in sent
    assert "dollar-for-dollar repayment" in sent
    assert "reaction may interpret" in sent


def test_angle_schema_normalizes_live_model_key_and_list_variants():
    raw = {
        "claim": (
            "Withheld Social Security benefits are delayed cash flow, not a "
            "permanent confiscation"),
        "pushes_against": "Every withheld dollar is gone forever",
        "why_it_matters": (
            "A worker may make a permanent claiming decision from the wrong "
            "mental model"),
        "reveal": (
            "SSA credits withheld months when it recalculates at full "
            "retirement age"),
        "takeaway": "A painful delay and a permanent loss are not the same",
        "evidence_anchors": ["E1", "E2"],
        "fair_counterpoint": (
            "The temporary cash-flow gap can still be genuinely damaging"),
        "stance": "calmly irritated by a rule whose name hides its mechanism",
        "reaction_beats": [
            {"fact": "E1", "reaction": f"reaction {i}"}
            for i in range(6)
        ],
        "metaphor": "A locked drawer, not a shredder",
        "callback": "Open the drawer again at recalculation",
        "driving_questions": [f"Question {i}?" for i in range(6)],
        "closing_question": (
            "Would you still call it a tax after seeing the recalculation?"),
    }

    parsed = _EditorialAngleDraft.model_validate(raw)

    assert parsed.stake.startswith("A worker")
    assert parsed.turn.startswith("SSA credits")
    assert parsed.walk_away.startswith("A painful")
    assert parsed.evidence_ids == ["E1", "E2"]
    assert len(parsed.reaction_beats) == 4
    assert parsed.reaction_beats[0] == "E1: reaction 0"
    assert len(parsed.driving_questions) == 4


def test_angle_schema_normalizes_semantic_field_names_from_pipeline_model():
    """Structured-output providers still paraphrase JSON property names.

    These are semantically unambiguous variants seen in live planning calls;
    rejecting the entire run wastes a paid call without improving the angle.
    """
    raw = {
        "thesis": "Withholding creates a delay, not permanent benefit loss",
        "against": "A stopped check means the benefit vanished",
        "what_the_viewer_risks": "A false mental model can distort a work decision",
        "narrative_turn": "At full retirement age SSA recalculates the benefit",
        "mental_model_to_keep": "Cash-flow pain and lifetime loss are different",
        "evidence_ids": ["E4"],
        "counterpoint": "The near-term cash-flow loss remains real",
        "narrator_attitude": "irritated by a misleading label",
        "reaction_beats": ["E1 changes the immediate check", "E4 changes the lifetime story"],
        "felt_metaphor": "A locked drawer, not a shredder",
        "metaphor_callback": "The drawer opens at recalculation",
        "driving_questions": ["What is withheld?", "What happens later?"],
        "ending_question": "Does withheld still sound like lost?",
    }

    parsed = _EditorialAngleDraft.model_validate(raw)

    assert parsed.stake.startswith("A false mental model")
    assert parsed.turn.startswith("At full retirement age")
    assert parsed.walk_away.startswith("Cash-flow pain")
