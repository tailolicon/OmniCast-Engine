"""Tests for Critic Agent and Thinking Agent."""

import pytest
from unittest.mock import AsyncMock

from omnicast.agents.critic import (
    CriticAgent, VO_DIMS, PROD_DIMS, VO_PASS, PROD_PASS,
    HUB_THRESHOLD, SPOKE_THRESHOLD,
)
from omnicast.agents.thinking import ThinkingAgent
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.models.script import (
    TopicBrief, ScriptDraft, ScriptSegment, CriticFeedback, CriticDimension,
)
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.shared.errors import AgentError


@pytest.fixture
def mock_llm() -> AsyncMock:
    return AsyncMock(spec=LLMClient)


@pytest.fixture
def sample_brief() -> TopicBrief:
    return TopicBrief(
        title="Investment Tips",
        niche=Niche.FINANCE,
        market=Market.US,
        source=TopicSource.GOOGLE_TRENDS,
    )


@pytest.fixture
def sample_draft() -> ScriptDraft:
    return ScriptDraft(
        variant_id="A",
        brief_title="Investment Tips",
        hook="90% of traders lose money in their first year.",
        segments=[
            ScriptSegment(index=0, heading="Intro", content="Let me explain...",
                          estimated_duration_seconds=25, has_pattern_interrupt=True),
            # Real spoken text long enough to clear the mid-roll word floor (the
            # length gate counts ACTUAL words, not the declared word_count).
            ScriptSegment(index=1, heading="Mistake 1",
                          content=("Overtrading quietly drains your account every single day. " * 220),
                          estimated_duration_seconds=80, has_pattern_interrupt=True),
        ],
        outro="Subscribe for more.",
        word_count=1500,
        estimated_duration_seconds=600,
    )


class TestThinkingAgent:
    async def test_name(self, mock_llm):
        agent = ThinkingAgent(llm=mock_llm)
        assert agent.name == "thinking"

    async def test_execute_returns_notes(self, mock_llm, sample_draft):
        mock_llm.complete.return_value = LLMResponse(
            content="Weak transition between segments 1 and 2.",
            model="claude-haiku-4-5",
            input_tokens=200, output_tokens=50,
            cost_usd=0.0004, stop_reason="end_turn",
        )
        agent = ThinkingAgent(llm=mock_llm)
        notes = await agent.execute(sample_draft)
        assert isinstance(notes, str)
        assert len(notes) > 0

    async def test_execute_error(self, mock_llm, sample_draft):
        mock_llm.complete.side_effect = AgentError("Failed")
        agent = ThinkingAgent(llm=mock_llm)
        with pytest.raises(AgentError):
            await agent.execute(sample_draft)


class TestCriticAgent:
    async def test_name(self, mock_llm):
        critic = CriticAgent(llm=mock_llm)
        assert critic.name == "critic"

    async def test_scoring_rubric_sums_100(self):
        assert sum(VO_DIMS.values()) + sum(PROD_DIMS.values()) == 100
        assert sum(VO_DIMS.values()) == 70
        assert sum(PROD_DIMS.values()) == 30
        assert VO_PASS == 53   # 75% of 70
        assert PROD_PASS == 23  # 75% of 30

    async def test_execute_approved(self, mock_llm, sample_draft, sample_brief):
        # VO group: 25+13+9+9+5+4 = 65 | Prod group: 20+4 = 24 | total = 89
        feedback = CriticFeedback(
            variant_id="A",
            total_score=89,
            voiceover_score=65,
            production_score=24,
            dimensions=[
                CriticDimension(name="hook_quality",        score=25, max_score=25),
                CriticDimension(name="anti_ai_cliche",      score=13, max_score=15),
                CriticDimension(name="retention_structure", score=9,  max_score=10),
                CriticDimension(name="human_editorial",     score=9,  max_score=10),
                CriticDimension(name="niche_compliance",    score=5,  max_score=5),
                CriticDimension(name="pacing_compliance",   score=4,  max_score=5),
                CriticDimension(name="visual_concreteness", score=20, max_score=25),
                CriticDimension(name="sfx_appropriateness", score=4,  max_score=5),
            ],
            approved=True,
        )
        mock_llm.complete_structured.return_value = (
            LLMResponse(
                content="{}", model="claude-sonnet-4-6",
                input_tokens=800, output_tokens=200,
                cost_usd=0.005, stop_reason="end_turn",
            ),
            feedback,
        )
        critic = CriticAgent(llm=mock_llm)
        result = await critic.execute(sample_draft, sample_brief, threshold=SPOKE_THRESHOLD)
        assert isinstance(result, CriticFeedback)
        assert result.approved is True
        assert result.voiceover_score == 65
        assert result.production_score == 24
        assert result.total_score == 89

    async def test_execute_rejected(self, mock_llm, sample_draft, sample_brief):
        feedback = CriticFeedback(
            variant_id="A",
            total_score=55,
            approved=False,
            rejection_reasons=["Generic hook"],
            specific_fixes=["Use a specific statistic"],
        )
        mock_llm.complete_structured.return_value = (
            LLMResponse(
                content="{}", model="claude-sonnet-4-6",
                input_tokens=800, output_tokens=200,
                cost_usd=0.005, stop_reason="end_turn",
            ),
            feedback,
        )
        critic = CriticAgent(llm=mock_llm)
        result = await critic.execute(sample_draft, sample_brief)
        assert result.approved is False
        assert len(result.rejection_reasons) > 0

    async def test_hard_gate_rejects_perfect_vo_zero_prod(self, mock_llm, sample_draft, sample_brief):
        """VO=70, PROD=0, total=70 >= threshold=70 must NOT approve — hard gate."""
        feedback = CriticFeedback(
            variant_id="A",
            total_score=70,
            voiceover_score=70,
            production_score=0,
            dimensions=[
                CriticDimension(name="hook_quality",        score=25, max_score=25),
                CriticDimension(name="anti_ai_cliche",      score=15, max_score=15),
                CriticDimension(name="retention_structure", score=10, max_score=10),
                CriticDimension(name="human_editorial",     score=10, max_score=10),
                CriticDimension(name="niche_compliance",    score=5,  max_score=5),
                CriticDimension(name="pacing_compliance",   score=5,  max_score=5),
                CriticDimension(name="visual_concreteness", score=0,  max_score=25),
                CriticDimension(name="sfx_appropriateness", score=0,  max_score=5),
            ],
            approved=True,  # LLM incorrectly approved — hard gate must override
        )
        mock_llm.complete_structured.return_value = (
            LLMResponse(
                content="{}", model="claude-sonnet-4-6",
                input_tokens=800, output_tokens=200,
                cost_usd=0.005, stop_reason="end_turn",
            ),
            feedback,
        )
        critic = CriticAgent(llm=mock_llm)
        result = await critic.execute(sample_draft, sample_brief, threshold=SPOKE_THRESHOLD)
        # Hard gate: PROD=0 < PROD_PASS=23 → must reject despite total==threshold
        assert result.approved is False, "Hard gate failed: perfect VO + zero PROD should not approve"
        assert result.voiceover_score == 70
        assert result.production_score == 0

    async def test_hard_gate_passes_when_both_groups_pass(self, mock_llm, sample_draft, sample_brief):
        """Both groups must independently pass VO_PASS + PROD_PASS."""
        feedback = CriticFeedback(
            variant_id="A",
            total_score=76,
            voiceover_score=53,   # exactly VO_PASS
            production_score=23,  # exactly PROD_PASS
            dimensions=[
                CriticDimension(name="hook_quality",        score=15, max_score=25),
                CriticDimension(name="anti_ai_cliche",      score=11, max_score=15),
                CriticDimension(name="retention_structure", score=9,  max_score=10),
                CriticDimension(name="human_editorial",     score=9,  max_score=10),
                CriticDimension(name="niche_compliance",    score=5,  max_score=5),
                CriticDimension(name="pacing_compliance",   score=5,  max_score=5),
                CriticDimension(name="visual_concreteness", score=18, max_score=25),
                CriticDimension(name="sfx_appropriateness", score=5,  max_score=5),
            ],  # VO 15+11+9+9+5+5 = 54 (≥53), Prod 18+5 = 23 (≥23)
            approved=True,
        )
        mock_llm.complete_structured.return_value = (
            LLMResponse(
                content="{}", model="claude-sonnet-4-6",
                input_tokens=800, output_tokens=200,
                cost_usd=0.005, stop_reason="end_turn",
            ),
            feedback,
        )
        critic = CriticAgent(llm=mock_llm)
        result = await critic.execute(sample_draft, sample_brief, threshold=SPOKE_THRESHOLD)
        assert result.approved is True

    async def test_hub_threshold_higher(self):
        assert HUB_THRESHOLD > SPOKE_THRESHOLD
        assert HUB_THRESHOLD == 85
        assert SPOKE_THRESHOLD == 70

    async def test_compare_variants(self, mock_llm, sample_draft, sample_brief):
        draft_b = ScriptDraft(
            variant_id="B", brief_title="Test", hook="Alternative hook.",
            segments=[], word_count=1200, estimated_duration_seconds=500,
        )
        mock_llm.complete.return_value = LLMResponse(
            content="B",
            model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=10,
            cost_usd=0.003, stop_reason="end_turn",
        )
        critic = CriticAgent(llm=mock_llm)
        winner = await critic.compare_variants(sample_draft, draft_b, sample_brief)
        assert winner in ("A", "B")

    async def test_error_raises_agent_error(self, mock_llm, sample_draft, sample_brief):
        mock_llm.complete_structured.side_effect = AgentError("Parse failed")
        critic = CriticAgent(llm=mock_llm)
        with pytest.raises(AgentError):
            await critic.execute(sample_draft, sample_brief)


# ── Golden tests for the scoring-integrity overhaul (ChatGPT review 2026-07-14) ──

class TestScoringIntegrity:
    def test_dimension_clamps_to_max(self):
        """A dimension can never score above its own max (was: 8/5 accepted → totals >100)."""
        d = CriticDimension(name="niche_compliance", score=8, max_score=5)
        assert d.score == 5

    def test_canonical_spoken_no_double_count(self):
        """hook + hook_scenes must NOT both be counted; legacy content is included once."""
        from omnicast.agents.critic import _canonical_spoken
        from omnicast.models.script import ScriptScene
        draft = ScriptDraft(
            variant_id="A", brief_title="t",
            hook="HOOKTEXT",
            hook_scenes=[ScriptScene(voiceover="HOOKTEXT", visual_prompt="x")],
            segments=[ScriptSegment(index=0, heading="S", content="BODYLEGACY",
                                    estimated_duration_seconds=10)],
            outro="OUTROTEXT",
        )
        text = _canonical_spoken(draft)
        assert text.count("HOOKTEXT") == 1          # not doubled
        assert "BODYLEGACY" in text                 # legacy content not dropped
        assert "OUTROTEXT" in text

    def test_narrative_slop_signals_caps(self):
        """Objective slop scan returns hard caps (enforced in Python, not prompt-trust)."""
        from omnicast.agents.critic import _narrative_slop_signals
        text = ("I told myself it was fine. I told myself again. He was tall and "
                "standing perfectly still. Three knocks came at the door. "
                "Comment below which room we open next.")
        flags, caps = _narrative_slop_signals(text)
        assert len(flags) >= 4
        # caps target the narrative dimension set (originality / structural_variety)
        assert caps.get("originality", 99) <= 4       # "I told myself" x2+ / CTA / motifs
        assert "structural_variety" in caps or caps.get("originality", 99) <= 4

    async def test_continuity_issues_cap_total(self, mock_llm, sample_draft):
        """A continuity contradiction hard-caps total ≤65 no matter how high the LLM scored."""
        from omnicast.config.niches import get_niche_config
        narr_cfg = get_niche_config("psychology", "horror")
        assert getattr(narr_cfg, "content_format", "") == "narrative"
        brief = TopicBrief(title="Night Shift", niche=Niche.FINANCE, market=Market.US,
                           source=TopicSource.GOOGLE_TRENDS)
        feedback = CriticFeedback(
            variant_id="A", total_score=92, voiceover_score=62, production_score=30,
            dimensions=[  # NARRATIVE dimension set (continuity/voice/fear/variety/originality)
                CriticDimension(name="continuity", score=18, max_score=20),
                CriticDimension(name="authentic_voice", score=16, max_score=18),
                CriticDimension(name="fear_immersion", score=10, max_score=12),
                CriticDimension(name="structural_variety", score=10, max_score=12),
                CriticDimension(name="originality", score=8, max_score=8),
                CriticDimension(name="visual_concreteness", score=25, max_score=25),
                CriticDimension(name="sfx_appropriateness", score=5, max_score=5),
            ],
            continuity_issues=["hook says the second night, body says the fourth"],
        )
        mock_llm.complete_structured.return_value = (
            LLMResponse(content="{}", model="m", input_tokens=1, output_tokens=1,
                        cost_usd=0.0, stop_reason="end_turn"),
            feedback,
        )
        critic = CriticAgent(llm=mock_llm)
        result = await critic.execute(sample_draft, brief, niche_cfg=narr_cfg,
                                      threshold=SPOKE_THRESHOLD)
        assert result.total_score <= 65
        assert result.approved is False


class TestScoringIntegrityV2:
    """Golden tests for the ChatGPT round-2 review (double-score cap bypass, fake
    max_score, prompt separation, under-length routing)."""

    def _narr(self):
        from omnicast.config.niches import get_niche_config
        return get_niche_config("psychology", "horror")

    async def test_double_score_cap_survives_and_total_consistent(self, mock_llm):
        from omnicast.models.script import ScriptScene
        brief = TopicBrief(title="Night", niche=Niche.FINANCE, market=Market.US,
                           source=TopicSource.GOOGLE_TRENDS)
        slop = "I told myself it was nothing. I told myself again. I told myself a third time. "
        long_vo = slop + ("the road went on and the dark pressed close for a long while " * 200)
        draft = ScriptDraft(
            variant_id="A", brief_title="t", hook="It kept pace with my car.",
            hook_scenes=[ScriptScene(voiceover="It kept pace with my car.", visual_prompt="road")],
            segments=[ScriptSegment(index=0, heading="Route", content="",
                estimated_duration_seconds=600,
                scenes=[ScriptScene(voiceover=long_vo, visual_prompt="dark road")])],
            outro="I never took that road again.")

        def _fb():
            return CriticFeedback(
                variant_id="A", total_score=80, voiceover_score=60, production_score=20,
                dimensions=[
                    CriticDimension(name="continuity", score=16, max_score=20),
                    CriticDimension(name="authentic_voice", score=14, max_score=18),
                    CriticDimension(name="fear_immersion", score=9, max_score=12),
                    CriticDimension(name="structural_variety", score=9, max_score=12),
                    CriticDimension(name="originality", score=8, max_score=8),  # → capped to 4
                    CriticDimension(name="visual_concreteness", score=18, max_score=25),
                    CriticDimension(name="sfx_appropriateness", score=4, max_score=5),
                ])
        resp = LLMResponse(content="{}", model="m", input_tokens=1, output_tokens=1,
                           cost_usd=0.0, stop_reason="end_turn")
        mock_llm.complete_structured.side_effect = [(resp, _fb()), (resp, _fb())]
        result = await CriticAgent(llm=mock_llm).execute(
            draft, brief, niche_cfg=self._narr(), threshold=SPOKE_THRESHOLD)
        orig = next(d for d in result.dimensions if d.name == "originality")
        assert orig.score <= 4, "anti-slop cap must survive the double-score average"
        assert result.total_score == sum(d.score for d in result.dimensions), "total == sum(dims)"

    async def test_rejects_fake_max_unknown_missing_dims(self, mock_llm, sample_draft, sample_brief):
        fb = CriticFeedback(
            variant_id="A", total_score=99, voiceover_score=50, production_score=25,
            dimensions=[
                CriticDimension(name="hook_quality", score=25, max_score=25),
                CriticDimension(name="niche_compliance", score=25, max_score=25),  # real max 5 — model lied
                CriticDimension(name="bogus_dim", score=25, max_score=25),          # unknown
            ])
        mock_llm.complete_structured.return_value = (
            LLMResponse(content="{}", model="m", input_tokens=1, output_tokens=1,
                        cost_usd=0.0, stop_reason="end_turn"), fb)
        result = await CriticAgent(llm=mock_llm).execute(
            sample_draft, sample_brief, threshold=SPOKE_THRESHOLD)
        by = {d.name: d for d in result.dimensions}
        assert "bogus_dim" not in by                              # unknown dropped
        assert by["niche_compliance"].max_score == 5              # canonical, not model's 25
        assert by["niche_compliance"].score <= 5                  # clamped to canonical max
        assert set(by) == set(VO_DIMS) | set(PROD_DIMS)           # exactly the 8, missing filled
        assert result.total_score == sum(d.score for d in result.dimensions)

    def test_narrative_prompt_separated_from_explainer(self, mock_llm):
        from omnicast.models.script import ScriptScene
        from omnicast.config.niches import get_niche_config
        c = CriticAgent(llm=mock_llm)
        brief = TopicBrief(title="Night", niche=Niche.FINANCE, market=Market.US,
                           source=TopicSource.GOOGLE_TRENDS)
        draft = ScriptDraft(variant_id="A", brief_title="t", hook="I saw it.",
            hook_scenes=[ScriptScene(voiceover="I saw it.", visual_prompt="road")],
            segments=[ScriptSegment(index=0, heading="Lot", content="",
                estimated_duration_seconds=60,
                scenes=[ScriptScene(voiceover="It stood there.", visual_prompt="figure")])],
            outro="I still lock the door.")
        np = c._build_review_prompt(draft, brief, get_niche_config("psychology", "horror"))
        ep = c._build_review_prompt(draft, brief, get_niche_config("finance", None))
        # narrative: integrity fields present, explainer demands absent
        assert "continuity_issues" in np and "story_shapes" in np
        assert "continuity" in np and "authentic_voice" in np
        assert "SPECIFIC number" not in np and "hook_quality" not in np
        assert "mid-video like CTA" not in np.lower()
        # explainer unchanged
        assert "hook_quality" in ep and "SPECIFIC number" in ep

    async def test_underlength_routes_to_writer_not_visual(self, mock_llm, sample_brief):
        """A short script (high scores) must reject on length with a writer/expand
        reason — never pass as a visuals-only fix."""
        short = ScriptDraft(variant_id="A", brief_title="t", hook="Tiny.",
                            segments=[ScriptSegment(index=0, heading="S", content="Only a few words here.",
                                                    estimated_duration_seconds=10)],
                            outro="End.")
        fb = CriticFeedback(
            variant_id="A", total_score=88, voiceover_score=65, production_score=23,
            dimensions=[
                CriticDimension(name="hook_quality", score=25, max_score=25),
                CriticDimension(name="anti_ai_cliche", score=13, max_score=15),
                CriticDimension(name="retention_structure", score=9, max_score=10),
                CriticDimension(name="human_editorial", score=9, max_score=10),
                CriticDimension(name="niche_compliance", score=5, max_score=5),
                CriticDimension(name="pacing_compliance", score=4, max_score=5),
                CriticDimension(name="visual_concreteness", score=18, max_score=25),
                CriticDimension(name="sfx_appropriateness", score=5, max_score=5),
            ])
        mock_llm.complete_structured.return_value = (
            LLMResponse(content="{}", model="m", input_tokens=1, output_tokens=1,
                        cost_usd=0.0, stop_reason="end_turn"), fb)
        result = await CriticAgent(llm=mock_llm).execute(short, sample_brief, threshold=SPOKE_THRESHOLD)
        assert result.approved is False
        assert any("HARD GATE" in r for r in result.rejection_reasons)
