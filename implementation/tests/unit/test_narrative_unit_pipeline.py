"""Unit-first narrative pipeline quality and release invariants."""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

import omnicast.agents.narrative_pipeline as np
from omnicast.agents.narrative_pipeline import (
    CompilationPlan,
    BeatAnnotation,
    BlindPatchSelection,
    FinalCompilationReview,
    NarrativePipelineResult,
    NarrativeScorecard,
    NarrativeStoryPlan,
    NarrativeUnitPipeline,
    PlanAuditResult,
    PlanPlausibilityReview,
    ReleaseChallengeResult,
    StoryAnnotation,
    StoryBeatCheck,
    StoryComplianceReview,
    StoryDraft,
    StoryIssue,
    StoryOutput,
    StoryPatchCandidate,
    StoryPatchCandidateSet,
    StoryTextEdit,
    _assemble,
    _narration_sha256,
    _split_beats,
    _story_plan_fingerprint,
    content_can_lock,
    gate_compilation,
    locked_voiceover_sha256,
)
from omnicast.llm import LLMResponse
from omnicast.models.enums import Market, Niche, TopicSource
from omnicast.models.script import TopicBrief


def _brief() -> TopicBrief:
    return TopicBrief(
        title="3 True Encounters in a Self-Storage Facility After Midnight",
        niche=Niche.PSYCHOLOGY,
        market=Market.US,
        source=TopicSource.MANUAL,
        target_duration_min=15,
        channel_id="true_dread_files_us",
    )


def _story_plan(index: int) -> NarrativeStoryPlan:
    shapes = ["immediate escape", "quiet unresolved departure", "social near miss"]
    evidence = ["none", "physical", "none"]
    # Distinct on every typed axis: the mechanism-diversity gate must see a
    # legitimately varied compilation here, so tests fail on what they target.
    threats = ["blocks_path", "pursues", "intrudes_space"]
    progressions = ["silent_stillness", "steady_approach", "repeat_sightings"]
    escapes = ["flee_to_occupied_place", "vehicle_escape", "barricade_in_place"]
    aftermaths = ["no_explanation_offered", "physical_trace_found", "told_no_one"]
    identities = ["lone_stranger", "known_regular", "group"]
    return NarrativeStoryPlan(
        story_id=f"story_{index}",
        title=f"Unit {index}",
        narrator_profile=f"narrator {index} with a distinct job and cadence",
        setting=f"different storage building {index}",
        setup_requirement=f"ordinary work routine {index} established before danger",
        threat=f"different human threat {index}",
        threat_type="human",
        escape_action=f"different practical escape {index}",
        ending_shape=shapes[index - 1],
        evidence_allowance=evidence[index - 1],
        voice_rules=f"voice pattern {index}",
        threat_mechanism=threats[index - 1],
        progression_mechanism=progressions[index - 1],
        escape_mechanism=escapes[index - 1],
        aftermath_mechanism=aftermaths[index - 1],
        threat_identity=identities[index - 1],
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
            "props_threat_position: threat stays beyond the office",
            "response_escape: narrator reaches the exit",
        ],
    )


def _plan() -> CompilationPlan:
    return CompilationPlan(
        topic=_brief().title,
        cold_open="The padlock was hanging open from the inside.",
        target_word_count=2250,
        stories=[_story_plan(i) for i in range(1, 4)],
    )


_MECHANISM_POOL = {
    "threat_mechanism": [
        "blocks_path", "pursues", "intrudes_space", "lures_or_deceives",
        "traps_or_confines", "watches_without_approach", "ambush_reveal",
        "environmental_anomaly",
    ],
    "progression_mechanism": [
        "silent_stillness", "steady_approach", "sudden_rush", "repeat_sightings",
        "escalating_contact", "discovery_of_evidence", "exits_close_one_by_one",
        "impersonation_or_mimicry",
    ],
    "escape_mechanism": [
        "flee_to_occupied_place", "vehicle_escape", "barricade_in_place",
        "physical_confrontation", "call_for_help", "evade_by_route_knowledge",
        "third_party_intervenes", "climb_or_vault_barrier",
    ],
    "aftermath_mechanism": [
        "no_explanation_offered", "authority_response", "witness_corroboration",
        "physical_trace_found", "recurrence_later", "identity_partially_learned",
        "routine_permanently_changed", "told_no_one",
    ],
}


def _variant_plan(generation: int) -> CompilationPlan:
    """A genuinely distinct compilation concept, for tests that need a real replan.

    Two properties the planner-retry and outer-retry tests depend on, and which a
    hand-tweaked copy of _plan() quietly fails to provide:

    * within a plan, the three stories differ on every typed axis, so the
      mechanism-diversity preflight passes;
    * across generations, at most one story shares a concept, so the freshness gate
      sees a materially new compilation rather than a reshuffle. The stride of 3
      over an 8-value pool is what buys that: generations 0/1/2 occupy slots
      {0,1,2}, {3,4,5}, {6,7,0}.

    Tests that want a rejected plan use a deliberately broken variant instead;
    freshness is never weakened to make a fixture convenient.
    """
    plan = _plan()
    stories = [
        story.model_copy(update={
            axis: pool[(index + generation * 3) % len(pool)]
            for axis, pool in _MECHANISM_POOL.items()
        } | {"title": f"Unit {index + 1} gen {generation}"})
        for index, story in enumerate(plan.stories)
    ]
    return plan.model_copy(update={"stories": stories})


def _narration(seed: str, words: int = 730) -> str:
    # Unique paragraphs avoid accidental repetition flags while preserving a stable count.
    seed = seed.translate(str.maketrans("1234567890", "abcdefghij"))
    alpha = lambda value: chr(97 + (value // 26) % 26) + chr(97 + value % 26)
    return "\n\n".join(
        f"{seed} detail{alpha(idx)} "
        + " ".join(f"{seed}{alpha(idx)}{alpha(n)}" for n in range(18))
        for idx in range(max(1, words // 20))
    )


def _draft(index: int, words: int = 730) -> StoryDraft:
    return StoryDraft(
        story_id=f"story_{index}",
        title=f"Unit {index}",
        hook_candidates=[f"hook {index} a", f"hook {index} b"],
        narration=_narration(f"s{index}", words),
    )


def _passing_score() -> NarrativeScorecard:
    return NarrativeScorecard(
        continuity_believability=23,
        distinct_authentic_voices=17,
        dread_escalation=17,
        plausible_response=8,
        structural_variety=8,
        originality=8,
        ending_discipline=4,
        critical_issues=[],
        story_issues=[],
    )


def _approved_final_review() -> FinalCompilationReview:
    return FinalCompilationReview(
        approved=True,
        reviewed_story_ids=["story_1", "story_2", "story_3"],
        issues=[],
        summary="clean",
    )


def _release_evidence() -> dict:
    """The pre-writer evidence a content lock claims to rest on.

    A locked result asserts that its premise was audited and that an adversary was
    given a chance to veto it. Tests that construct results directly to probe a
    different invariant (a drifted hash, a forged draft, a weak score) supply the
    evidence here so they fail on the property they name, not on this one.
    """
    return {
        "plan_audit": PlanAuditResult(status="valid"),
        "release_challenge": ReleaseChallengeResult(status="not_required"),
    }


def _compliance_reviews(stories: list[StoryDraft]) -> list[StoryComplianceReview]:
    reviews = []
    beat_ids = (
        "ordinary_setup", "threat_confirmation", "decision_action",
        "completed_escape", "completed_ending",
    )
    for story in stories:
        plan = _story_plan(int(story.story_id[-1]))
        requirements = (
            plan.setup_requirement, plan.threat, plan.escape_action,
            plan.escape_action, plan.ending_shape,
        )
        quotes = [item.strip() for item in story.narration.split("\n\n") if item.strip()][:5]
        reviews.append(StoryComplianceReview(
            story_id=story.story_id,
            plan_fingerprint=_story_plan_fingerprint(plan),
            narration_sha256=_narration_sha256(story),
            beats=[StoryBeatCheck(
                beat_id=beat_id, locked_requirement=requirement,
                status="complete", evidence_quote=quote,
            ) for beat_id, requirement, quote in zip(
                beat_ids, requirements, quotes, strict=True
            )],
            plan_facts_status="preserved", evidence_budget_status="preserved",
        ))
    return reviews


def _select_changed_option(prompt: str) -> BlindPatchSelection:
    labels = re.findall(r'"label":\s*"(option_\d+)"', prompt)
    selected = labels[0]
    for label in labels:
        start = prompt.index(f'"label": "{label}"')
        next_positions = [prompt.find(f'"label": "{other}"', start + 1) for other in labels]
        ends = [value for value in next_positions if value >= 0]
        chunk = prompt[start:min(ends) if ends else len(prompt)]
        if "I told myself" not in chunk:
            selected = label
            break
    return BlindPatchSelection(
        selected_label=selected, confidence=0.92, preserves_locked_plan=True,
        resolves_target_issues=True, introduced_issues=[], rationale="clean local repair",
    )


def _select_option_containing(prompt: str, needle: str) -> BlindPatchSelection:
    labels = re.findall(r'"label":\s*"(option_\d+)"', prompt)
    selected = labels[0]
    for label in labels:
        start = prompt.index(f'"label": "{label}"')
        later = [
            prompt.find(f'"label": "{other}"', start + 1)
            for other in labels
        ]
        ends = [value for value in later if value >= 0]
        if needle in prompt[start:min(ends) if ends else len(prompt)]:
            selected = label
            break
    return BlindPatchSelection(
        selected_label=selected, confidence=0.93, preserves_locked_plan=True,
        resolves_target_issues=True, introduced_issues=[], rationale="targeted local repair",
    )


class _FakeStructuredLLM:
    def __init__(self, handler, *, auto_compliance: bool = True,
                 auto_plan_audit: bool = True):
        self.handler = handler
        self.auto_compliance = auto_compliance
        # The plan audit is an auxiliary call most tests do not care about;
        # auto-answer it clean so score iterators are not consumed by it.
        # Tests exercising the audit itself pass auto_plan_audit=False.
        self.auto_plan_audit = auto_plan_audit
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []

    async def complete_structured(self, *, messages, output_schema, **kwargs):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        try:
            if output_schema is PlanPlausibilityReview and self.auto_plan_audit:
                return LLMResponse(
                    content="{}", model="fake", input_tokens=1, output_tokens=1,
                    cost_usd=0.0, stop_reason="stop",
                ), PlanPlausibilityReview()
            if output_schema is StoryComplianceReview and self.auto_compliance:
                sid = re.search(r"story_id:\s*(story_\d+)", prompt).group(1)
                fingerprint = re.search(r"plan_fingerprint:\s*([0-9a-f]{64})", prompt).group(1)
                narration_hash = re.search(r"narration_sha256:\s*([0-9a-f]{64})", prompt).group(1)
                plan_text = prompt.split("LOCKED PLAN:\n", 1)[1].split("\n\nNARRATION:\n", 1)[0]
                narration = prompt.split("\n\nNARRATION:\n", 1)[1]
                plan = json.loads(plan_text)
                quotes = [item.strip() for item in narration.split("\n\n") if item.strip()][:5]
                requirements = (
                    plan["setup_requirement"], plan["threat"], plan["escape_action"],
                    plan["escape_action"], plan["ending_shape"],
                )
                beat_ids = (
                    "ordinary_setup", "threat_confirmation", "decision_action",
                    "completed_escape", "completed_ending",
                )
                return LLMResponse(
                    content="{}", model="fake", input_tokens=1, output_tokens=1,
                    cost_usd=0.0, stop_reason="stop",
                ), StoryComplianceReview(
                    story_id=sid, plan_fingerprint=fingerprint,
                    narration_sha256=narration_hash,
                    beats=[StoryBeatCheck(
                        beat_id=beat_id, locked_requirement=requirement,
                        status="complete", evidence_quote=quote,
                    ) for beat_id, requirement, quote in zip(
                        beat_ids, requirements, quotes, strict=True
                    )],
                    plan_facts_status="preserved",
                    evidence_budget_status="preserved",
                )
            value = self.handler(prompt, output_schema)
            return LLMResponse(content="{}", model="fake", input_tokens=1,
                               output_tokens=1, cost_usd=0.0, stop_reason="stop"), value
        finally:
            self.active -= 1

    async def complete(self, *, messages, **kwargs):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        try:
            schema = (
                FinalCompilationReview
                if "Perform a final read-only compilation audit" in prompt
                else StoryOutput
            )
            value = self.handler(prompt, schema)
            content = value.model_dump_json() if isinstance(value, BaseModel) else json.dumps(value)
            return LLMResponse(content=content, model="fake", input_tokens=1,
                               output_tokens=1, cost_usd=0.0, stop_reason="stop")
        finally:
            self.active -= 1


def test_gate_rejects_ai_tells_evidence_stacking_and_repetition():
    drafts = [_draft(1), _draft(2), _draft(3)]
    bad = drafts[0].model_copy(update={
        "narration": (
            "I told myself it was nothing. The next morning the camera recording showed static. "
            "The police later confirmed it. " + _narration("bad", 700)
        )
    })
    repeated = drafts[1].model_copy(update={
        "narration": drafts[1].narration + "\n\n" + drafts[1].narration.split("\n\n")[0]
    })

    report = gate_compilation(_plan(), [bad, repeated, drafts[2]])

    codes = {failure.code for failure in report.failures}
    assert "banned_self_reassurance" in codes
    assert "evidence_budget" in codes
    assert "repeated_paragraph" in codes
    assert report.passed is False


@pytest.mark.parametrize(
    "phrase",
    [
        "I figure it's pipes.",
        "I did that thing where you tell yourself it lines up with something ordinary.",
        "I almost had myself convinced it was the radiator.",
    ],
)
def test_gate_rejects_paraphrased_stock_self_reassurance(phrase):
    stories = [_draft(1), _draft(2), _draft(3)]
    stories[0] = stories[0].model_copy(update={
        "narration": phrase + " " + _narration("paraphrase", 700)
    })
    report = gate_compilation(_plan(), stories)
    assert "banned_self_reassurance" in {item.code for item in report.failures}


def test_evidence_gate_ignores_live_safety_actions_but_flags_aftermath_stacking():
    drafts = [_draft(1), _draft(2), _draft(3)]
    direct_actions = drafts[0].model_copy(update={
        "narration": (
            "I watched the live security camera, called the police, and stayed behind "
            "the locked office door. " + _narration("direct", 680)
        )
    })
    direct_report = gate_compilation(_plan(), [direct_actions, drafts[1], drafts[2]])
    direct_codes = {failure.code for failure in direct_report.failures}
    assert "unplanned_evidence" not in direct_codes
    assert "evidence_budget" not in direct_codes

    unrelated_sentences = drafts[0].model_copy(update={
        "narration": (
            "I watched the live security camera. The door lock failed without warning. "
            "I called the police. My flashlight later revealed a broken window. "
            + _narration("sentences", 680)
        )
    })
    unrelated_report = gate_compilation(
        _plan(), [unrelated_sentences, drafts[1], drafts[2]]
    )
    unrelated_codes = {failure.code for failure in unrelated_report.failures}
    assert "unplanned_evidence" not in unrelated_codes
    assert "evidence_budget" not in unrelated_codes

    stacked = drafts[0].model_copy(update={
        "narration": (
            "The next morning the camera recording showed the figure at the gate. "
            "Police later confirmed that the incident report identified his truck. "
            + _narration("stacked", 680)
        )
    })
    stacked_report = gate_compilation(_plan(), [stacked, drafts[1], drafts[2]])
    stacked_codes = {failure.code for failure in stacked_report.failures}
    assert "evidence_budget" in stacked_codes
    assert "unplanned_evidence" in stacked_codes


@pytest.mark.asyncio
async def test_story_units_generate_concurrently_from_distinct_locked_plans():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())

    def write(prompt, _schema):
        story_id = next(s for s in ("story_1", "story_2", "story_3") if s in prompt)
        index = int(story_id[-1])
        return StoryOutput(
            title=f"Unit {index}", hook_candidates=[f"hook {index}"],
            narration=_narration(f"s{index}"),
        )

    writer = _FakeStructuredLLM(write)
    critic = _FakeStructuredLLM(
        lambda _p, schema: (
            _approved_final_review() if schema is FinalCompilationReview else _passing_score()
        )
    )
    pipeline = NarrativeUnitPipeline(planner, writer, critic, annotation_llm=None)

    result = await pipeline.run(_brief(), annotate=False)

    assert writer.max_active == 3
    assert len(writer.calls) == 3
    assert all(f"story_{i}" in writer.calls[i - 1] for i in range(1, 4))
    assert result.content_locked is True
    assert result.call_counts == {
        "planner": 1, "story_writer": 3, "story_writer_recovery": 0,
        "story_compliance": 3,
        "story_compliance_escalation": 0, "critic_score": 1,
        "repair_writer": 0, "repair_rewrite": 0, "repair_salvage": 0, "plan_audit": 1,
        "plan_audit_escalation": 0, "release_challenger": 0,
        "planner_schema_retry": 0, "plan_repair": 0,
        "critic_score_escalation": 0, "final_editor_escalation": 0,
        "annotation_escalation": 0, "plan_audit_contract_retry": 0,
        "plan_repair_schema_retry": 0,
        "blind_selector": 0, "final_editor": 1, "annotation": 0,
    }


@pytest.mark.asyncio
async def test_only_failed_story_is_repaired_and_clean_stories_are_unchanged():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, schema):
        sid = next(s for s in initial if s in prompt)
        if "Surgically repair" in prompt:
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ",
                    replace="I checked the latch twice. ",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ",
                    replace="I put my thumb against the latch and felt it shift. ",
                )]),
            ])
        d = initial[sid]
        narration = "I told myself it was nothing. " + d.narration if sid == "story_1" else d.narration
        return StoryOutput(title=d.title, hook_candidates=d.hook_candidates, narration=narration)

    scores = iter([
        NarrativeScorecard(
            continuity_believability=20, distinct_authentic_voices=17,
            dread_escalation=16, plausible_response=8, structural_variety=8,
            originality=8, ending_discipline=4, critical_issues=[],
                story_issues=[StoryIssue(
                    story_id="story_1", severity="major", problem="stock rationalization",
                    repair_instruction="replace it with observable behavior",
                    issue_kind="style", evidence_quote="I told myself it was nothing. ",
                    viewer_impact="sounds synthetic", issue_id="stock_1",
                )],
        ),
        _passing_score(),
    ])
    writer = _FakeStructuredLLM(write)
    def judge(prompt, schema):
        if schema is BlindPatchSelection:
            if "wrench_1" in prompt:
                return _select_option_containing(prompt, "I left the wrench behind")
            return _select_changed_option(prompt)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return next(scores)

    critic = _FakeStructuredLLM(judge)
    pipeline = NarrativeUnitPipeline(planner, writer, critic, annotation_llm=None)

    result = await pipeline.run(_brief(), annotate=False)

    # 3 drafts + 1 deterministic recovery attempt (banned phrase; rejected because
    # the recovery echo did not reduce hard failures) + 1 surgical repair call.
    assert len(writer.calls) == 5
    assert result.call_counts["story_writer_recovery"] == 1
    assert "Surgically repair" in writer.calls[-1]
    assert "story_1" in writer.calls[-1]
    assert result.stories[1].narration == initial["story_2"].narration
    assert result.stories[2].narration == initial["story_3"].narration
    assert result.repair_waves == 1
    assert result.content_locked is True
    assert "EXACTLY TWO" in writer.calls[-1]
    assert len(result.patch_decisions) == 1
    assert result.patch_decisions[0].selected in {"candidate_1", "candidate_2"}
    compliance_prompts = [
        prompt for prompt in critic.calls
        if "Perform a narrow mechanical compliance audit" in prompt
    ]
    assert result.call_counts["story_compliance"] == 4
    assert sum("story_id: story_1" in prompt for prompt in compliance_prompts) == 2
    assert sum("story_id: story_2" in prompt for prompt in compliance_prompts) == 1
    assert sum("story_id: story_3" in prompt for prompt in compliance_prompts) == 1


@pytest.mark.asyncio
async def test_failed_changed_story_reaudit_rejects_candidate_before_rescore_or_annotation():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next(value for value in initial if value in prompt)
        if "Surgically repair" in prompt:
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ", replace="I checked the latch. ",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ", replace="I tested the latch. ",
                )]),
            ])
        draft = initial[sid]
        narration = (
            "I told myself it was nothing. " + draft.narration
            if sid == "story_1" else draft.narration
        )
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=narration,
        )

    issue_score = _passing_score().model_copy(update={
        "story_issues": [StoryIssue(
            story_id="story_1", severity="major", issue_kind="style",
            problem="stock phrase", repair_instruction="replace it",
            evidence_quote="I told myself it was nothing. ", viewer_impact="synthetic",
            issue_id="stock_1",
        )]
    })

    class _FailChangedAudit(_FakeStructuredLLM):
        def __init__(self):
            super().__init__(lambda _p, _s: pytest.fail("unexpected compliance handler"))
            self.audit_attempts = 0

        async def complete_structured(self, *, messages, output_schema, **kwargs):
            if output_schema is StoryComplianceReview:
                self.audit_attempts += 1
                if self.audit_attempts > 3:
                    raise ValueError("changed-story audit malformed")
            return await super().complete_structured(
                messages=messages, output_schema=output_schema, **kwargs
            )

    def judge(prompt, schema):
        if schema is BlindPatchSelection:
            return _select_changed_option(prompt)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return issue_score

    compliance = _FailChangedAudit()
    annotation = _FakeStructuredLLM(lambda _p, _s: pytest.fail("annotation must not run"))
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), annotation,
        compliance_llm=compliance,
    ).run(_brief(), annotate=True)

    assert compliance.audit_attempts == 5
    assert result.call_counts["story_compliance"] == 5
    assert result.call_counts["critic_score"] == 1
    assert result.call_counts["annotation"] == 0
    assert result.content_locked is False
    assert result.stories[0].narration.startswith("I told myself")
    assert result.stories[1].narration == initial["story_2"].narration
    assert result.stories[2].narration == initial["story_3"].narration


@pytest.mark.asyncio
async def test_high_scoring_clean_gate_can_use_one_bounded_salvage_wave_for_new_issue():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next(value for value in initial if value in prompt)
        if "Surgically repair" in prompt:
            if sid == "story_1":
                find = "I told myself it was nothing. "
                replacements = ("I checked the latch. ", "I tested the latch. ")
            else:
                find = initial["story_2"].narration.split("\n\n", 1)[0]
                replacements = (
                    find + " I left the wrench behind.",
                    find + " The wrench stayed on the floor.",
                )
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find=find, replace=replacements[0],
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find=find, replace=replacements[1],
                )]),
            ])
        draft = initial[sid]
        narration = (
            "I told myself it was nothing. " + draft.narration
            if sid == "story_1" else draft.narration
        )
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates, narration=narration,
        )

    issue_1 = StoryIssue(
        story_id="story_1", severity="major", issue_kind="style",
        problem="stock phrase", repair_instruction="replace it",
        evidence_quote="I told myself it was nothing. ", viewer_impact="synthetic",
        issue_id="stock_1",
    )
    story_2_anchor = initial["story_2"].narration.split("\n\n", 1)[0]
    issue_2 = StoryIssue(
        story_id="story_2", severity="major", issue_kind="style",
        problem="wrench outcome missing", repair_instruction="confirm it stays behind",
        evidence_quote=story_2_anchor, viewer_impact="object ambiguity", issue_id="wrench_1",
    )
    scores = iter([
        _passing_score().model_copy(update={"story_issues": [issue_1]}),
        _passing_score().model_copy(update={"story_issues": [issue_2]}),
        _passing_score(),
    ])

    def judge(prompt, schema):
        if schema is BlindPatchSelection:
            if "wrench_1" in prompt:
                return _select_option_containing(prompt, "I left the wrench behind")
            return _select_changed_option(prompt)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return next(scores)

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert result.repair_waves == 2
    assert result.content_locked is True
    assert "wrench" in result.stories[1].narration.lower()


@pytest.mark.asyncio
async def test_repair_that_removes_gate_failure_but_lowers_score_is_rolled_back():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, schema):
        sid = next(s for s in initial if s in prompt)
        if "Surgically repair" in prompt:
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ", replace="I checked the latch. ",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ", replace="I tested the latch. ",
                )]),
            ])
        draft = initial[sid]
        narration = (
            "I told myself it was nothing. " + draft.narration
            if sid == "story_1" else draft.narration
        )
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates, narration=narration,
        )

    high_with_issue = _passing_score().model_copy(update={
        "story_issues": [StoryIssue(
            story_id="story_1", severity="major", problem="stock phrase",
            repair_instruction="replace the phrase",
            issue_kind="style", evidence_quote="I told myself it was nothing. ",
            viewer_impact="sounds synthetic", issue_id="stock_1",
        )]
    })
    lower_without_issue = _passing_score().model_copy(update={"originality": 7})
    scores = iter([high_with_issue, lower_without_issue])
    writer = _FakeStructuredLLM(write)
    def rollback_judge(prompt, schema):
        if schema is BlindPatchSelection:
            return _select_changed_option(prompt)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return next(scores)

    critic = _FakeStructuredLLM(rollback_judge)
    pipeline = NarrativeUnitPipeline(planner, writer, critic, annotation_llm=None)

    result = await pipeline.run(_brief(), annotate=False)

    assert result.repair_waves == 1
    assert result.stories[0].narration.startswith("I told myself")
    assert result.content_locked is False


def test_release_requires_content_score_hard_gates_and_exact_annotation_coverage():
    stories = [_draft(i) for i in range(1, 4)]
    gate = gate_compilation(_plan(), stories)
    annotations = [
        StoryAnnotation(story_id=s.story_id, beats=[])
        for s in stories
    ]
    result = NarrativePipelineResult(
        plan=_plan(), stories=stories, gate_report=gate, scorecard=_passing_score(),
        content_locked=True, annotations=annotations, production_ready=False,
        story_compliance_reviews=_compliance_reviews(stories),
        final_editor_approved=True,
        locked_voiceover_sha256=locked_voiceover_sha256(stories),
        release_tier="editorially_ready", **_release_evidence(),
    )

    assert result.scorecard.total_score == 85
    assert result.production_ready is False


def test_major_story_issue_blocks_content_lock_even_when_total_is_high():
    score = _passing_score().model_copy(update={
        "story_issues": [StoryIssue(
            story_id="story_1", severity="major", problem="door changes sides",
            repair_instruction="keep the door on the east wall",
        )]
    })
    assert content_can_lock(score, gate_compilation(_plan(), [_draft(i) for i in range(1, 4)])) is False


def test_scorecard_clamps_dimension_over_awards_before_totaling():
    raw = _passing_score().model_dump()
    raw.update({"plausible_response": 19, "structural_variety": 15, "ending_discipline": 9})
    score = NarrativeScorecard.model_validate(raw)
    assert score.plausible_response == 10
    assert score.structural_variety == 10
    assert score.ending_discipline == 5
    assert score.total_score <= 100


def test_assembly_keeps_cold_open_in_renderable_hook_scene():
    stories = [_draft(i) for i in range(1, 4)]
    annotations = []
    for story in stories:
        annotations.append(StoryAnnotation(
            story_id=story.story_id,
            beats=[BeatAnnotation(beat_id=beat_id, visual_prompt="dark storage corridor")
                   for beat_id, _ in _split_beats(story)],
        ))
    draft = _assemble(_plan(), stories, annotations)
    assert draft.hook == _plan().cold_open
    assert [scene.voiceover for scene in draft.hook_scenes] == [_plan().cold_open]
    assert _plan().stories[0].setting in draft.hook_scenes[0].visual_prompt
    assert "self-storage" not in draft.hook_scenes[0].visual_prompt


def test_production_result_rejects_a_forged_draft_even_with_valid_annotations():
    stories = [_draft(i) for i in range(1, 4)]
    annotations = [
        StoryAnnotation(
            story_id=story.story_id,
            beats=[BeatAnnotation(beat_id=beat_id, visual_prompt="dark corridor")
                   for beat_id, _ in _split_beats(story)],
        )
        for story in stories
    ]
    expected = _assemble(_plan(), stories, annotations)
    forged = expected.model_copy(update={"raw_content": expected.raw_content + " forged"})

    with pytest.raises(ValueError, match="exactly match locked narration"):
        NarrativePipelineResult(
            plan=_plan(), stories=stories,
            gate_report=gate_compilation(_plan(), stories), scorecard=_passing_score(),
            content_locked=True, annotations=annotations, production_ready=True,
            story_compliance_reviews=_compliance_reviews(stories),
            draft=forged, final_editor_approved=True,
            locked_voiceover_sha256=locked_voiceover_sha256(stories),
            release_tier="production_test_ready", **_release_evidence(),
        )


@pytest.mark.asyncio
async def test_bad_plan_is_rejected_every_attempt_before_any_story_call():
    """A structurally broken plan is replanned to the bound, then aborts.

    A planner that resends the identical rejected plan is told so explicitly, and
    the run never reaches a writer or critic call.
    """
    bad = _plan().model_copy(update={
        "stories": [
            item.model_copy(update={"narrator_profile": "same narrator"})
            for item in _plan().stories
        ]
    })
    planner = _FakeStructuredLLM(lambda _p, _s: bad)
    writer = _FakeStructuredLLM(lambda _p, _s: pytest.fail("writer must not be called"))
    critic = _FakeStructuredLLM(lambda _p, _s: pytest.fail("critic must not be called"))
    pipeline = NarrativeUnitPipeline(planner, writer, critic, annotation_llm=None)

    with pytest.raises(np.PlanNotPlausible, match="No plausible, fresh plan") as excinfo:
        await pipeline.run(_brief(), annotate=False)

    assert "distinct non-empty narrator_profile" in str(excinfo.value)
    assert "identical plan that was just rejected" in str(excinfo.value)
    assert len(planner.calls) == pipeline.max_plan_attempts
    assert writer.calls == []
    # Pre-writer aborts stay ValueErrors so existing callers keep catching them.
    assert isinstance(excinfo.value, ValueError)
    assert len(excinfo.value.rejected_plans) == pipeline.max_plan_attempts


@pytest.mark.asyncio
async def test_planner_schema_error_gets_one_preflight_retry_before_story_calls():
    attempts = 0

    def plan_handler(_prompt, _schema):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("invalid evidence_allowance enum")
        return _plan()

    planner = _FakeStructuredLLM(plan_handler)

    def write(prompt, _schema):
        sid = next(value for value in ("story_1", "story_2", "story_3") if value in prompt)
        draft = _draft(int(sid[-1]))
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    critic = _FakeStructuredLLM(
        lambda _p, schema: (
            _approved_final_review() if schema is FinalCompilationReview else _passing_score()
        )
    )
    pipeline = NarrativeUnitPipeline(planner, _FakeStructuredLLM(write), critic, None)

    result = await pipeline.run(_brief(), annotate=False)

    assert attempts == 2
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_critic_forensic_contract_gets_one_retry_then_fails_closed():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())

    def write(prompt, _schema):
        sid = next(value for value in ("story_1", "story_2", "story_3") if value in prompt)
        draft = _draft(int(sid[-1]))
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    hallucinated = _passing_score().model_copy(update={
        "story_issues": [StoryIssue(
            story_id="story_1", severity="major", issue_kind="contradiction",
            problem="invented issue", repair_instruction="change it",
            evidence_quote="This sentence is absent.", viewer_impact="breaks belief",
            issue_id="fake_1",
        )]
    })
    critic = _FakeStructuredLLM(lambda _p, _s: hallucinated)
    pipeline = NarrativeUnitPipeline(planner, _FakeStructuredLLM(write), critic, None)

    result = await pipeline.run(_brief(), annotate=False)

    assert result.critic_contract_valid is False
    assert result.content_locked is False
    assert result.call_counts["critic_score"] == 2
    assert any("FORENSIC CONTRACT RETRY" in prompt for prompt in critic.calls)


@pytest.mark.asyncio
async def test_final_read_only_editor_can_block_an_otherwise_passing_compilation():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())

    def write(prompt, _schema):
        sid = next(value for value in ("story_1", "story_2", "story_3") if value in prompt)
        draft = _draft(int(sid[-1]))
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return FinalCompilationReview(
                approved=False,
                reviewed_story_ids=["story_1", "story_2", "story_3"],
                issues=[],
                summary="insufficient voice separation",
            )
        return _passing_score()

    critic = _FakeStructuredLLM(judge)
    pipeline = NarrativeUnitPipeline(planner, _FakeStructuredLLM(write), critic, None)
    result = await pipeline.run(_brief(), annotate=False)

    assert result.gate_report.passed is True
    assert result.scorecard.total_score == 85
    assert result.final_editor_approved is False
    assert result.content_locked is False
    assert result.release_tier == "content_valid"


@pytest.mark.asyncio
async def test_baseline_selector_cannot_gain_release_from_a_second_score_roll():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next(value for value in initial if value in prompt)
        if "Surgically repair" in prompt:
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ", replace="I checked the latch. ",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="I told myself it was nothing. ", replace="I touched the latch. ",
                )]),
            ])
        draft = initial[sid]
        narration = (
            "I told myself it was nothing. " + draft.narration
            if sid == "story_1" else draft.narration
        )
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates, narration=narration,
        )

    initial_score = _passing_score().model_copy(update={
        "story_issues": [StoryIssue(
            story_id="story_1", severity="major", issue_kind="style",
            problem="stock phrase", repair_instruction="replace it",
            evidence_quote="I told myself it was nothing. ", viewer_impact="synthetic",
            issue_id="stock_1",
        )]
    })

    def judge(prompt, schema):
        if schema is BlindPatchSelection:
            labels = re.findall(r'"label":\s*"(option_\d+)"', prompt)
            return BlindPatchSelection(
                selected_label=labels[0], confidence=0.99,
                preserves_locked_plan=True, resolves_target_issues=False,
                introduced_issues=[], rationale="baseline is safer",
            )
        return initial_score

    critic = _FakeStructuredLLM(judge)
    pipeline = NarrativeUnitPipeline(planner, _FakeStructuredLLM(write), critic, None)
    result = await pipeline.run(_brief(), annotate=False)

    assert result.content_locked is False
    assert result.stories[0].narration.startswith("I told myself")
    assert result.call_counts["critic_score"] == 1
    assert result.call_counts["blind_selector"] == 1


@pytest.mark.asyncio
async def test_invalid_forensic_patch_pair_keeps_baseline_instead_of_crashing_job():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next(value for value in initial if value in prompt)
        if "Surgically repair" in prompt:
            return StoryPatchCandidateSet(candidates=[
                StoryPatchCandidate(candidate_id="candidate_1", edits=[StoryTextEdit(
                    find="unrelated missing text", replace="replacement",
                )]),
                StoryPatchCandidate(candidate_id="candidate_2", edits=[StoryTextEdit(
                    find="another missing text", replace="replacement",
                )]),
            ])
        draft = initial[sid]
        narration = (
            "I told myself it was nothing. " + draft.narration
            if sid == "story_1" else draft.narration
        )
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates, narration=narration,
        )

    issue_score = _passing_score().model_copy(update={
        "story_issues": [StoryIssue(
            story_id="story_1", severity="major", issue_kind="style",
            problem="stock phrase", repair_instruction="replace it",
            evidence_quote="I told myself it was nothing. ", viewer_impact="synthetic",
            issue_id="stock_1",
        )]
    })
    critic = _FakeStructuredLLM(lambda _p, _s: issue_score)
    pipeline = NarrativeUnitPipeline(planner, _FakeStructuredLLM(write), critic, None)

    result = await pipeline.run(_brief(), annotate=False)

    assert result.content_locked is False
    assert result.stories[0].narration.startswith("I told myself")
    assert result.call_counts["critic_score"] == 1
    # The invalid pair receives exactly one contract-only retry before failing closed.
    assert result.call_counts["repair_writer"] == 2


@pytest.mark.asyncio
async def test_repair_schema_error_keeps_baseline_instead_of_crashing_job():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next(value for value in initial if value in prompt)
        if "Surgically repair" in prompt:
            raise ValueError("malformed patch JSON")
        draft = initial[sid]
        narration = (
            "I told myself it was nothing. " + draft.narration
            if sid == "story_1" else draft.narration
        )
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates, narration=narration,
        )

    issue_score = _passing_score().model_copy(update={
        "story_issues": [StoryIssue(
            story_id="story_1", severity="major", issue_kind="style",
            problem="stock phrase", repair_instruction="replace it",
            evidence_quote="I told myself it was nothing. ", viewer_impact="synthetic",
            issue_id="stock_1",
        )]
    })
    pipeline = NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write),
        _FakeStructuredLLM(lambda _p, _s: issue_score), None,
    )
    result = await pipeline.run(_brief(), annotate=False)
    assert result.content_locked is False
    assert result.stories[0].narration.startswith("I told myself")


@pytest.mark.asyncio
async def test_final_editor_schema_error_fails_closed_without_crashing_job():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())

    def write(prompt, _schema):
        sid = next(value for value in ("story_1", "story_2", "story_3") if value in prompt)
        draft = _draft(int(sid[-1]))
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            raise ValueError("malformed final review JSON")
        return _passing_score()

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)
    assert result.content_locked is False
    assert result.final_editor_approved is False


@pytest.mark.asyncio
async def test_final_editor_contract_gets_one_retry_and_can_recover():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())

    def write(prompt, _schema):
        sid = next(value for value in ("story_1", "story_2", "story_3") if value in prompt)
        draft = _draft(int(sid[-1]))
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    final_attempts = 0

    def judge(_prompt, schema):
        nonlocal final_attempts
        if schema is FinalCompilationReview:
            final_attempts += 1
            if final_attempts == 1:
                raise ValueError("malformed final review JSON")
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), _FakeStructuredLLM(judge), None,
    ).run(_brief(), annotate=False)

    assert final_attempts == 2
    assert result.call_counts["final_editor"] == 2
    assert result.final_editor_approved is True
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_annotation_schema_error_preserves_lock_but_blocks_production_ready():
    planner = _FakeStructuredLLM(lambda _p, _s: _plan())

    def write(prompt, _schema):
        sid = next(value for value in ("story_1", "story_2", "story_3") if value in prompt)
        draft = _draft(int(sid[-1]))
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    critic = _FakeStructuredLLM(
        lambda _p, schema: (
            _approved_final_review() if schema is FinalCompilationReview else _passing_score()
        )
    )
    annotation = _FakeStructuredLLM(
        lambda _p, _s: (_ for _ in ()).throw(ValueError("bad annotation JSON"))
    )
    result = await NarrativeUnitPipeline(
        planner, _FakeStructuredLLM(write), critic, annotation,
    ).run(_brief(), annotate=True)
    assert result.content_locked is True
    assert result.production_ready is False
    assert result.release_tier == "editorially_ready"


def test_result_invariant_rechecks_score_and_locked_voiceover_hash():
    stories = [_draft(i) for i in range(1, 4)]
    weak = _passing_score().model_copy(update={"distinct_authentic_voices": 8})
    with pytest.raises(ValueError, match="score|release contract"):
        NarrativePipelineResult(
            plan=_plan(), stories=stories,
            gate_report=gate_compilation(_plan(), stories), scorecard=weak,
            story_compliance_reviews=_compliance_reviews(stories),
            content_locked=True, final_editor_approved=True,
            locked_voiceover_sha256=locked_voiceover_sha256(stories),
            release_tier="editorially_ready", **_release_evidence(),
        )

    with pytest.raises(ValueError, match="SHA256"):
        NarrativePipelineResult(
            plan=_plan(), stories=stories,
            gate_report=gate_compilation(_plan(), stories), scorecard=_passing_score(),
            story_compliance_reviews=_compliance_reviews(stories),
            content_locked=True, final_editor_approved=True,
            locked_voiceover_sha256="0" * 64,
            release_tier="editorially_ready", **_release_evidence(),
        )
