"""Tests for Writer Agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from omnicast.agents.writer import (
    ANGLES,
    WriterAgent,
    production_competitor_rules,
)
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.models.script import (
    TopicBrief, ScriptDraft, CriticFeedback, CriticDimension,
    ScriptScene, ScriptSegment,
)
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.kb.patterns import PatternStore
from omnicast.shared.errors import AgentError
from omnicast.config.niches import get_niche_config
from omnicast.agents.editorial_angle import EditorialAngle


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

    def test_parser_accepts_em_dash_segment_headers_from_live_cli(
        self, mock_llm
    ):
        raw = (
            "HOOK:\nSCENES:\n[]\n"
            "SEGMENT 1 — THE MECHANICS:\nSCENES:\n"
            '[{"vo":"The first full segment now survives parsing.",'
            '"visual":"SSA page","sfx":null}]\n'
            "SEGMENT 2 - THE TURN:\nSCENES:\n"
            '[{"vo":"The second segment survives too.",'
            '"visual":"benefit chart","sfx":null}]\n'
            "OUTRO:\nSCENES:\n[]"
        )

        parsed = WriterAgent(llm=mock_llm)._parse_draft(raw, "A", "Topic")

        assert [segment.heading for segment in parsed.segments] == [
            "THE MECHANICS", "THE TURN"]
        assert sum(
            len(segment.content.split()) for segment in parsed.segments) == 12

    async def test_system_prompt_not_empty(self, mock_llm):
        writer = WriterAgent(llm=mock_llm)
        assert len(writer.system_prompt) > 50

    def test_finance_prosody_normalizer_keeps_only_load_bearing_pauses(
        self, mock_llm
    ):
        scenes = []
        for index in range(150):
            voiceover = (
                "Can we pause on this verified number together for one moment?"
                if index == 0
                else "This plain spoken sentence keeps the explanation moving with us."
            )
            scenes.append(ScriptScene(
                voiceover=voiceover,
                visual_prompt="benefit statement",
                pause_after_ms=900 if index < 30 else 0,
            ))
        draft = ScriptDraft(
            variant_id="A",
            brief_title="Topic",
            hook="",
            segments=[ScriptSegment(
                index=1,
                heading="The rule",
                content=" ".join(scene.voiceover for scene in scenes),
                estimated_duration_seconds=900,
                scenes=scenes,
            )],
        )

        normalized = WriterAgent(
            llm=mock_llm)._normalize_finance_prosody(draft)
        pauses = [
            scene.pause_after_ms
            for segment in normalized.segments
            for scene in segment.scenes
            if scene.pause_after_ms >= 400
        ]

        assert len(pauses) <= 9
        assert normalized.segments[0].scenes[0].pause_after_ms == 900
        assert normalized.word_count > 0
        assert normalized.raw_content

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

    def test_only_production_eligible_competitor_text_can_steer_writer(self):
        old = (
            "HYPOTHESIS: winners ask questions sooner\n\n"
            "=== MEASURED CRAFT (caption forensics, cohort-derived) ===\n"
            "PRODUCTION-ELIGIBLE COMPETITOR CRAFT RULES\n"
            "RULES: NONE."
        )
        assert production_competitor_rules(old).startswith("PRODUCTION-ELIGIBLE")
        assert "HYPOTHESIS" not in production_competitor_rules(old)
        assert production_competitor_rules(
            "STYLE REFERENCE ONLY: copy this winner shape") == ""

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

    def test_finance_prompt_has_one_hook_and_one_earned_subscribe_contract(
        self, mock_llm, sample_brief
    ):
        """The old prompt simultaneously banned and required a greeting, then
        treated every spoken subscribe invitation as disposable. The channel
        needs one earned invitation tied to its promise, without generic
        algorithm begging or a next-video detour."""
        writer = WriterAgent(llm=mock_llm)
        cfg = get_niche_config("finance", "retirement_senior")
        prompt = writer._build_generation_prompt(
            sample_brief, "pain_hook", [], cfg)

        assert "G — short warm spoken greeting" not in prompt
        assert "NO GREETING" in prompt
        assert "ONE EARNED SPOKEN SUBSCRIBE INVITATION" in prompt
        assert "channel promise" in prompt
        assert "generic 'like and subscribe'" in prompt
        assert "Next video tease" not in prompt
        assert "final question ENDS the spoken script" in prompt
        assert "Only when the OPERATOR BRIEF explicitly requests a HUMAN ANCHOR" in prompt
        assert "Do not force every episode into one mold" in prompt
        assert "A name alone does not make a story" in prompt
        assert "Do not bolt on Roth conversions, IRMAA" in prompt
        assert "invent an SSA letter" in prompt
        assert "Ozempic" not in prompt
        assert "fermenting" not in prompt
        assert "stuck in the throat" not in prompt
        assert "presenter on camera" not in prompt.lower()
        assert "presenter direct" not in prompt.lower()
        assert "BOTH open loops" not in prompt
        assert "3-5 scenes and 45-75 spoken words" in prompt
        assert "place it by hook scene 2" in prompt
        compact_prompt = " ".join(prompt.split())
        assert "Do not claim where specific withheld dollars are stored" in compact_prompt
        assert "agency letters, statements, calculators" in prompt

        system = writer._build_system_prompt(cfg)
        assert "name the primary source and rule year aloud" in system
        assert "one earned spoken subscribe invitation" in system
        assert "generic algorithm begging" in system
        assert "NEVER read the source aloud" not in system
        assert "presenter on camera" not in system.lower()
        assert "Ozempic" not in system

    def test_editorial_angle_leads_the_generation_prompt(
        self, mock_llm, sample_brief
    ):
        writer = WriterAgent(llm=mock_llm)
        cfg = get_niche_config("finance", "retirement_senior")
        angle = EditorialAngle(
            thesis="The earnings test is not a tax, and treating it as one "
                   "makes a temporary hold feel like a permanent loss",
            against="Money withheld by the earnings test is gone forever",
            stake="A working retiree may make a life decision from the wrong model",
            turn="The withheld months are accounted for again at full retirement age",
            walk_away="Withheld and lost are not the same thing",
            evidence_ids=("E1",),
            counterpoint="Cash flow can still hurt before full retirement age",
            narrator_attitude="calmly irritated by rules whose names mislead people",
            reaction_beats=(
                "React to the withheld amount as a cash-flow shock",
                "React to the recalculation as the overlooked turn",
            ),
            felt_metaphor="A locked drawer, not a shredder",
            metaphor_callback="Open the drawer again at the recalculation",
            driving_questions=(
                "What is actually withheld?",
                "When and how is it accounted for later?",
            ),
            ending_question="Would you still call it a tax after seeing the recalculation?",
        )

        prompt = writer._build_generation_prompt(
            sample_brief, "pain_hook", [], cfg, editorial_angle=angle)

        assert prompt.index("THIS VIDEO'S ARGUMENT") < prompt.index(
            "UPSTREAM EVIDENCE/CONTEXT ANCHORS")
        assert angle.thesis in prompt
        assert angle.counterpoint in prompt
        assert "invent a personal anecdote" in prompt.lower()
        assert "Never substitute a remembered prior-year figure" in prompt
        assert "first-person editorial reactions" in prompt

    def test_finance_revision_keeps_angle_evidence_and_faceless_contract(
        self, mock_llm, sample_brief, sample_draft, sample_feedback
    ):
        writer = WriterAgent(llm=mock_llm)
        cfg = get_niche_config("finance", "retirement_senior")
        draft = sample_draft.model_copy(update={"editorial_angle": {
            "thesis": "Withheld is not permanently lost",
            "against": "The earnings test is just a tax",
            "counterpoint": "The temporary cash-flow loss is real",
            "narrator_attitude": "calmly irritated by the misleading name",
            "reaction_beats": ["after the hold", "after recalculation"],
            "walk_away": "A hold and a loss are different",
        }})
        sample_brief = sample_brief.model_copy(update={
            "key_points": [
                "Operator brief: THE HUMAN ANCHOR\n"
                "Let's call her Denise. Keep the kitchen table recurring."
            ],
        })
        prompt = writer._build_revision_prompt(
            draft, sample_feedback, sample_brief, niche_cfg=cfg)
        assert "Withheld is not permanently lost" in prompt
        assert "Do not add a new factual claim" in prompt
        assert "VERIFIED EVIDENCE — OVERRIDES THE ORIGINAL SCRIPT" in prompt
        assert "OPERATOR BRIEF — STILL BINDING" in prompt
        assert "Let's call her Denise" in prompt
        assert "Keep the kitchen table recurring" in prompt
        assert "Never preserve a conflicting number" in prompt
        assert "spoken words after revision" in prompt
        assert "SFX remains null" in prompt
        assert "presenter on camera" not in prompt.lower()
        assert "(5 segments total" not in prompt
        assert "Open loops must be" not in prompt
        assert "Rewrite an overlong opening" in prompt
        assert "45-75 spoken words" in prompt
        assert "Ignore any critic fix" in prompt
        assert "Do not trace specific withheld dollars" in prompt

    async def test_revised_draft_keeps_editorial_angle_metadata(
        self, mock_llm, sample_brief, sample_draft, sample_feedback
    ):
        mock_llm.complete.return_value = _make_llm_response(
            "HOOK: Fixed.\nSEGMENT 1: Main\nBetter content.\nOUTRO: End.")
        angle = {"thesis": "A hold is not a permanent loss"}
        draft = sample_draft.model_copy(update={"editorial_angle": angle})
        revised = await WriterAgent(llm=mock_llm).revise(
            draft, sample_feedback, sample_brief,
            niche_cfg=get_niche_config("finance", "retirement_senior"))
        assert revised.editorial_angle == angle

    def test_finance_length_fill_cannot_invent_more_data_points(
        self, mock_llm, sample_brief, sample_draft
    ):
        writer = WriterAgent(llm=mock_llm)
        draft = sample_draft.model_copy(update={
            "editorial_angle": {"thesis": "A hold is not a permanent loss"}})
        prompt = writer._build_expansion_prompt(
            draft, sample_brief, words=800, floor=1500,
            previous_script="HOOK: test", narrative=False)
        assert "Do NOT add data points" in prompt
        assert "counterpoint already present" in prompt
        assert "SFX stays null" in prompt
        assert '"insertions"' in prompt
        assert "Do NOT output the full script" in prompt

    async def test_finance_length_fill_is_one_insertion_patch_not_four_rewrites(
        self, mock_llm, sample_brief
    ):
        mock_llm.complete.return_value = _make_llm_response(
            '{"insertions":[{"segment_index":1,"after_scene_index":0,'
            '"scenes":[{"vo":"This added explanation stays inside the supplied '
            'mechanism and does not invent another number.",'
            '"visual":"official document close-up","sfx":null,'
            '"pace":"normal","pause_after_ms":0,"emphasis":[]}]}]}'
        )
        original = ScriptScene(
            voiceover="The verified rule changes what the smaller check means.",
            visual_prompt="SSA document")
        draft = ScriptDraft(
            variant_id="A", brief_title=sample_brief.title, hook="",
            segments=[ScriptSegment(
                index=1, heading="The cash-flow window",
                content=original.voiceover, estimated_duration_seconds=5,
                scenes=[original])],
            editorial_angle={"thesis": "A delay and a loss are different"},
        )

        grown = await WriterAgent(llm=mock_llm)._ensure_length(
            draft, sample_brief, "system", "CURRENT", "A",
            max_passes=4, narrative=False,
        )

        assert mock_llm.complete.call_count == 1
        assert len(grown.segments[0].scenes) == 2
        assert "added explanation" in grown.segments[0].scenes[1].voiceover

    async def test_finance_length_fill_stays_bounded_when_resume_lost_editorial_angle(
        self, mock_llm, sample_brief
    ):
        mock_llm.complete.return_value = _make_llm_response(
            '{"insertions":[{"segment_index":1,"after_scene_index":0,'
            '"scenes":[{"vo":"This evidence-safe insertion deepens the existing '
            'cash-flow distinction without adding another claim.",'
            '"visual":"furnace estimate on table","sfx":null,'
            '"pace":"normal","pause_after_ms":0,"emphasis":[]}]}]}'
        )
        original = ScriptScene(
            voiceover="The verified rule changes what the smaller check means.",
            visual_prompt="SSA document")
        resumed = ScriptDraft(
            variant_id="A", brief_title=sample_brief.title, hook="",
            segments=[ScriptSegment(
                index=1, heading="The cash-flow window",
                content=original.voiceover, estimated_duration_seconds=5,
                scenes=[original])],
            editorial_angle={},
        )

        grown = await WriterAgent(llm=mock_llm)._ensure_length(
            resumed, sample_brief, "system", "CURRENT", "A",
            max_passes=4, narrative=False, finance=True,
        )

        assert mock_llm.complete.call_count == 1
        assert len(grown.segments[0].scenes) == 2
        prompt = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
        assert "senior-finance script" in prompt
        assert "Do NOT output the full script" in prompt

    def test_finance_revision_treats_deterministic_gate_as_delete_instruction(
        self, mock_llm, sample_brief, sample_draft
    ):
        from omnicast.models.script import CriticFeedback

        feedback = CriticFeedback(
            variant_id="A",
            dimensions=[],
            total_score=70,
            approved=False,
            rejection_reasons=["HARD GATE (verified evidence)"],
            specific_fixes=["Delete an unsupported prevalence claim."],
        )
        prompt = WriterAgent(llm=mock_llm)._build_revision_prompt(
            sample_draft,
            feedback,
            sample_brief,
            niche_cfg=get_niche_config("finance", "retirement_senior"),
        )

        assert "deterministic evidence-boundary complaint is a DELETE instruction" in prompt
        assert "same named" in prompt

    async def test_finance_patch_salvages_noncompliant_full_script_response(
        self, mock_llm, sample_brief
    ):
        scene = (
            '{"vo":"A complete substantive sentence stays inside the verified '
            'mechanism here.","visual":"SSA document","sfx":null,'
            '"pace":"normal","pause_after_ms":0,"emphasis":[]}')
        mock_llm.complete.return_value = _make_llm_response(
            "HOOK:\nSCENES:\n[]\n"
            "SEGMENT 1: The cash-flow window\nSCENES:\n["
            + ",".join([scene, scene, scene])
            + "]\nOUTRO:\nSCENES:\n[]"
        )
        original = ScriptScene(
            voiceover="The verified rule changes the check.",
            visual_prompt="SSA document")
        draft = ScriptDraft(
            variant_id="A", brief_title=sample_brief.title, hook="",
            segments=[ScriptSegment(
                index=1, heading="The cash-flow window",
                content=original.voiceover, estimated_duration_seconds=5,
                scenes=[original])],
            editorial_angle={"thesis": "A delay and a loss are different"},
        )

        grown = await WriterAgent(llm=mock_llm)._ensure_length(
            draft, sample_brief, "system", "CURRENT", "A",
            narrative=False,
        )

        assert mock_llm.complete.call_count == 1
        assert len(grown.segments[0].scenes) == 3
