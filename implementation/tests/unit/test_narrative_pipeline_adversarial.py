"""RED-team contracts for the narrative unit pipeline.

These tests intentionally describe the release-safe public API before it exists.
They protect boundaries that are easy for an LLM-driven pipeline to bypass while
still producing fluent prose: channel strategy isolation, forensic grounding,
atomic edits, blind candidate selection, release invariants, and immutable VO.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

import omnicast.agents.narrative_pipeline as np
from omnicast.models.enums import Market, Niche, TopicSource
from omnicast.models.script import TopicBrief


def _brief(channel_id: str = "true_dread_files_us") -> TopicBrief:
    return TopicBrief(
        title="3 True Encounters in a Self-Storage Facility After Midnight",
        niche=Niche.PSYCHOLOGY,
        market=Market.US,
        source=TopicSource.MANUAL,
        target_duration_min=15,
        channel_id=channel_id,
    )


def _story_plan(index: int) -> np.NarrativeStoryPlan:
    return np.NarrativeStoryPlan(
        story_id=f"story_{index}",
        title=f"Unit {index}",
        narrator_profile=f"narrator {index} with a distinct job and cadence",
        setting=f"different storage building {index}",
        setup_requirement=f"ordinary work routine {index} established before danger",
        threat=f"different human threat {index}",
        threat_type="human",
        escape_action=f"different practical escape {index}",
        ending_shape=("immediate escape", "quiet unresolved departure", "social near miss")[index - 1],
        evidence_allowance=("none", "physical", "none")[index - 1],
        voice_rules=f"voice pattern {index}",
        threat_mechanism=("blocks_path", "pursues", "intrudes_space")[index - 1],
        progression_mechanism=(
            "silent_stillness", "steady_approach", "repeat_sightings",
        )[index - 1],
        escape_mechanism=(
            "flee_to_occupied_place", "vehicle_escape", "barricade_in_place",
        )[index - 1],
        aftermath_mechanism=(
            "no_explanation_offered", "physical_trace_found", "told_no_one",
        )[index - 1],
        threat_identity=("lone_stranger", "known_regular", "group")[index - 1],
        topic_promise=f"a night storage shift {index} in the facility the topic names",
        distinguishing_turn=(
            f"stock prowler would flee; this one already knows the narrator's rota {index}"
        ),
        narrator_age_band="adult",
        safety_obligation="not_applicable",
        continuity_ledger=[
            "hook_timeline: hook occurs before the escape",
            "people_objects: one narrator and one phone",
            "locations_exits: corridor leads to one exit",
            "props_threat_position: threat stays beyond the latch",
            "response_escape: narrator reaches the exit",
        ],
    )


def _plan() -> np.CompilationPlan:
    return np.CompilationPlan(
        topic=_brief().title,
        cold_open="The padlock was hanging open from the inside.",
        target_word_count=2250,
        stories=[_story_plan(i) for i in range(1, 4)],
    )


def _narration(seed: str, words: int = 730) -> str:
    """Stable unique filler that does not accidentally trip repetition gates."""
    safe_seed = seed.translate(str.maketrans("1234567890", "abcdefghij"))
    alpha = lambda value: chr(97 + (value // 26) % 26) + chr(97 + value % 26)
    return "\n\n".join(
        f"{safe_seed} detail{alpha(idx)} "
        + " ".join(f"{safe_seed}{alpha(idx)}{alpha(n)}" for n in range(18))
        for idx in range(max(1, words // 20))
    )


def _draft(index: int, narration: str | None = None) -> np.StoryDraft:
    return np.StoryDraft(
        story_id=f"story_{index}",
        title=f"Unit {index}",
        hook_candidates=[f"hook {index}"],
        narration=narration or _narration(f"story{index}"),
    )


def _passing_score(*, issues: list[np.StoryIssue] | None = None) -> np.NarrativeScorecard:
    return np.NarrativeScorecard(
        continuity_believability=23,
        distinct_authentic_voices=17,
        dread_escalation=17,
        plausible_response=8,
        structural_variety=8,
        originality=8,
        ending_discipline=4,
        critical_issues=[],
        story_issues=issues or [],
    )


def _annotations(stories: list[np.StoryDraft]) -> list[np.StoryAnnotation]:
    return [
        np.StoryAnnotation(
            story_id=story.story_id,
            beats=[
                np.BeatAnnotation(beat_id=beat_id, visual_prompt="dark storage corridor")
                for beat_id, _ in np._split_beats(story)
            ],
        )
        for story in stories
    ]


# ---------------------------------------------------------------------------
# Named channel strategies must be explicit and isolated.


def test_named_channel_strategy_registry_isolates_profiles_and_rejects_unknown_id():
    strategy_type = getattr(np, "NamedChannelStrategy")
    registry_type = getattr(np, "ChannelStrategyRegistry")
    channel_a = strategy_type(
        strategy_id="restrained_real_horror",
        writer_rules="A_ONLY_PLAIN_SUBMISSION",
        critic_rules="A_ONLY_UNDERCONFIRM",
        annotation_rules="A_ONLY_REAL_STOCK",
    )
    channel_b = strategy_type(
        strategy_id="literary_ghost_letters",
        writer_rules="B_ONLY_EPISTOLARY",
        critic_rules="B_ONLY_PERIOD_VOICE",
        annotation_rules="B_ONLY_ARCHIVAL",
    )
    registry = registry_type([channel_a, channel_b])

    selected_a = registry.require("restrained_real_horror")
    selected_b = registry.require("literary_ghost_letters")
    assert selected_a.writer_rules == "A_ONLY_PLAIN_SUBMISSION"
    assert "B_ONLY" not in selected_a.model_dump_json()
    assert selected_b.writer_rules == "B_ONLY_EPISTOLARY"
    assert "A_ONLY" not in selected_b.model_dump_json()

    with pytest.raises(ValueError, match="Unknown channel strategy"):
        registry.require("does_not_exist")


def test_named_channel_strategy_registry_rejects_duplicate_ids():
    strategy_type = getattr(np, "NamedChannelStrategy")
    registry_type = getattr(np, "ChannelStrategyRegistry")
    first = strategy_type(
        strategy_id="same_id", writer_rules="A", critic_rules="A", annotation_rules="A"
    )
    second = strategy_type(
        strategy_id="same_id", writer_rules="B", critic_rules="B", annotation_rules="B"
    )
    with pytest.raises(ValueError, match="Duplicate channel strategy"):
        registry_type([first, second])


# ---------------------------------------------------------------------------
# Exact-number budgets include written-out numbers, not only digits.


def test_spelled_out_numeric_anchors_count_toward_specificity_budget():
    over_specific = (
        "After six years there, I had worked three hundred closing shifts. "
        "The drive took eleven minutes. The gate lagged for forty seconds. "
        "The hallway had seventeen units. He stopped two hundred yards away. "
        "The rent was nine hundred a month. There were twelve keys on the ring. The lot held fifty cars. The code had eight digits. It was ninety feet to the dock and thirty feet to the gate. "
        + _narration("specific", 680)
    )
    stories = [_draft(1, over_specific), _draft(2), _draft(3)]

    report = np.gate_compilation(_plan(), stories)

    assert "specificity_budget" in {failure.code for failure in report.failures}


def test_repeated_written_anchor_counts_once_and_vague_quantities_do_not_count():
    acceptable = (
        "I had worked there six years. Six years was long enough to know the gate. "
        "After six years I recognized every normal sound. The drive took eleven minutes. "
        "I waited forty seconds, crossed seventeen units, and then ran a few blocks. "
        "A couple of people were still outside. "
        + _narration("acceptable", 670)
    )
    stories = [_draft(1, acceptable), _draft(2), _draft(3)]

    report = np.gate_compilation(_plan(), stories)

    assert "specificity_budget" not in {failure.code for failure in report.failures}


def test_ordinary_number_words_are_not_treated_as_fake_precision():
    ordinary = (
        "Someone knocked once, but no one answered. First I checked the latch. "
        "The second thing I noticed was the smell. One of us stayed by the office. "
        + _narration("ordinary", 690)
    )
    report = np.gate_compilation(_plan(), [_draft(1, ordinary), _draft(2), _draft(3)])
    assert "specificity_budget" not in {failure.code for failure in report.failures}


def test_spelled_out_clock_times_count_toward_clock_budget():
    clocks = (
        "The first call came at two seventeen a.m. The second came at three forty p.m. "
        "The third came at four ten a.m., the fourth at five fifteen p.m., the fifth at six twenty a.m., the sixth at seven thirty p.m. "
        + _narration("clocks", 700)
    )
    report = np.gate_compilation(_plan(), [_draft(1, clocks), _draft(2), _draft(3)])
    assert "specificity_budget" in {failure.code for failure in report.failures}


def test_numbered_unit_sequence_counts_as_one_identity_anchor():
    identity = (
        "The directory listed 1, 2, 3, 4. I had worked there six years, made nine "
        "calls, and crossed twenty yards. " + _narration("units", 690)
    )
    report = np.gate_compilation(_plan(), [_draft(1, identity), _draft(2), _draft(3)])
    assert "specificity_budget" not in {failure.code for failure in report.failures}


def test_later_and_lost_track_do_not_fake_a_physical_evidence_match():
    ordinary = (
        "It was later than I meant to be awake, probably close to midnight, and I had "
        "lost track of the show. " + _narration("later", 690)
    )
    report = np.gate_compilation(_plan(), [_draft(1, ordinary), _draft(2), _draft(3)])
    codes = {failure.code for failure in report.failures}
    assert "unplanned_evidence" not in codes
    assert "evidence_budget" not in codes


def test_live_camera_and_non_witness_language_are_not_aftermath_evidence():
    live = (
        "The live camera showed him crossing the lot, so I locked the office. "
        "I had no witness with me. My manager already knew I was working alone. "
        + _narration("livecamera", 680)
    )
    report = np.gate_compilation(_plan(), [_draft(1, live), _draft(2), _draft(3)])
    codes = {failure.code for failure in report.failures}
    assert "unplanned_evidence" not in codes
    assert "evidence_budget" not in codes


def test_ledger_requires_ordered_unique_concise_category_entries():
    payload = _story_plan(1).model_dump()
    payload["continuity_ledger"] = ["same"] * 5
    with pytest.raises(ValidationError, match="ledger|hook_timeline"):
        np.NarrativeStoryPlan.model_validate(payload)

    copied = _story_plan(1).model_copy(update={"continuity_ledger": ["same"] * 5})
    bad_plan = _plan().model_copy(update={"stories": [copied, *_plan().stories[1:]]})
    errors = np.validate_plan_preflight(bad_plan, 3)
    assert any("five unique" in error for error in errors)

    bare = _story_plan(1).model_dump()
    bare["continuity_ledger"] = [
        "hook_timeline:", "people_objects:", "locations_exits:",
        "props_threat_position:", "response_escape:",
    ]
    with pytest.raises(ValidationError, match="fact words"):
        np.NarrativeStoryPlan.model_validate(bare)


def test_zero_evidence_profile_rejects_planned_evidence_before_story_calls():
    strategy = np.NamedChannelStrategy(
        strategy_id="zero_evidence",
        writer_rules="plain",
        critic_rules="strict",
        annotation_rules="literal",
        evidence_beat_limit=0,
    )
    errors = np.validate_plan_preflight(_plan(), 3, strategy)
    assert any("at most 0 stories" in error for error in errors)


# ---------------------------------------------------------------------------
# The critic must ground every actionable issue in exact source text.


def test_story_issue_schema_carries_forensic_kind_quote_and_anchor():
    required = {"issue_kind", "evidence_quote", "anchor_quote"}
    assert required <= set(np.StoryIssue.model_fields)


def test_forensic_validation_rejects_hallucinated_cross_story_and_ambiguous_quotes():
    validate = getattr(np, "validate_forensic_issues")
    repeated = "The east latch clicked twice."
    story_1 = _draft(1, repeated + " " + _narration("one", 690) + " " + repeated)
    story_2 = _draft(2, "The loading door rolled upward. " + _narration("two", 700))
    stories = [story_1, story_2, _draft(3)]
    issues = [
        np.StoryIssue.model_validate({
            "story_id": "story_1", "severity": "major", "issue_kind": "contradiction",
            "problem": "invented position", "repair_instruction": "fix the position",
            "evidence_quote": "The west latch broke in my hand.", "anchor_quote": "",
        }),
        np.StoryIssue.model_validate({
            "story_id": "story_1", "severity": "major", "issue_kind": "contradiction",
            "problem": "quote belongs elsewhere", "repair_instruction": "fix the door",
            "evidence_quote": "The loading door rolled upward.", "anchor_quote": "",
        }),
        np.StoryIssue.model_validate({
            "story_id": "story_1", "severity": "major", "issue_kind": "contradiction",
            "problem": "ambiguous anchor", "repair_instruction": "fix the latch",
            "evidence_quote": repeated, "anchor_quote": "",
        }),
    ]

    errors = validate(_passing_score(issues=issues), stories)

    assert len(errors) == 3
    assert any("not found" in error.lower() for error in errors)
    assert any("different story" in error.lower() for error in errors)
    assert any("unique" in error.lower() for error in errors)


def test_forensic_omission_requires_a_unique_exact_insertion_anchor():
    validate = getattr(np, "validate_forensic_issues")
    anchor = "I pulled the office door shut behind me."
    stories = [_draft(1, anchor + " " + _narration("one", 700)), _draft(2), _draft(3)]
    missing_anchor = np.StoryIssue.model_validate({
        "story_id": "story_1", "severity": "major", "issue_kind": "omission",
        "problem": "escape beat is absent", "repair_instruction": "insert the locked escape",
        "evidence_quote": "", "anchor_quote": "A sentence that is not in the story.",
    })
    valid_anchor = missing_anchor.model_copy(update={"anchor_quote": anchor})

    assert validate(_passing_score(issues=[missing_anchor]), stories)
    assert validate(_passing_score(issues=[valid_anchor]), stories) == []


# ---------------------------------------------------------------------------
# Exact patches are atomic, bounded, and candidate alternatives share a baseline.


def test_patch_bundle_is_atomic_when_one_edit_is_invalid():
    story = _draft(1, "The latch clicked. I ran for the office. " + _narration("atomic", 700))
    patch = np.StoryPatchOutput(edits=[
        np.StoryTextEdit(find="The latch clicked.", replace="The latch snapped."),
        np.StoryTextEdit(find="This sentence does not exist.", replace="Injected text."),
    ])

    with pytest.raises(ValueError, match="atomic|exact|unique"):
        np._apply_story_patch(story, patch)


def test_patch_bundle_rejects_cascading_or_overlapping_edits():
    story = _draft(1, "The latch clicked. I ran for the office. " + _narration("cascade", 700))
    cascading = np.StoryPatchOutput(edits=[
        np.StoryTextEdit(find="The latch clicked.", replace="The lock snapped."),
        np.StoryTextEdit(find="The lock snapped.", replace="The whole door vanished."),
    ])

    with pytest.raises(ValueError, match="baseline|overlap|exact"):
        np._apply_story_patch(story, cascading)


def test_patch_bundle_cannot_delete_or_replace_most_of_a_story():
    story = _draft(1)
    destructive = np.StoryPatchOutput(edits=[
        np.StoryTextEdit(find=story.narration, replace="I left."),
    ])

    with pytest.raises(ValueError, match="budget|large|destructive"):
        np._apply_story_patch(story, destructive)


def test_patch_can_replace_one_issue_paragraph_when_total_edit_stays_surgical():
    issue_paragraph = " ".join(f"issueword{index}" for index in range(90))
    untouched = _narration("untouched", 610)
    story = _draft(1, issue_paragraph + "\n\n" + untouched)
    replacement = " ".join(f"fixedword{index}" for index in range(82))
    patch = np.StoryPatchOutput(edits=[
        np.StoryTextEdit(find=issue_paragraph, replace=replacement),
    ])

    repaired = np._apply_story_patch(story, patch)

    assert repaired.narration.startswith(replacement)
    assert repaired.narration.endswith(untouched)


def test_patch_candidate_set_requires_exactly_two_candidates():
    candidate_set_type = getattr(np, "StoryPatchCandidateSet")
    one = {
        "candidates": [{
            "candidate_id": "candidate_1",
            "edits": [{"find": "The latch clicked.", "replace": "The latch snapped."}],
        }]
    }
    three = {
        "candidates": [
            {"candidate_id": key, "edits": [{"find": "The latch clicked.", "replace": text}]}
            for key, text in (("candidate_1", "The latch snapped."),
                              ("candidate_2", "The latch lifted."),
                              ("candidate_1", "The latch disappeared."))
        ]
    }

    with pytest.raises(ValidationError):
        candidate_set_type.model_validate(one)
    with pytest.raises(ValidationError):
        candidate_set_type.model_validate(three)

    with pytest.raises(ValidationError):
        candidate_set_type.model_validate({
            "candidates": [
                {"candidate_id": "A", "edits": [
                    {"find": "The latch clicked.", "replace": "The latch snapped."}
                ]},
                {"candidate_id": "B", "edits": [
                    {"find": "The latch clicked.", "replace": "The latch lifted."}
                ]},
            ]
        })


def test_two_patch_candidates_are_materialized_from_the_same_baseline():
    candidate_set_type = getattr(np, "StoryPatchCandidateSet")
    materialize = getattr(np, "materialize_patch_candidates")
    story = _draft(1, "The latch clicked. I ran for the office. " + _narration("baseline", 700))
    candidates = candidate_set_type.model_validate({
        "candidates": [
            {"candidate_id": "candidate_1", "edits": [
                {"find": "The latch clicked.", "replace": "The latch snapped."}
            ]},
            {"candidate_id": "candidate_2", "edits": [
                {"find": "The latch clicked.", "replace": "The latch lifted by itself."}
            ]},
        ]
    })

    outputs = materialize(story, candidates)

    assert set(outputs) == {"candidate_1", "candidate_2"}
    assert outputs["candidate_1"].narration.startswith("The latch snapped.")
    assert "lifted by itself" not in outputs["candidate_1"].narration
    assert outputs["candidate_2"].narration.startswith("The latch lifted by itself.")
    assert "snapped" not in outputs["candidate_2"].narration


def test_blind_selector_tie_or_hallucinated_candidate_keeps_baseline():
    resolve = getattr(np, "resolve_blind_patch_selection")
    baseline = _draft(1, "The latch clicked. " + _narration("blind", 700))
    candidates = {
        "A": baseline.model_copy(update={"narration": baseline.narration.replace("clicked", "snapped", 1)}),
        "B": baseline.model_copy(update={"narration": baseline.narration.replace("clicked", "lifted", 1)}),
    }

    assert resolve("tie", baseline, candidates).narration == baseline.narration
    assert resolve("C", baseline, candidates).narration == baseline.narration


# ---------------------------------------------------------------------------
# A selected edit is never equivalent to a final release decision.


def test_pipeline_result_cannot_claim_lock_or_production_ready_when_final_gate_fails():
    bad_story = _draft(1, "I told myself it was nothing. " + _narration("bad", 700))
    stories = [bad_story, _draft(2), _draft(3)]
    gate = np.gate_compilation(_plan(), stories)
    assert gate.passed is False
    annotations = _annotations(stories)
    draft = np._assemble(_plan(), stories, annotations)

    with pytest.raises(ValidationError, match="gate|lock|release"):
        np.NarrativePipelineResult(
            plan=_plan(),
            stories=stories,
            gate_report=gate,
            scorecard=_passing_score(),
            content_locked=True,
            annotations=annotations,
            production_ready=True,
            draft=draft,
            plan_audit=np.PlanAuditResult(status="valid"),
            release_challenge=np.ReleaseChallengeResult(status="not_required"),
        )


# ---------------------------------------------------------------------------
# Production metadata cannot change even punctuation or capitalization in VO.


def test_assembly_preserves_locked_voiceover_case_and_punctuation_exactly():
    narration = (
        'ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œDON\'T move,ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â Mara whisperedÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Âthen stopped... ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œWho IS there?ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â\n\n'
        "I couldn't answer; the latch clicked once. "
        + _narration("punctuation", 690)
    )
    stories = [_draft(1, narration), _draft(2), _draft(3)]
    annotations = _annotations(stories)

    draft = np._assemble(_plan(), stories, annotations)
    rendered = " ".join(scene.voiceover for scene in draft.segments[0].scenes)

    normalize_space = lambda text: " ".join(text.split())
    assert normalize_space(rendered) == normalize_space(narration)
    assert draft.segments[0].content == narration


def test_annotation_models_reject_any_attempt_to_return_voiceover():
    with pytest.raises(ValidationError):
        np.BeatAnnotation.model_validate({
            "beat_id": "story_1_beat_01",
            "visual_prompt": "dark storage corridor",
            "voiceover": "A rewritten line that must never be accepted.",
        })
