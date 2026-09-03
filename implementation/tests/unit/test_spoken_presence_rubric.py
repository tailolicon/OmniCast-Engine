"""Spoken-presence gate — the anti-"essay read aloud" layer.

The first shipped video was accurate, sourced, codex-approved… and voiceless:
6 companionship words in 2,471, two reaction beats, one invitation, eighty
em-dashes. The operator rejected it on exactly that. These tests keep the
machine half of that judgement permanent.
"""

from __future__ import annotations

from types import SimpleNamespace

from omnicast.agents.rubrics import finance_explainer as fe

ESSAY = (
    "Work part-time in 2026, earn $40,000, and Social Security will hold back "
    "$7,760 of your own benefit. That is the earnings test in action — one "
    "dollar withheld for every two dollars earned above the annual limit. The "
    "Social Security Administration's 2026 fact sheet sets that $24,480 line, "
    "and it trips up more working retirees than almost any other rule. The "
    "retirement test goes back to the original 1935 Act — the 1939 amendments "
    "added an explicit dollar threshold, and the structure survived six "
    "decades of amendment. Only wages and net self-employment income count "
    "toward the limit, so pension checks, dividends and required minimum "
    "distributions are all outside it entirely."
) * 6

SPOKEN = (
    "Let's start with a number that stopped me: $7,760. That is what Social "
    "Security holds back from a retiree earning $40,000 in 2026 — and honestly, "
    "most people never see it coming. Picture a toll booth sitting on your "
    "paycheck. We're going to walk through both lanes together, because which "
    "one you're waved into changes everything. Look at this figure for a "
    "second: $24,480. That's the 2026 line, straight from SSA's fact sheet. "
    "Here's what gets me — the rule isn't a penalty, it's a delay, and nobody "
    "says that out loud. That's the mechanism. Now the part that costs money. "
    "So we've got the history. Next up: what actually counts as earnings, "
    "because it isn't what you'd guess. Try this — grab your last statement "
    "and check one line. We'll come back to Carol's four missing checks in a "
    "moment, and yes, she got most of it back."
) * 6


def test_essay_register_is_visible_to_the_semantic_critic():
    """Texture is evidence for the judge, not a machine verdict."""
    _flags, caps = fe.finance_slop_signals(ESSAY)
    assert "spoken_presence" not in caps
    stats = fe.finance_presence_diagnostics(ESSAY)
    assert stats["reaction_phrases_per_1k"] < 2
    assert stats["companionship_per_1k"] < 2


def test_em_dash_prose_is_flagged():
    """The shipped script carried 80 em-dashes in 2,471 words — beautiful on
    paper, airless in the mouth."""
    dashy = ("The rule applies — and it applies quietly — to every retiree "
             "under full retirement age — which is most of them. ") * 30
    flags, caps = fe.finance_slop_signals(dashy)
    assert "em-dash" in " ".join(flags), flags
    assert caps.get("anti_ai_cliche", 99) <= 3
    assert "spoken_presence" not in caps


def test_spoken_register_passes_clean():
    flags, caps = fe.finance_slop_signals(SPOKEN)
    assert "spoken_presence" not in caps, (caps, flags)


def test_spoken_presence_is_a_scored_dimension():
    assert fe.VO_DIMS["spoken_presence"] >= 10
    assert sum(fe.VO_DIMS.values()) == 70
    assert sum(fe.PROD_DIMS.values()) == 30
    rubric = fe.dimension_rubric()
    assert "spoken_presence" in rubric
    # the six mechanics must be spelled out for the judge
    for cue in ("COMPANIONSHIP", "REACTION", "INVITATION", "MOUTH-LANGUAGE",
                "SIGNPOSTING", "FELT METAPHOR"):
        assert cue in rubric, cue
    assert "EARNED SUBSCRIBE" in rubric
    assert "channel promise" in rubric
    assert "generic CTA" in rubric
    assert "never invent a calculator" in rubric
    assert "Do not demand one universal example shape" in rubric
    assert "recurring human-anchor contract" in rubric
    assert "tax/Medicare/spousal effect" in rubric
    assert "SSA calculator shows your exact number" not in rubric


def test_detectors_are_length_normalised():
    """A longer script must not pass simply by accumulating raw counts."""
    short_spoken = ("Let's look at this together. Picture the booth. "
                    "Here's what gets me: $7,760. That's the mechanism. "
                    "Now the part that costs money. We'll walk through it.")
    short = fe.finance_presence_diagnostics(short_spoken)
    long = fe.finance_presence_diagnostics(short_spoken * 10)
    delta = abs(short["companionship_per_1k"]
                - long["companionship_per_1k"])
    assert delta / short["companionship_per_1k"] < 0.05


def test_presence_keywords_are_diagnostics_not_a_machine_score():
    """Keyword counts cannot tell whether a narrator has a point of view.

    Repeating "honestly / let's / picture this" can game every old detector
    while making a worse script. Deterministic code may report texture, but it
    must not hard-cap the semantic editorial dimension.
    """
    stuffed = (
        "Honestly, let's picture this together. Look at this. That's the "
        "mechanism. Now the next part. Read that again. "
    ) * 100
    _flags, caps = fe.finance_slop_signals(stuffed)
    assert "spoken_presence" not in caps


def test_human_anchor_contract_requires_a_carried_transparent_story():
    brief = (
        "THE HUMAN ANCHOR\n"
        "Let's call her Denise. She is hypothetical, not a client.\n"
        "HUMAN_ANCHOR_REQUIRED_DETAILS: garden center | apron | "
        "grocery list | furnace estimate | kitchen table"
    )
    valid = SimpleNamespace(
        hook=(
            "Let's call her Denise. She is hypothetical. Her garden-center "
            "apron sits on the kitchen table beside a grocery list."
        ),
        segments=[
            SimpleNamespace(
                heading="THE CALCULATION",
                content=(
                    "Denise works three mornings a week. Her pay stub and "
                    "furnace estimate make the current budget concrete."
                ),
            ),
            SimpleNamespace(
                heading="THE LATER TURN",
                content=(
                    "Denise cannot assign a later recalculation to a bill due "
                    "this month."
                ),
            ),
        ],
        outro="What would Denise need on today's calendar?",
    )
    arithmetic_only = SimpleNamespace(
        hook="The limit is $24,480.",
        segments=[
            SimpleNamespace(
                heading="HYPOTHETICAL EXAMPLE",
                content="Say, hypothetically, someone earns $30,000.",
            ),
        ],
        outro="That is the answer.",
    )

    assert fe.human_anchor_contract_problems(valid, brief) == []
    natural_framing = SimpleNamespace(
        hook=(
            "Denise works three mornings at a garden center. Her apron sits "
            "on the kitchen table beside a grocery list and furnace estimate."
        ),
        segments=[
            SimpleNamespace(
                heading="THE THRESHOLD",
                content=(
                    "Denise puts the limit beside her current household budget."
                ),
            ),
            SimpleNamespace(
                heading="WORKED EXAMPLE",
                content=(
                    "Her garden-center wages total $30,000. Denise uses "
                    "the worksheet, then returns to the furnace estimate."
                ),
            ),
            SimpleNamespace(
                heading="THE LATER TURN",
                content=(
                    "Back at Denise's kitchen table, the later recalculation "
                    "does not pay today's grocery bill."
                ),
            ),
        ],
        outro="We keep reading the fine print together.",
    )
    assert fe.human_anchor_contract_problems(natural_framing, brief) == []

    problems = fe.human_anchor_contract_problems(arithmetic_only, brief)
    assert any("operator requested anchor Denise" in problem
               for problem in problems)

    pasted_name = SimpleNamespace(
        hook="The limit affects today's grocery bill.",
        segments=[
            SimpleNamespace(
                heading="THE LIMIT",
                content=(
                    "Let's call her Denise. She is hypothetical. Denise sees "
                    "the threshold."
                ),
            ),
            SimpleNamespace(
                heading="HYPOTHETICAL EXAMPLE",
                content="Denise earns $30,000 and we do the arithmetic.",
            ),
        ],
        outro="That is the answer.",
    )
    pasted_problems = fe.human_anchor_contract_problems(pasted_name, brief)
    assert any("absent from the hook" in problem
               for problem in pasted_problems)
    assert any("disappears after the worked example" in problem
               for problem in pasted_problems)
    assert any("life-detail groups" in problem
               for problem in pasted_problems)
    assert any("requested recurring anchor details" in problem
               for problem in pasted_problems)

    rubric = fe.dimension_rubric()
    assert "Do NOT award points by counting" in rubric
    assert "thesis" in rubric.lower()
    assert "counterpoint" in rubric.lower()
