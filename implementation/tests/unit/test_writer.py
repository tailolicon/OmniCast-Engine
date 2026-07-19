"""Tests for Writer Agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from omnicast.agents.writer import WriterAgent, ANGLES
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.models.script import (
    TopicBrief, ScriptDraft, CriticFeedback, CriticDimension,
    ScriptScene, ScriptSegment,
)
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.kb.patterns import PatternStore
from omnicast.shared.errors import AgentError
from omnicast.config.niches import get_niche_config


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock(spec=LLMClient)
    llm.total_cost = 0.01
    return llm


@pytest.fixture
def mock_pattern_store() -> AsyncMock:
    store = AsyncMock(spec=PatternStore)
    store.get_patterns_for_brief.return_value = []
    return store


@pytest.fixture
def sample_brief() -> TopicBrief:
    return TopicBrief(
        title="5 Investment Mistakes to Avoid",
        niche=Niche.FINANCE,
        market=Market.US,
        source=TopicSource.GOOGLE_TRENDS,
        angle="",
        key_points=["Overtrading", "No stop loss", "FOMO"],
        target_duration_min=10,
    )


@pytest.fixture
def sample_draft() -> ScriptDraft:
    return ScriptDraft(
        variant_id="A",
        brief_title="5 Investment Mistakes",
        hook="Did you know 90% of retail traders lose money?",
        segments=[],
        word_count=1500,
        estimated_duration_seconds=600,
        version=1,
    )


@pytest.fixture
def sample_feedback() -> CriticFeedback:
    return CriticFeedback(
        variant_id="A",
        total_score=65,
        approved=False,
        rejection_reasons=["Hook too generic"],
        specific_fixes=["Replace with a specific statistic"],
        round_number=1,
    )


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        input_tokens=500,
        output_tokens=1000,
        cost_usd=0.0165,
        stop_reason="end_turn",
    )


class TestWriterAgent:
    async def test_name(self, mock_llm):
        writer = WriterAgent(llm=mock_llm)
        assert writer.name == "writer"

    async def test_system_prompt_not_empty(self, mock_llm):
        writer = WriterAgent(llm=mock_llm)
        assert len(writer.system_prompt) > 50

    async def test_generate_returns_variants(self, mock_llm, sample_brief):
        # Mock LLM to return parseable script content
        mock_llm.complete.return_value = _make_llm_response(
            "HOOK: A bold statement.\n"
            "SEGMENT 1: Introduction\n"
            "Content here about investment mistakes.\n"
            "SEGMENT 2: Main Point\n"
            "More content.\n"
            "OUTRO: Thanks for watching."
        )
        writer = WriterAgent(llm=mock_llm)
        variants = await writer.execute(sample_brief, num_variants=3)
        assert len(variants) == 3
        assert all(isinstance(v, ScriptDraft) for v in variants)
        # Each variant should have a different variant_id
        ids = [v.variant_id for v in variants]
        assert len(set(ids)) == 3

    async def test_generate_single_variant(self, mock_llm, sample_brief):
        mock_llm.complete.return_value = _make_llm_response("HOOK: Test.\nOUTRO: End.")
        writer = WriterAgent(llm=mock_llm)
        variants = await writer.execute(sample_brief, num_variants=1)
        assert len(variants) == 1

    async def test_generate_with_patterns(
        self, mock_llm, mock_pattern_store, sample_brief
    ):
        from omnicast.models.script import EngagementPattern
        from datetime import datetime, timezone, timedelta

        mock_pattern_store.get_patterns_for_brief.return_value = [
            EngagementPattern(
                pattern_id="EP-001",
                niche=Niche.FINANCE,
                market=Market.US,
                finding="Numbered lists improve retention",
                confidence=0.8,
                sample_size=15,
                decay_date=datetime.now(timezone.utc) + timedelta(days=90),
            )
        ]
        mock_llm.complete.return_value = _make_llm_response("HOOK: Test.\nOUTRO: End.")
        writer = WriterAgent(llm=mock_llm, pattern_store=mock_pattern_store)
        variants = await writer.execute(sample_brief, num_variants=1)
        assert len(variants) == 1
        mock_pattern_store.get_patterns_for_brief.assert_called_once()

    async def test_revise_increments_version(
        self, mock_llm, sample_draft, sample_feedback, sample_brief
    ):
        mock_llm.complete.return_value = _make_llm_response(
            "HOOK: A shocking new statistic.\nOUTRO: End."
        )
        writer = WriterAgent(llm=mock_llm)
        revised = await writer.revise(sample_draft, sample_feedback, sample_brief)
        assert isinstance(revised, ScriptDraft)
        assert revised.version == sample_draft.version + 1
        assert revised.variant_id == "A"  # preserved

    async def test_revise_uses_feedback(
        self, mock_llm, sample_draft, sample_feedback, sample_brief
    ):
        mock_llm.complete.return_value = _make_llm_response("HOOK: Fixed.\nOUTRO: End.")
        writer = WriterAgent(llm=mock_llm)
        await writer.revise(sample_draft, sample_feedback, sample_brief)
        # Verify feedback was included in the REVISE prompt (the first LLM call;
        # a short draft triggers a later _ensure_length expand call whose prompt
        # does not carry the feedback — inspect call [0], not the last).
        call_args = mock_llm.complete.call_args_list[0]
        messages = call_args.kwargs["messages"]
        user_msg = messages[0]["content"]
        assert "Hook too generic" in user_msg or "specific" in user_msg.lower()

    async def test_revise_is_one_llm_call_without_hidden_expand_or_quality_pass(
        self, mock_llm, sample_draft, sample_feedback, sample_brief
    ):
        mock_llm.complete.return_value = _make_llm_response(
            "HOOK: Fixed.\nSEGMENT 1: Main\nBetter content.\nOUTRO: End."
        )
        writer = WriterAgent(llm=mock_llm)

        await writer.revise(sample_draft, sample_feedback, sample_brief)

        assert mock_llm.complete.call_count == 1

    async def test_llm_error_raises_agent_error(self, mock_llm, sample_brief):
        mock_llm.complete.side_effect = AgentError("API down")
        writer = WriterAgent(llm=mock_llm)
        with pytest.raises(AgentError):
            await writer.execute(sample_brief)

    async def test_angles_constant(self):
        assert len(ANGLES) == 3
        assert "pain_hook" in ANGLES
        assert "data_driven" in ANGLES
        assert "contrarian" in ANGLES

    def test_narrative_generation_prompt_has_v4_quality_contract(
        self, mock_llm, sample_brief
    ):
        writer = WriterAgent(llm=mock_llm)
        niche_cfg = get_niche_config("psychology", "horror")
        prompt = writer._build_narrative_generation_prompt(sample_brief, niche_cfg)

        assert "CONTINUITY LEDGER" in prompt
        assert "at most ONE aftermath/corroboration beat" in prompt
        assert "at least one story has ZERO" in prompt
        assert "no more than FOUR exact numeric anchors" in prompt
        assert "No two stories may end with later evidence" in prompt
        assert '"I told myself" is banned' in prompt
        assert "sentence rhythm" in prompt

    def test_narrative_quality_pass_targets_observed_v4_failures(
        self, mock_llm, sample_draft, sample_brief
    ):
        writer = WriterAgent(llm=mock_llm)
        prompt = writer._build_continuity_prompt(sample_draft, sample_brief)

        assert "truck is already parked" in prompt
        assert "one van" in prompt and "four plates" in prompt
        assert "one electrician visit" in prompt
        assert "one precise clock time" in prompt
        assert "PRESERVE the core fight-or-flight" in prompt
        assert "at most ONE" in prompt and "corroboration" in prompt

    def test_narrative_quality_pass_enforces_recent_name_registry(
        self, mock_llm, sample_draft, sample_brief
    ):
        writer = WriterAgent(llm=mock_llm)
        brief = sample_brief.model_copy(update={
            "key_points": [
                "DO NOT REUSE from recent videos on this channel — character names: "
                "Priya, Marcus, Deb; motifs: thermos. Invent fresh names/props."
            ]
        })
        prompt = writer._build_continuity_prompt(sample_draft, brief)

        assert "RECENT CHANNEL HISTORY" in prompt
        assert "Priya, Marcus, Deb" in prompt
        assert "Rename every reused character consistently" in prompt

    def test_narrative_expansion_uses_story_beats_not_explainer_padding(
        self, mock_llm, sample_draft, sample_brief
    ):
        writer = WriterAgent(llm=mock_llm)
        prompt = writer._build_expansion_prompt(
            sample_draft,
            sample_brief,
            words=600,
            floor=1200,
            previous_script="HOOK: test",
            narrative=True,
        )

        assert "causal story beats" in prompt
        assert "data points" not in prompt
        assert "objections + rebuttals" not in prompt
        assert "official records" in prompt
        assert "Do NOT add" in prompt
        assert '"insertions"' in prompt
        assert "after_scene_index" in prompt
        assert "Do NOT output the full script" in prompt

    def test_word_count_includes_hook_segments_and_outro(self, mock_llm):
        writer = WriterAgent(llm=mock_llm)
        scene = lambda words: ScriptScene(voiceover=words, visual_prompt="dark hall")
        draft = ScriptDraft(
            variant_id="A",
            brief_title="T",
            hook="one two",
            hook_scenes=[scene("one two")],
            segments=[ScriptSegment(
                index=1, heading="Hall", content="three four five",
                estimated_duration_seconds=2,
                scenes=[scene("three four five")],
            )],
            outro="six seven",
            outro_scenes=[scene("six seven")],
        )

        assert writer._word_count(draft) == 7

    def test_narrative_scene_patch_inserts_without_rewriting_clean_scenes(
        self, mock_llm
    ):
        writer = WriterAgent(llm=mock_llm)
        original = ScriptScene(
            voiceover="I heard the service door move.", visual_prompt="service door dark"
        )
        draft = ScriptDraft(
            variant_id="A", brief_title="Night cleaners", hook="The door moved.",
            hook_scenes=[ScriptScene(voiceover="The door moved.", visual_prompt="dark door")],
            segments=[ScriptSegment(
                index=1, heading="Service Hall", content=original.voiceover,
                estimated_duration_seconds=3, scenes=[original],
            )],
        )
        payload = {
            "insertions": [{
                "segment_index": 1,
                "after_scene_index": 0,
                "scenes": [{
                    "vo": "I shoved the cart under the handle and called security.",
                    "visual": "cart blocks service door",
                    "sfx": None,
                    "pace": "fast",
                    "pause_after_ms": 0,
                    "emphasis": ["called security"],
                }],
            }]
        }

        grown = writer._apply_narrative_expansion_patch(draft, payload, "Night cleaners")

        assert grown.segments[0].scenes[0].voiceover == original.voiceover
        assert grown.segments[0].scenes[1].voiceover.startswith("I shoved the cart")
        assert writer._word_count(grown) > writer._word_count(draft)

    async def test_narrative_expand_caps_at_one_patch_call(
        self, mock_llm
    ):
        mock_llm._model = "claude-sonnet-5"
        mock_llm.complete.return_value = _make_llm_response(
            '{"insertions":[{"segment_index":1,"after_scene_index":0,'
            '"scenes":[{"vo":"I ran for help.","visual":"running dark hall",'
            '"sfx":null,"pace":"fast","pause_after_ms":0,"emphasis":[]}]}]}'
        )
        writer = WriterAgent(llm=mock_llm)
        scene = ScriptScene(voiceover="The lock moved.", visual_prompt="door lock dark")
        draft = ScriptDraft(
            variant_id="A", brief_title="T", hook="The lock moved.",
            hook_scenes=[scene],
            segments=[ScriptSegment(
                index=1, heading="Hall", content=scene.voiceover,
                estimated_duration_seconds=2, scenes=[scene],
            )],
        )
        brief = TopicBrief(
            title="T", niche=Niche.PSYCHOLOGY, market=Market.US,
            source=TopicSource.MANUAL, target_duration_min=10,
        )

        await writer._ensure_length(
            draft, brief, "system", "CURRENT", "A",
            max_passes=4, narrative=True,
        )

        assert mock_llm.complete.call_count == 1

    def test_narrative_revision_does_not_apply_explainer_template(
        self, mock_llm, sample_draft, sample_feedback, sample_brief
    ):
        writer = WriterAgent(llm=mock_llm)
        niche_cfg = get_niche_config("psychology", "horror")
        prompt = writer._build_revision_prompt(
            sample_draft, sample_feedback, sample_brief, niche_cfg=niche_cfg
        )

        assert "NARRATIVE HORROR" in prompt
        assert "preserve the strongest fight-or-flight" in prompt
        assert "(5 segments total" not in prompt
        assert "key stats" not in prompt
        assert "Open loops" not in prompt
