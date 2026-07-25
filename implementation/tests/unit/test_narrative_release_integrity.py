"""Release-integrity contracts derived from a real false-positive artifact.

On 2026-07-17 the pipeline approved
``output/products/true_dread_files_us/20260717_0733_3_true_encounters_while_delivering_newspapers_befo``
at 93/100 ``production_ready``. An independent manual audit scored it ~58-62 and found
an impossible fence-gap traversal, a this-morning/changed-route timeline contradiction,
three stories sharing one semantic beat sheet, a newspapers/packages topic mismatch, a
sixteen-year-old abduction attempt with no police response, a forbidden self-referential
ending, and a plan whose spoken age was never actually spoken.

Every test here binds to that exact artifact (``tests/fixtures/narrative/true_dread_20260717.json``,
verbatim plan text and narration) or to a minimized deterministic equivalent. The point is
not that a judge *should* have caught these — it is that the release path must catch them
without asking a judge nicely.
"""

from __future__ import annotations

import json
import pathlib

import pytest

import omnicast.agents.narrative_pipeline as np
from omnicast.agents.narrative_pipeline import (
    CompilationPlan,
    FinalCompilationReview,
    NamedChannelStrategy,
    NarrativeRunExhausted,
    NarrativeStoryPlan,
    NarrativeUnitPipeline,
    PlanAuditUnavailable,
    PlanIssue,
    PlanNotPlausible,
    PlanPlausibilityReview,
    ReleaseChallenge,
    ChallengeVerdict,
    StoryDraft,
    StoryOutput,
    evaluate_plan_audit,
    gate_compilation,
    plan_audit_blockers,
    plan_concept_fingerprint,
    promote_miscalibrated_issues,
    validate_plan_audit_issues,
    validate_plan_preflight,
)
from omnicast.config.narrative_quality import resolve_script_profile

from tests.unit.test_narrative_unit_pipeline import (
    _FakeStructuredLLM,
    _approved_final_review,
    _brief,
    _draft,
    _passing_score,
    _plan,
    _variant_plan,
)


_FIXTURE = json.loads(
    (
        pathlib.Path(__file__).resolve().parents[1]
        / "fixtures" / "narrative" / "true_dread_20260717.json"
    ).read_text(encoding="utf-8")
)


def _horror_strategy() -> NamedChannelStrategy:
    """The real channel contract, not a permissive system default."""
    return NamedChannelStrategy.from_quality_profile(
        resolve_script_profile("true_horror_strict_v1")
    )


def _artifact_plan(**overrides) -> CompilationPlan:
    """The 2026-07-17 plan, verbatim, plus the typed labels its schema lacked."""
    stories = []
    for item in _FIXTURE["stories"]:
        payload = dict(item)
        payload.update(_FIXTURE["honest_labels"][item["story_id"]])
        payload.update(overrides.get(item["story_id"], {}))
        stories.append(NarrativeStoryPlan.model_validate(payload))
    return CompilationPlan(
        topic=_FIXTURE["topic"],
        cold_open=_FIXTURE["cold_open"],
        target_word_count=_FIXTURE["target_word_count"],
        stories=stories,
    )


def _artifact_story(story_id: str) -> StoryDraft:
    source = next(item for item in _FIXTURE["stories"] if item["story_id"] == story_id)
    return StoryDraft(
        story_id=story_id,
        title=source["title"],
        hook_candidates=[source["title"]],
        narration=_FIXTURE["narrations"][story_id],
    )


def _artifact_stories() -> list[StoryDraft]:
    return [_artifact_story(f"story_{index}") for index in range(1, 4)]


def _codes(report) -> set[str]:
    return {failure.code for failure in report.failures}


def _identified(fake, provider: str, model: str):
    """Give a fake client the attributes LLMClient exposes for identity.

    Provider independence is decided on the RESOLVED (provider, model) pair, never
    on which variable a client was assigned to — the CapabilityBus can route two
    differently-named preferences onto one provider, which is exactly what happened
    on 2026-07-17 (every recorded cost was a DeepSeek model despite an "anthropic"
    client). These tests therefore state identity explicitly.
    """
    fake._provider = provider
    fake._model = model
    return fake


def _clean_stories() -> dict:
    return {f"story_{i}": _draft(i) for i in range(1, 4)}


def _story_writer(initial: dict):
    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )
    return write


# ---------------------------------------------------------------------------
# 1. Plan-time: the shared semantic beat sheet is rejected before any prose is paid for.


def test_artifact_shared_beat_sheet_is_rejected_before_story_generation():
    """Stories 1 and 3 are 'silent watcher blocks path -> flee to a lit occupied
    place'. Literal string diversity passed; typed mechanism diversity must not."""
    errors = validate_plan_preflight(_artifact_plan(), 3, _horror_strategy())

    threat = [item for item in errors if "threat_mechanism" in item]
    escape = [item for item in errors if "escape_mechanism" in item]
    assert threat, f"duplicate blocks_path threat not rejected: {errors}"
    assert escape, f"duplicate flee_to_occupied_place escape not rejected: {errors}"
    assert all("story_1" in item and "story_3" in item for item in threat + escape)


def test_literal_field_diversity_alone_no_longer_passes_the_artifact_plan():
    """The old gate only compared normalized prose fields, which all differed."""
    plan = _artifact_plan()
    for field in ("narrator_profile", "threat", "ending_shape", "escape_action"):
        values = [np._normal(getattr(item, field)) for item in plan.stories]
        assert len(set(values)) == len(values), f"{field} literally differs in the artifact"
    assert validate_plan_preflight(plan, 3, _horror_strategy())


def test_distinct_mechanisms_across_axes_pass_preflight():
    """The gate must reject repetition, not creativity."""
    plan = _artifact_plan(overrides={})
    fixed = _artifact_plan(**{
        "story_3": {
            "threat_mechanism": "pursues",
            "escape_mechanism": "vehicle_escape",
            "threat_identity": "vehicle_mediated",
            "topic_promise": "drives a Main Street newspaper bundle route before dawn",
        },
        "story_1": {"safety_obligation": "authorities_contacted"},
        "story_2": {
            "threat_identity": "known_regular",
            "topic_promise": "delivers newspapers on foot through apartment breezeways",
        },
    })
    assert plan.stories[0].threat_mechanism == "blocks_path"
    assert validate_plan_preflight(fixed, 3, _horror_strategy()) == []


# ---------------------------------------------------------------------------
# 2. Plan-time: topic alignment. The compilation promised newspapers; story 2 planned packages.


def test_artifact_newspapers_versus_packages_mismatch_is_rejected_at_plan_time():
    errors = validate_plan_preflight(_artifact_plan(), 3, _horror_strategy())
    mismatch = [item for item in errors if "topic_promise" in item and "story_2" in item]
    assert mismatch, f"packages-vs-newspapers topic drift not rejected: {errors}"
    assert "newspaper" in mismatch[0]


def test_topic_alignment_accepts_a_legitimate_synonym_of_the_subject():
    """Story 3 delivers 'newspaper bundles' — a stem match, not a literal one."""
    plan = _artifact_plan(**{
        "story_2": {"topic_promise": "delivers newspaper bundles through breezeways"},
    })
    errors = validate_plan_preflight(plan, 3, _horror_strategy())
    assert not [item for item in errors if "topic_promise" in item and "story_2" in item]


def test_topic_alignment_gate_is_channel_scoped_not_global():
    """A channel without the gate must not inherit horror topic policy."""
    generic = NamedChannelStrategy(
        strategy_id="generic_test", writer_rules="w", critic_rules="c",
        annotation_rules="a",
    )
    assert generic.topic_alignment_gate is False
    errors = validate_plan_preflight(_artifact_plan(), 3, generic)
    assert not [item for item in errors if "topic_promise" in item]


# ---------------------------------------------------------------------------
# 3. Plan-time: a sixteen-year-old is nearly abducted and nobody calls anyone.


def test_artifact_minor_abduction_attempt_plans_no_safety_response_at_all():
    """The artifact's story 1 plan commits to no safety response whatsoever: its
    ending_shape promises only an identity inquiry ("learns next day no one
    matching him lives nearby"), and the neighbour who pulls her inside belongs to
    escape_action, not the aftermath. `not_applicable` is the honest label for
    that plan, and it is not a plausible aftermath for a near-abducted child."""
    assert _FIXTURE["honest_labels"]["story_1"]["safety_obligation"] == "not_applicable"
    errors = validate_plan_preflight(_artifact_plan(), 3, _horror_strategy())
    safety = [item for item in errors if "safety_obligation" in item and "story_1" in item]
    assert safety, f"minor + human threat + no planned response not rejected: {errors}"


def test_minor_safety_accepts_authorities_a_trusted_adult_or_a_concrete_reason():
    """Three legal paths, not one. Requiring police for every minor manufactures
    the formulaic ending the channel promise exists to avoid; the point is that a
    child who survives a human threat tells SOMEONE, or the plan says why not."""
    for override in (
        {"safety_obligation": "authorities_contacted"},
        {"safety_obligation": "trusted_adult_or_witness"},
        {
            "safety_obligation": "concrete_reason_omitted",
            "safety_omission_reason": (
                "she is an undocumented minor whose family cannot call police"
            ),
        },
    ):
        plan = _artifact_plan(**{"story_1": override})
        assert not [
            item for item in validate_plan_preflight(plan, 3, _horror_strategy())
            if "safety_obligation" in item and "story_1" in item
        ], f"{override['safety_obligation']} must be a legal minor-safety path"


def test_a_bare_omission_reason_does_not_buy_silence():
    plan = _artifact_plan(**{"story_1": {
        "safety_obligation": "concrete_reason_omitted", "safety_omission_reason": "no",
    }})
    assert [
        item for item in validate_plan_preflight(plan, 3, _horror_strategy())
        if "safety_obligation" in item and "story_1" in item
    ]


def test_a_declared_trusted_adult_response_must_actually_reach_the_page():
    """A plan path is a promise, not a loophole: declaring the softer response and
    then writing no response at all would be strictly easier than the police
    ending it replaces."""
    plan = _artifact_plan(**{"story_1": {"safety_obligation": "trusted_adult_or_witness"}})
    stories = _artifact_stories()
    silent = stories[0].model_copy(update={
        "narration": stories[0].narration.replace(
            "The next day my mom asked around the subdivision, and Mrs. Alden asked too,",
            "The next day nobody asked around the subdivision, and nobody else asked either,",
            1,
        ).replace("Mrs. Alden leaves her porch light burning till the sun's all the way up.",
                  "The porch light burns till the sun's all the way up.", 1),
    })
    # The aftermath is what discharges the obligation. "Forty minutes before the
    # sun, my mom always said, is the darkest dark there is" is still mid-story and
    # must not count: that is a remembered saying, not somebody being told.
    assert "mom" in silent.narration.lower()
    assert "mom" not in np._aftermath_region(silent.narration).lower()

    report = gate_compilation(plan, [silent, stories[1], stories[2]], _horror_strategy())
    failure = next((f for f in report.failures if f.code == "safety_response"), None)
    assert failure is not None, _codes(report)
    assert failure.story_ids == ["story_1"]


def test_a_delivered_trusted_adult_response_clears_the_gate():
    """The artifact's real story 1 does tell a parent, so the gate must pass it —
    what the plan failed to promise, the page happened to deliver."""
    plan = _artifact_plan(**{"story_1": {"safety_obligation": "trusted_adult_or_witness"}})
    assert "my mom asked around" in _FIXTURE["narrations"]["story_1"]

    report = gate_compilation(plan, _artifact_stories(), _horror_strategy())
    assert not [
        f for f in report.failures
        if f.code == "safety_response" and "story_1" in f.story_ids
    ]


def test_any_passing_adult_is_not_a_responsible_adult_response():
    """'A man let me in' is a bystander in the escape, not someone responsible who
    was told. Matching any adult noun would make the gate decorative."""
    plan = _artifact_plan(**{"story_1": {"safety_obligation": "trusted_adult_or_witness"}})
    stories = _artifact_stories()
    bystander = stories[0].model_copy(update={
        "narration": stories[0].narration.replace(
            "The next day my mom asked around the subdivision, and Mrs. Alden asked too,",
            "The next day some adult man asked around the subdivision, and a person asked too,",
            1,
        ).replace("Mrs. Alden leaves her porch light burning till the sun's all the way up.",
                  "The porch light burns till the sun's all the way up.", 1),
    })
    report = gate_compilation(plan, [bystander, stories[1], stories[2]], _horror_strategy())
    assert "safety_response" in _codes(report)


def test_authorities_contacted_still_requires_an_authority_on_the_page():
    plan = _artifact_plan(**{"story_1": {"safety_obligation": "authorities_contacted"}})
    report = gate_compilation(plan, _artifact_stories(), _horror_strategy())
    failure = next((f for f in report.failures if f.code == "safety_response"), None)
    assert failure is not None, "story 1 never mentions police"
    assert failure.story_ids == ["story_1"]

    stories = _artifact_stories()
    reported = stories[0].model_copy(update={
        "narration": stories[0].narration + "\n\nMy mom called the police that morning.",
    })
    cleared = gate_compilation(plan, [reported, stories[1], stories[2]], _horror_strategy())
    assert not [
        f for f in cleared.failures
        if f.code == "safety_response" and "story_1" in f.story_ids
    ]


def test_safety_response_gate_is_channel_scoped():
    generic = NamedChannelStrategy(
        strategy_id="generic_test", writer_rules="w", critic_rules="c",
        annotation_rules="a",
    )
    assert generic.safety_response_gate is False
    assert not [
        item for item in validate_plan_preflight(_artifact_plan(), 3, generic)
        if "safety_obligation" in item
    ]


def test_adult_narrators_do_not_inherit_the_minor_safety_obligation():
    assert not [
        item for item in validate_plan_preflight(_artifact_plan(), 3, _horror_strategy())
        if "safety_obligation" in item and ("story_2" in item or "story_3" in item)
    ]


# ---------------------------------------------------------------------------
# 4. Story-time: material plan-to-story fact fidelity on the real narration.


def test_artifact_story_1_never_speaks_the_sixteen_the_plan_locked():
    """Compliance called ordinary_setup 'complete'; the age is simply not on the page."""
    narration = _FIXTURE["narrations"]["story_1"].lower()
    assert "sixteen" not in narration and " 16" not in narration

    report = gate_compilation(_artifact_plan(), _artifact_stories(), _horror_strategy())

    assert "plan_fact_age" in _codes(report)
    failure = next(f for f in report.failures if f.code == "plan_fact_age")
    assert failure.story_ids == ["story_1"]


def test_speaking_the_locked_age_clears_the_material_fidelity_gate():
    stories = _artifact_stories()
    stories[0] = stories[0].model_copy(update={
        "narration": "I was sixteen that October.\n\n" + stories[0].narration,
    })
    report = gate_compilation(_artifact_plan(), stories, _horror_strategy())
    assert "plan_fact_age" not in _codes(report)


def test_artifact_narration_that_never_says_the_promised_subject_blocks_release():
    """Story 2 delivers packages. Story 3 planned a newspaper bundle route and then
    wrote only 'bundle' — the title's promise is never paid on the page. Story 1
    says 'papers' and passes on the stem, which is the behaviour we want: the gate
    demands the subject, not a keyword."""
    report = gate_compilation(_artifact_plan(), _artifact_stories(), _horror_strategy())

    flagged = {
        sid for f in report.failures if f.code == "plan_fact_topic_promise"
        for sid in f.story_ids
    }
    assert flagged == {"story_2", "story_3"}, _codes(report)
    assert "paper" in _FIXTURE["narrations"]["story_1"].lower()


def test_saying_the_promised_subject_clears_the_topic_fidelity_gate():
    stories = _artifact_stories()
    stories[2] = stories[2].model_copy(update={
        "narration": stories[2].narration.replace(
            "Load the car at the depot", "Load the newspaper bundles at the depot", 1
        ),
    })
    report = gate_compilation(_artifact_plan(), stories, _horror_strategy())
    assert not [
        f for f in report.failures
        if f.code == "plan_fact_topic_promise" and "story_3" in f.story_ids
    ]


# ---------------------------------------------------------------------------
# 5. Story-time: the forbidden self-referential ending the writer rules already banned.


def test_artifact_story_2_forbidden_never_went_back_ending_blocks_release():
    assert _FIXTURE["narrations"]["story_2"].rstrip().endswith(
        "I never went back to find out who he was."
    )
    report = gate_compilation(_artifact_plan(), _artifact_stories(), _horror_strategy())

    assert "forbidden_ending" in _codes(report)
    failure = next(f for f in report.failures if f.code == "forbidden_ending")
    assert failure.story_ids == ["story_2"]
    assert report.passed is False


def test_forbidden_ending_only_reads_the_ending_not_the_whole_story():
    """The same clause mid-story is a beat, not a release defect."""
    story = _artifact_story("story_1")
    mid = story.model_copy(update={
        "narration": (
            "I never went back to find out who he was, not that whole first week.\n\n"
            + story.narration
        ),
    })
    plan = _artifact_plan()
    report = gate_compilation(plan, [mid, _artifact_story("story_2"), _artifact_story("story_3")],
                              _horror_strategy())
    assert not [
        f for f in report.failures if f.code == "forbidden_ending" and "story_1" in f.story_ids
    ]


def test_forbidden_ending_gate_is_channel_scoped():
    generic = NamedChannelStrategy(
        strategy_id="generic_test", writer_rules="w", critic_rules="c",
        annotation_rules="a",
    )
    assert generic.forbidden_ending_gate is False
    report = gate_compilation(_artifact_plan(), _artifact_stories(), generic)
    assert "forbidden_ending" not in _codes(report)


# ---------------------------------------------------------------------------
# 6. Critic calibration: an impossible traversal cannot be filed as minor/style.


def test_artifact_impossible_fence_gap_minor_is_promoted_to_major():
    """The live critic wrote 'physically unclear ... fences right up against his
    shoulders' and filed it severity=minor, issue_kind=style. That is the exact
    false-positive: a major causal/physics contradiction laundered as taste."""
    raw = _FIXTURE["scored_story_issues"][0]
    assert raw["severity"] == "minor" and raw["issue_kind"] == "style"

    score = _passing_score().model_copy(update={
        "story_issues": [np.StoryIssue.model_validate(raw)],
    })
    promoted = promote_miscalibrated_issues(score, _horror_strategy())

    issue = promoted.story_issues[0]
    assert issue.severity == "major"
    assert issue.issue_kind == "contradiction"
    assert issue.evidence_quote == raw["evidence_quote"]
    assert not np.content_can_lock(
        promoted, gate_compilation(_artifact_plan(), _artifact_stories(), _horror_strategy()),
        _horror_strategy(),
    )


def test_promotion_leaves_genuine_taste_notes_alone():
    """Story 3's 'undercuts urgency' pacing note is a real minor and must stay one."""
    raw = _FIXTURE["scored_story_issues"][2]
    score = _passing_score().model_copy(update={
        "story_issues": [np.StoryIssue.model_validate(raw)],
    })
    promoted = promote_miscalibrated_issues(score, _horror_strategy())
    assert promoted.story_issues[0].severity == "minor"


def test_ungrounded_impossibility_claim_is_not_promoted_into_an_unrepairable_blocker():
    """Promotion needs the critic's own exact quote; a quoteless minor stays minor."""
    score = _passing_score().model_copy(update={"story_issues": [np.StoryIssue(
        story_id="story_1", severity="minor", issue_kind="style",
        problem="the escape is physically impossible", repair_instruction="clarify",
        evidence_quote="", issue_id="x1",
    )]})
    assert promote_miscalibrated_issues(score, _horror_strategy()).story_issues[0].severity == "minor"


# ---------------------------------------------------------------------------
# 7. Plan audit is fail-closed and tri-state.


def test_a_single_grounded_major_blocks_the_plan():
    """Previously a lone major was discarded and only >=2 majors on one story blocked."""
    review = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="geography", severity="major",
        problem="the exit is behind the threat", plan_fix="move the exit",
    )])
    blockers = plan_audit_blockers(review)
    assert len(blockers) == 1
    assert "exit is behind the threat" in blockers[0]

    result = evaluate_plan_audit(review, _artifact_plan())
    assert result.status == "blocked"
    assert result.issues[0].severity == "major"


def test_minor_plan_issues_are_preserved_but_never_block():
    review = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_2", category="trope", severity="minor",
        problem="familiar premise", plan_fix="vary it",
    )])
    result = evaluate_plan_audit(review, _artifact_plan())
    assert result.status == "valid"
    assert result.blockers == []
    assert result.issues, "minor evidence must survive on the audit trail"


@pytest.mark.asyncio
async def test_plan_audit_infrastructure_failure_aborts_before_the_writer():
    """An auditor that never answered is not a clean auditor."""
    writer_calls: list[str] = []

    def write(prompt, _schema):
        writer_calls.append(prompt)
        return StoryOutput(title="t", hook_candidates=["h"], narration="n")

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            raise ValueError("provider returned malformed JSON")
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(PlanAuditUnavailable) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert writer_calls == [], "aborted before paying for any draft"
    assert excinfo.value.audit.status == "infra_failed"
    assert excinfo.value.audit.provider_errors


def _dead_primary_pipeline(*, critic_fallback=None, writer_calls=None):
    """The exact 2026-07-17 13:34 shape: every DeepSeek primary audit 402s, Claude
    escalation answers every time, and the plan verdict comes back clean."""
    primary_calls = {"n": 0}

    def primary(_prompt, schema):
        # A 402 does not politely decline one schema and serve the rest. The whole
        # account is gone, which is the entire reason a shared account is not a
        # fallback for itself.
        if schema is PlanPlausibilityReview:
            primary_calls["n"] += 1
        raise ValueError("402 insufficient balance")

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    initial = _clean_stories()

    def write(prompt, _schema):
        if writer_calls is not None:
            writer_calls.append(prompt)
        return _story_writer(initial)(prompt, _schema)

    critic = _identified(
        _FakeStructuredLLM(primary, auto_plan_audit=False), "deepseek", "deepseek-v4-pro"
    )
    # Compliance is the same DeepSeek account on a different model name. That is
    # one balance and one outage, not a fallback — so it is dead too.
    compliance = _identified(
        _FakeStructuredLLM(
            judge if critic_fallback is None else primary, auto_plan_audit=False
        ),
        "deepseek", "deepseek-v4-flash",
    )
    escalation = _identified(
        _FakeStructuredLLM(lambda _p, _s: PlanPlausibilityReview(), auto_plan_audit=False),
        "anthropic", "claude-opus-5",
    )
    pipe = NarrativeUnitPipeline(
        _identified(_FakeStructuredLLM(lambda _p, _s: _plan()), "anthropic", "claude-opus-5"),
        _identified(_FakeStructuredLLM(write), "anthropic", "claude-opus-5"),
        critic, None,
        compliance_llm=compliance,
        plan_audit_escalation_llm=escalation,
        critic_fallback_llm=critic_fallback,
        release_challenger_llm=_identified(
            _FakeStructuredLLM(
                lambda _p, _s: ReleaseChallenge(
                    verdicts=[ChallengeVerdict(axis=axis, verdict="pass")
                              for axis, _rule in np._CHALLENGE_AXES],
                    summary="clean",
                ),
                auto_plan_audit=False,
            ),
            "anthropic", "claude-opus-5",
        ),
    )
    return pipe, primary_calls, escalation


@pytest.mark.asyncio
async def test_plan_audit_escalation_rescues_the_verdict_but_not_the_provider_health():
    """The 13:34 masking bug. All ten DeepSeek primary audits failed; Claude
    escalation answered every one; the audit reported a clean verdict. Had a plan
    passed, the run would have bought three Opus drafts and only then discovered
    that the scorer, compliance auditor and final editor were all unreachable —
    the 08:36 failure again, paid for twice. Escalation rescues the VERDICT; it
    must not launder the HEALTH."""
    writer_calls: list[str] = []
    pipe, primary_calls, escalation = _dead_primary_pipeline(writer_calls=writer_calls)

    with pytest.raises(np.QualityPathUnhealthy) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert primary_calls["n"] == 2, "primary retried before escalating"
    assert len(escalation.calls) == 1
    # The verdict itself was clean and escalated — that is not the point.
    audit = excinfo.value.audit
    assert audit.status == "valid"
    assert audit.escalated is True
    assert audit.verdict_source == "escalation"
    # ...and the health signal survived it.
    assert audit.primary_healthy is False
    assert any("402" in item for item in audit.primary_provider_errors)
    assert writer_calls == [], "no draft is bought when its judges are already dead"
    message = str(excinfo.value)
    assert "critic_score" in message and "final_editor" in message
    # Compliance is a different MODEL on the same dead account, so it is stranded too.
    assert "story_compliance" in message


@pytest.mark.asyncio
async def test_a_genuinely_independent_critic_fallback_lets_the_run_proceed():
    """The control: the gate must reject a shared dead account, not resilience.
    With a real fallback on another provider for every mandatory post-writer judge,
    drafting is safe and the run continues."""
    writer_calls: list[str] = []

    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    fallback = _identified(
        _FakeStructuredLLM(judge, auto_plan_audit=False), "anthropic", "claude-opus-5"
    )
    pipe, _primary_calls, _escalation = _dead_primary_pipeline(
        critic_fallback=fallback, writer_calls=writer_calls
    )
    # Compliance also needs a live path; its escalation is the same dead account by
    # default, so give it the independent one too.
    pipe.compliance_escalation_llm = fallback

    result = await pipe.run(_brief(), annotate=False)

    assert result.plan_audit.primary_healthy is False
    assert len(writer_calls) == 3, "drafting proceeds when the judges have a live path"
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_same_object_escalation_is_not_a_different_provider():
    """critic_llm and its 'escalation' being one client is not provider diversity."""
    critic = _FakeStructuredLLM(
        lambda _p, _s: (_ for _ in ()).throw(ValueError("502")), auto_plan_audit=False
    )
    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(lambda _p, _s: None), critic, None,
        plan_audit_escalation_llm=critic,
    )
    with pytest.raises(PlanAuditUnavailable):
        await pipe.run(_brief(), annotate=False)
    assert len(critic.calls) == 2, "no third call to the same client dressed as escalation"


@pytest.mark.asyncio
async def test_unresolved_second_critical_aborts_instead_of_writing_stories():
    """The final planner attempt used to proceed with a known-broken premise."""
    writer_calls: list[str] = []

    def write(prompt, _schema):
        writer_calls.append(prompt)
        return StoryOutput(title="t", hook_candidates=["h"], narration="n")

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview(issues=[PlanIssue(
                story_id="story_1", category="physical", severity="critical",
                problem="the door cannot lock from both sides", plan_fix="use one lock",
                evidence_quote="different human threat 1",
            )])
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert writer_calls == []
    assert excinfo.value.audit.status == "blocked"
    assert any("cannot lock from both sides" in item for item in excinfo.value.audit.blockers)
    assert len(excinfo.value.rejected_plans) == pipe.max_plan_attempts


# ---------------------------------------------------------------------------
# 8. 'Fresh concept' is enforced, not merely requested in a prompt.


def test_identical_plans_share_a_concept_fingerprint():
    assert plan_concept_fingerprint(_plan()) == plan_concept_fingerprint(_plan())


def test_fingerprint_ignores_cosmetic_rewording_but_tracks_mechanisms():
    reworded = _plan()
    reworded = reworded.model_copy(update={"stories": [
        reworded.stories[0].model_copy(update={"title": "A Totally New Title"}),
        *reworded.stories[1:],
    ]})
    assert plan_concept_fingerprint(reworded) == plan_concept_fingerprint(_plan())

    remechanized = _plan()
    remechanized = remechanized.model_copy(update={"stories": [
        remechanized.stories[0].model_copy(update={"escape_mechanism": "vehicle_escape"}),
        *remechanized.stories[1:],
    ]})
    assert plan_concept_fingerprint(remechanized) != plan_concept_fingerprint(_plan())


@pytest.mark.asyncio
async def test_a_repeated_fresh_plan_is_rejected_before_paying_for_stories():
    """Attempt 2 asked for a 'fresh concept' in the prompt and accepted a carbon copy."""
    planner_prompts: list[str] = []
    writer_prompts: list[str] = []

    def plan_handler(prompt, _schema):
        planner_prompts.append(prompt)
        # A planner that ignores the brief and returns the identical concept twice.
        return _plan()

    def write(prompt, _schema):
        writer_prompts.append(prompt)
        return StoryOutput(title="t", hook_candidates=["h"], narration="n")

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(PlanNotPlausible):
        await pipe.run(
            _brief(), annotate=False,
            forbidden_plan_fingerprints={plan_concept_fingerprint(_plan())},
        )

    assert writer_prompts == [], "a stale concept never reaches the writer"
    assert len(planner_prompts) == pipe.max_plan_attempts
    assert "already been generated" in planner_prompts[1]


@pytest.mark.asyncio
async def test_outer_retry_forbids_the_failed_attempts_concept():
    seen: list[str] = []

    def plan_handler(prompt, _schema):
        seen.append(prompt)
        return _plan()

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        return _passing_score()

    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next((s for s in initial if s in prompt), None)
        if sid is None:
            return StoryOutput(title="t", hook_candidates=["h"], narration="n")
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    # Attempt 1 fails its content gates (no final review approval configured here),
    # so attempt 2 must be told the attempt-1 concept is spent.
    result = await pipe.run_with_retry(_brief(), annotate=False, max_attempts=2)
    assert result.attempts_executed == 2
    assert any("already been generated" in prompt for prompt in seen[1:])


# ---------------------------------------------------------------------------
# 9. All-attempt accounting: attempt 2 must never look like attempt 1 was free.


@pytest.mark.asyncio
async def test_retry_accounting_aggregates_every_attempt():
    """The artifact reported attempt=2 with planner=1 — attempt 1 billed to nobody."""
    assert _FIXTURE["reported_attempt"] == 2
    assert _FIXTURE["reported_call_counts"]["planner"] == 1

    state = {"attempt": 0}

    def plan_handler(_prompt, _schema):
        state["attempt"] += 1
        # Two genuinely distinct concepts, so attempt 2 is a real replan the
        # freshness gate accepts rather than a reshuffle it rejects.
        return _variant_plan(state["attempt"] - 1)

    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            # Attempt 1 is rejected by the final editor with no anchored blocker,
            # so no repair wave can rescue it and it genuinely reaches needs_edit.
            return (
                _approved_final_review() if state["attempt"] > 1
                else FinalCompilationReview(
                    approved=False, reviewed_story_ids=["story_1", "story_2", "story_3"],
                    issues=[], summary="not yet",
                )
            )
        return _passing_score()

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    ).run_with_retry(_brief(), annotate=False, max_attempts=2)

    assert result.attempt == 2
    assert result.attempts_executed == 2
    assert len(result.attempt_summaries) == 2
    assert result.attempt_summaries[0].outcome == "needs_edit"
    assert result.attempt_summaries[0].call_counts["planner"] == 1
    # The winning attempt's own counts stay per-run; the aggregate carries both.
    assert result.call_counts["planner"] == 1
    assert result.aggregate_call_counts["planner"] == 2
    assert result.aggregate_call_counts["story_writer"] == 6
    assert result.aggregate_latency_s >= 0.0
    assert result.attempt_summaries[0].plan_fingerprint
    assert (
        result.attempt_summaries[0].plan_fingerprint
        != result.attempt_summaries[1].plan_fingerprint
    )


@pytest.mark.asyncio
async def test_a_run_where_every_attempt_aborts_still_reports_what_it_spent():
    """The defect this closes: run_with_retry carried all-attempt accounting only
    on a returned result, so a run where nothing survived raised the raw provider
    error and the entire bill vanished — the exact invisible-spend problem the
    accounting contract exists to prevent, in the case that spends most and
    delivers least."""
    def plan_handler(_prompt, _schema):
        return _plan()

    writer_calls: list[str] = []

    def write(prompt, _schema):
        writer_calls.append(prompt)
        return StoryOutput(title="t", hook_candidates=["h"], narration="n")

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            raise ValueError("402 insufficient balance")
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(NarrativeRunExhausted) as excinfo:
        await pipe.run_with_retry(_brief(), annotate=False, max_attempts=2)

    evidence = excinfo.value.evidence
    assert writer_calls == []
    assert evidence.attempts_executed == 2
    assert len(evidence.attempt_summaries) == 2
    assert all(
        item.outcome == "plan_audit_unavailable" for item in evidence.attempt_summaries
    )
    # One planner call per attempt. The auditor is retried twice on attempt 1 and
    # NOT retried on attempt 2: provider health outlives an attempt, so the dead
    # account is skipped rather than re-discovered at the price of another bounded
    # round. Two primary calls for the whole run, not two per attempt.
    assert evidence.aggregate_call_counts["planner"] == 2
    assert evidence.aggregate_call_counts["plan_audit"] == 2
    assert evidence.attempt_summaries[0].call_counts["plan_audit"] == 2
    assert evidence.attempt_summaries[1].call_counts["plan_audit"] == 0
    assert evidence.aggregate_latency_s >= 0.0
    assert "402 insufficient balance" in evidence.attempt_summaries[0].reason
    # The original failure is preserved for diagnosis, not swallowed by the wrapper.
    assert isinstance(excinfo.value.__cause__, PlanAuditUnavailable)
    # Callers that caught the old raw ValueError still catch this.
    assert isinstance(excinfo.value, ValueError)


@pytest.mark.asyncio
async def test_exhausted_run_evidence_is_serializable_for_the_failure_audit():
    """_step_script persists this without a result to dump, so it must survive a
    JSON round-trip and must not invent a score or a script."""
    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview(issues=[PlanIssue(
                story_id="story_1", category="physical", severity="critical",
                problem="the door cannot lock from both sides", plan_fix="use one lock",
                evidence_quote="different human threat 1",
            )])
        return _passing_score()

    state = {"n": 0}

    def plan_handler(_prompt, _schema):
        state["n"] += 1
        return _variant_plan(state["n"] - 1)

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler),
        _FakeStructuredLLM(lambda _p, _s: pytest.fail("writer must not be called")),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(NarrativeRunExhausted) as excinfo:
        await pipe.run_with_retry(_brief(), annotate=False, max_attempts=2)

    payload = json.loads(excinfo.value.evidence.model_dump_json())
    assert payload["attempts_executed"] == 2
    assert payload["aggregate_call_counts"]["planner"] == 2 * pipe.max_plan_attempts
    assert set(payload) >= {
        "attempts_executed", "attempt_summaries", "aggregate_call_counts",
        "aggregate_cost_usd", "aggregate_latency_s",
    }
    assert "score" not in payload and "script" not in payload
    # Every rejected premise is retained as evidence, with the reason it lost.
    first = payload["attempt_summaries"][0]
    assert first["outcome"] == "plan_blocked"
    assert first["blocking_issues"]
    assert any("cannot lock from both sides" in item for item in first["blocking_issues"])
    assert len(excinfo.value.rejected_plans) == 2 * pipe.max_plan_attempts


# ---------------------------------------------------------------------------
# 10c. Live 2026-07-17 14:02, stopped by hand after ~9.5 minutes and 11 Opus calls
#      with zero writer calls. The health gate existed but ran AFTER the planner
#      loop, so a plan that kept getting blocked never reached it: the run happily
#      repaired, re-audited and re-planned against a provider it already knew was
#      dead. Health is knowable at the first audit; it must be acted on there.


def _health_pipeline(
    *,
    critic_fallback=None,
    compliance_fallback=None,
    challenger=None,
    writer_calls=None,
    plan_audits=None,
):
    """Primary DeepSeek 402s on everything; Claude escalation answers the audit."""
    counts = {"primary_audit": 0}

    def dead(_prompt, schema):
        if schema is PlanPlausibilityReview:
            counts["primary_audit"] += 1
        raise ValueError("402 Insufficient Balance")

    audits = plan_audits or iter([PlanPlausibilityReview()] * 12)

    def escalated_audit(_prompt, _schema):
        return next(audits)

    def sonnet_judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    initial = _clean_stories()

    def write(prompt, _schema):
        if writer_calls is not None:
            writer_calls.append(prompt)
        return _story_writer(initial)(prompt, _schema)

    critic = _identified(
        _FakeStructuredLLM(dead, auto_plan_audit=False), "deepseek", "deepseek-v4-pro"
    )
    # Same account, different model name: one balance, one outage, not a fallback.
    compliance = _identified(
        _FakeStructuredLLM(dead, auto_plan_audit=False), "deepseek", "deepseek-v4-flash"
    )
    pipe = NarrativeUnitPipeline(
        _identified(_FakeStructuredLLM(lambda _p, _s: _plan()), "anthropic", "claude-sonnet-5"),
        _identified(_FakeStructuredLLM(write), "anthropic", "claude-opus-5"),
        critic, None,
        compliance_llm=compliance,
        compliance_escalation_llm=compliance_fallback,
        critic_fallback_llm=critic_fallback,
        plan_audit_escalation_llm=_identified(
            _FakeStructuredLLM(escalated_audit, auto_plan_audit=False),
            "anthropic", "claude-sonnet-5",
        ),
        release_challenger_llm=challenger,
        quality_strategy=_challenger_strategy() if challenger else None,
    )
    return pipe, counts


def _sonnet_fallback():
    def judge(_prompt, schema):
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()
    return _identified(
        _FakeStructuredLLM(judge, auto_plan_audit=False), "anthropic", "claude-sonnet-5"
    )


def _opus_challenger():
    return _identified(
        _FakeStructuredLLM(
            lambda _p, _s: ReleaseChallenge(
                verdicts=[ChallengeVerdict(axis=axis, verdict="pass")
                          for axis, _rule in np._CHALLENGE_AXES],
                summary="checked every axis",
            ),
            auto_plan_audit=False,
        ),
        "anthropic", "claude-opus-5",
    )


@pytest.mark.asyncio
async def test_health_failure_aborts_before_any_repair_replan_or_writer():
    """The 14:02 run should have been: one plan, bounded primary retries, one
    escalated audit, abort. Instead it spent 11 Opus calls repairing and replanning
    against a dead provider because the gate ran after the loop."""
    writer_calls: list[str] = []
    # Every audit blocks, which is what kept the 14:02 loop alive.
    blocked = iter([PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="physical", severity="critical",
        problem="a blocked premise that would trigger repair and replan",
        plan_fix="fix it", evidence_quote="different human threat 1",
    )])] * 12)
    pipe, counts = _health_pipeline(writer_calls=writer_calls, plan_audits=blocked)

    with pytest.raises(np.QualityPathUnhealthy) as excinfo:
        await pipe.run(_brief(), annotate=False)

    calls = pipe._run_call_counts
    assert calls["planner"] == 1, "no second concept is planned against a dead path"
    assert calls["plan_repair"] == 0, "no repair against a dead path"
    assert calls["story_writer"] == 0
    assert writer_calls == []
    assert counts["primary_audit"] == 2, "primary retried twice, then stopped"
    assert calls["plan_audit_escalation"] == 1, "one escalation, not one per attempt"
    # The abort carries the first provider errors and the evidence gathered so far.
    assert excinfo.value.audit.primary_healthy is False
    assert any("402" in item for item in excinfo.value.audit.primary_provider_errors)
    assert excinfo.value.rejections, "the blocked plan is still recorded as evidence"


@pytest.mark.asyncio
async def test_a_dead_primary_is_dialled_exactly_twice_across_repair_and_reaudit():
    """Live 2026-07-17 14:32, stopped after ~31 minutes with zero writer calls.

    The health domain was marked downstream of the audit, so a re-audit inside
    targeted repair could still queue behind the same dead provider. One bounded
    failure set is enough evidence: two primary calls for the whole run, however
    many audits follow.
    """
    fallback = _sonnet_fallback()
    # Blocked -> targeted repair -> re-audit. Every audit after the first must
    # skip the primary outright.
    def _blocked(*quotes):
        return PlanPlausibilityReview(issues=[PlanIssue(
            story_id="story_1", category="prop_staging", severity="major",
            problem=f"objection on {quote}", plan_fix="fix it",
            evidence_quote=quote, knowledge_scope="universal",
        ) for quote in quotes])

    # Two blockers, then one (progress, so the repair loop continues), then clean:
    # three audits in one outer attempt, and only the first may touch the primary.
    # The second audit quotes narrator_profile, which the repair does not rewrite —
    # a quote from the repaired `threat` would no longer exist in the plan text and
    # would be rejected as ungrounded, correctly.
    pipe, counts = _health_pipeline(
        critic_fallback=fallback, compliance_fallback=fallback,
        challenger=_opus_challenger(),
        plan_audits=iter([
            _blocked("different human threat 1", "different practical escape 1"),
            _blocked("narrator 1 with a distinct job and cadence"),
            PlanPlausibilityReview(),
        ]),
    )
    # Each repair round returns a MATERIALLY different story, so the loop really
    # re-audits instead of being rejected as a verbatim resend.
    planner_state = {"n": 0, "repairs": 0}

    def plan_handler(_prompt, schema):
        if schema is np.PlanRepairOutput:
            planner_state["repairs"] += 1
            return np.PlanRepairOutput(stories=[
                _plan().stories[0].model_copy(update={
                    "threat": (
                        f"repair {planner_state['repairs']}: a man steps out from the "
                        "laundry side of the cart, not behind it"
                    ),
                }),
            ])
        planner_state["n"] += 1
        return _plan()

    pipe.planner_llm = _identified(
        _FakeStructuredLLM(plan_handler), "anthropic", "claude-sonnet-5"
    )
    # Plan repair routes through its own cheap-tier client since the cost
    # routing change; point it at the same fake for this scenario.
    pipe.plan_repair_llm = pipe.planner_llm
    result = await pipe.run(_brief(), annotate=False)

    assert counts["primary_audit"] == 2, "the dead account is never dialled again"
    assert result.call_counts["plan_audit"] == 2
    # Three audits happened; the two after the first went straight to escalation.
    assert result.call_counts["plan_audit_escalation"] == 3
    assert result.call_counts["plan_repair"] >= 1
    assert planner_state["n"] == 1, "no full replan for a locally repairable defect"
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_missing_one_mandatory_fallback_aborts_immediately():
    """A fallback for the scorer is not a fallback for compliance."""
    writer_calls: list[str] = []
    pipe, _counts = _health_pipeline(
        critic_fallback=_sonnet_fallback(), compliance_fallback=None,
        writer_calls=writer_calls,
    )
    with pytest.raises(np.QualityPathUnhealthy) as excinfo:
        await pipe.run(_brief(), annotate=False)

    message = str(excinfo.value)
    assert "story_compliance" in message
    assert "critic_score" not in message, "the scorer has a live path; do not blame it"
    assert writer_calls == []
    assert pipe._run_call_counts["plan_repair"] == 0


@pytest.mark.asyncio
async def test_a_complete_healthy_fallback_path_keeps_live_generation_running():
    """DeepSeek 402 must not stop the run when every mandatory judge has a healthy
    configured fallback. This is the path a live max-quality run depends on."""
    writer_calls: list[str] = []
    fallback = _sonnet_fallback()
    pipe, counts = _health_pipeline(
        critic_fallback=fallback, compliance_fallback=fallback,
        challenger=_opus_challenger(), writer_calls=writer_calls,
    )
    result = await pipe.run(_brief(), annotate=False)

    assert len(writer_calls) == 3, "the writer runs on a healthy fallback path"
    assert result.content_locked is True
    assert result.plan_audit.primary_healthy is False
    assert result.plan_audit.verdict_source == "escalation"
    assert result.release_challenge.status == "passed"
    assert result.release_challenge.challenger_is_independent is True


@pytest.mark.asyncio
async def test_a_dead_primary_is_never_called_again_after_its_domain_is_marked():
    """Requirement and thrift: after the account is known dead, every later
    mandatory judge goes straight to the fallback and the counters say so."""
    fallback = _sonnet_fallback()
    pipe, counts = _health_pipeline(
        critic_fallback=fallback, compliance_fallback=fallback,
        challenger=_opus_challenger(),
    )
    result = await pipe.run(_brief(), annotate=False)

    calls = result.call_counts
    # The primary auditor is retried exactly twice, once, at the first audit.
    assert counts["primary_audit"] == 2
    # ...and never again: no primary compliance, score or final calls at all.
    assert calls["story_compliance"] == 0
    assert calls["critic_score"] == 0
    assert calls["final_editor"] == 0
    # The fallback did that work, counted separately.
    assert calls["story_compliance_escalation"] == 3
    assert calls["critic_score_escalation"] == 1
    assert calls["final_editor_escalation"] == 1
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_a_challenger_matching_the_actual_fallback_judge_cannot_approve():
    """Independence is measured against the judges that ACTUALLY approved this
    release, not against the primary that never ran. When DeepSeek dies and Sonnet
    scores the compilation, a Sonnet challenger is the same reader twice."""
    fallback = _sonnet_fallback()
    same_as_judge = _identified(
        _FakeStructuredLLM(
            lambda _p, _s: ReleaseChallenge(
                verdicts=[ChallengeVerdict(axis=axis, verdict="pass")
                          for axis, _rule in np._CHALLENGE_AXES],
                summary="nothing to see",
            ),
            auto_plan_audit=False,
        ),
        "anthropic", "claude-sonnet-5",
    )
    pipe, _counts = _health_pipeline(
        critic_fallback=fallback, compliance_fallback=fallback,
        challenger=same_as_judge,
    )
    pipe._preflight_quality_path = lambda _strategy: None
    result = await pipe.run(_brief(), annotate=False)

    assert result.release_challenge.status == "not_independent"
    assert result.content_locked is False
    assert np._llm_identity_of(fallback) in result.judge_identities


@pytest.mark.asyncio
async def test_a_challenger_on_a_different_model_than_the_actual_judge_approves():
    """The control: Opus challenging a Sonnet judge is a real second reader, even
    though both are Anthropic."""
    fallback = _sonnet_fallback()
    pipe, _counts = _health_pipeline(
        critic_fallback=fallback, compliance_fallback=fallback,
        challenger=_opus_challenger(),
    )
    result = await pipe.run(_brief(), annotate=False)

    assert result.release_challenge.status == "passed"
    assert result.release_challenge.challenger_is_independent is True
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_a_same_model_challenger_veto_still_blocks_on_the_fallback_path():
    fallback = _sonnet_fallback()
    initial = _clean_stories()
    quote = initial["story_2"].narration.split("\n\n")[2]
    veto = _identified(
        _FakeStructuredLLM(
            lambda _p, _s: ReleaseChallenge(verdicts=[ChallengeVerdict(
                axis="physical_possibility", verdict="fail", story_id="story_2",
                evidence_quote=quote, explanation="the exit cannot exist",
            )], summary="one grounded veto"),
            auto_plan_audit=False,
        ),
        "anthropic", "claude-sonnet-5",
    )
    pipe, _counts = _health_pipeline(
        critic_fallback=fallback, compliance_fallback=fallback, challenger=veto,
    )
    pipe._preflight_quality_path = lambda _strategy: None
    result = await pipe.run(_brief(), annotate=False)

    assert result.release_challenge.status == "failed"
    assert result.content_locked is False


# ---------------------------------------------------------------------------
# 10d. Plan-stage budget. Live 2026-07-17 14:32: ~31 minutes, zero writer calls,
#      because one outer attempt allowed two local repairs AND a fresh planner
#      loop, with every Sonnet call running 2-7 minutes. The budget is a profile
#      field, not a magic number in the coordinator.


def test_the_strict_horror_profile_bounds_the_plan_stage():
    strategy = _horror_strategy()
    assert strategy.max_plan_attempts == 2, "one initial plan + one fresh concept"
    assert strategy.max_plan_repairs == 1, "one targeted repair, then abandon"


def _budget_pipeline(audits, *, planner_log=None, repair_story=None):
    """Horror budget, healthy providers, everything else clean."""
    state = {"planner": 0}

    def plan_handler(prompt, schema):
        if planner_log is not None:
            planner_log.append(prompt)
        if schema is np.PlanRepairOutput:
            return np.PlanRepairOutput(stories=[repair_story])
        state["planner"] += 1
        return _variant_plan(state["planner"] - 1)

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return next(audits)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler),
        _FakeStructuredLLM(_story_writer(_clean_stories())),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
        release_challenger_llm=_opus_challenger(),
        quality_strategy=_horror_strategy().model_copy(update={
            # Isolate the budget: the horror content gates read real prose and
            # these drafts are synthetic filler.
            "topic_alignment_gate": False, "plan_fact_fidelity_gate": False,
            "safety_response_gate": False, "forbidden_ending_gate": False,
        }),
    )
    return pipe, state


@pytest.mark.asyncio
async def test_a_clean_plan_costs_exactly_one_plan_and_one_audit():
    pipe, state = _budget_pipeline(iter([PlanPlausibilityReview()]))
    result = await pipe.run(_brief(), annotate=False)

    assert result.call_counts["planner"] == 1
    assert result.call_counts["plan_audit"] == 1
    assert result.call_counts["plan_repair"] == 0
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_a_repaired_plan_costs_one_plan_one_repair_and_two_audits():
    repair = _variant_plan(0).stories[0].model_copy(update={
        "threat": "a repaired threat that resolves the objection",
    })
    pipe, state = _budget_pipeline(
        iter([
            PlanPlausibilityReview(issues=[PlanIssue(
                story_id="story_1", category="prop_staging", severity="major",
                problem="cart geometry", plan_fix="fix",
                evidence_quote="different human threat 1", knowledge_scope="universal",
            )]),
            PlanPlausibilityReview(),
        ]),
        repair_story=repair,
    )
    result = await pipe.run(_brief(), annotate=False)

    assert result.call_counts["planner"] == 1, "a local defect never costs a replan"
    assert result.call_counts["plan_repair"] == 1
    assert result.call_counts["plan_audit"] == 2, "the repair is re-audited, once"
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_an_unrepairable_plan_stops_at_the_bound_not_at_exhaustion():
    """The 14:32 shape: keep blocking. One repair, then abandon the concept and
    take exactly one fresh one — not two repairs plus a third full planner loop."""
    blocked = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="prop_staging", severity="major",
        problem="cart geometry", plan_fix="fix",
        evidence_quote="different human threat 1", knowledge_scope="universal",
    )])
    repair = _variant_plan(0).stories[0].model_copy(update={
        "threat": "different human threat 1 restated but still wrong",
    })
    pipe, state = _budget_pipeline(iter([blocked] * 10), repair_story=repair)

    with pytest.raises(PlanNotPlausible):
        await pipe.run(_brief(), annotate=False)

    # max_plan_attempts=2 planner calls, each earning at most max_plan_repairs=1.
    assert state["planner"] == 2
    assert pipe._run_call_counts["planner"] == 2
    assert pipe._run_call_counts["plan_repair"] <= 2
    assert pipe._run_call_counts["story_writer"] == 0


@pytest.mark.asyncio
async def test_the_outer_retry_buys_exactly_one_fresh_concept():
    blocked = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="trope", severity="major",
        problem="premise-wide trope", plan_fix="new premise",
        evidence_quote="different human threat 1", knowledge_scope="universal",
    )])
    pipe, state = _budget_pipeline(iter([blocked] * 20))

    with pytest.raises(NarrativeRunExhausted) as excinfo:
        await pipe.run_with_retry(_brief(), annotate=False, max_attempts=2)

    evidence = excinfo.value.evidence
    assert evidence.attempts_executed == 2
    # Two outer attempts x two plan attempts each, and no more.
    assert evidence.aggregate_call_counts["planner"] == 4
    assert evidence.aggregate_call_counts["story_writer"] == 0
    # The bound is visible in the persisted evidence, not folklore.
    assert all(item.outcome == "plan_blocked" for item in evidence.attempt_summaries)


@pytest.mark.asyncio
async def test_attempt_evidence_carries_notional_subscription_cost():
    """The 14:32 log reported notional cost only on stdout. A run that spends 31
    subscription-minutes must say so in its own artifact, while aggregate_cost_usd
    stays honestly zero — a subscription call is not billed per token."""
    class _Priced(_FakeStructuredLLM):
        async def complete_structured(self, **kwargs):
            response, value = await super().complete_structured(**kwargs)
            from omnicast.llm import LLMResponse
            return LLMResponse(
                content=response.content, model="claude-sonnet-5",
                input_tokens=1, output_tokens=11924, cost_usd=0.0,
                stop_reason="end_turn", notional_cost_usd=0.1909,
                role="planner", effort="medium",
            ), value

    pipe, _state = _budget_pipeline(iter([PlanPlausibilityReview()] * 4))
    pipe.planner_llm = _Priced(pipe.planner_llm.handler)
    result = await pipe.run_with_retry(_brief(), annotate=False, max_attempts=1)

    assert result.aggregate_cost_usd == 0.0, "no marginal bill is invented"
    assert result.aggregate_notional_cost_usd == pytest.approx(0.1909)
    assert result.attempt_summaries[0].notional_cost_usd == pytest.approx(0.1909)


# ---------------------------------------------------------------------------
# 10e. Live 2026-07-17 16:03 (504.1s, writer=0): the PLANNER contract.
#      One whole plan died at preflight because topic_promise described the real
#      sites — "a laundromat", "a furniture warehouse" — without repeating the
#      extracted subject word "business". The gate is right and stays; the planner
#      was never told topic_promise is a gate string.


def _plan_prompt_for(strategy, title="3 True Encounters While Rekeying Businesses After Hours"):
    brief = _brief().model_copy(update={"title": title})
    return np._plan_prompt(brief, 3, 2250, None, "", strategy)


def test_the_planner_is_told_topic_promise_is_a_gate_string_not_prose():
    prompt = _plan_prompt_for(_horror_strategy())
    assert "INTERNAL GATE STRING" in prompt
    assert "'business'" in prompt, "the extracted subject is named literally"
    assert "verbatim" in prompt


def test_the_planner_is_shown_the_exact_failure_that_wasted_the_16_03_plan():
    """'rekeying a laundromat after closing' lost to 'rekeying a laundromat
    business after closing' purely because the subject word was missing."""
    prompt = _plan_prompt_for(_horror_strategy())
    assert "laundromat" in prompt
    assert "concrete site" in prompt or "concrete site or job" in prompt
    # And that naming a site is not an escape from naming the subject.
    assert "not a substitute" in prompt


def test_the_subject_contract_survives_a_topic_with_no_extractable_subject():
    prompt = _plan_prompt_for(_horror_strategy(), title="True Encounters")
    assert "INTERNAL GATE STRING" in prompt


def test_the_plan_self_audit_is_present_for_strict_horror():
    """Every rule is a defect the 16:03 auditor already caught AFTER the plan was
    paid for. Checking it inside the planner's own call is free."""
    prompt = _plan_prompt_for(_horror_strategy())
    assert "BEFORE YOU RETURN" in prompt
    for rule in (
        "Trade reality",          # locksmith trapped by his own lock
        "Egress",                 # fire-code interior exit hardware
        "Staged mechanism",       # doors that latch themselves
        "Repeated threat",        # third night alone with a stalker
        "Response immediacy",     # non-emergency call at the glass
        "Consistency",            # trusted_adult vs told_no_one
        "Trade logic",            # generic haunted-house mechanics
    ):
        assert rule in prompt, rule


def test_the_plan_self_audit_is_channel_scoped():
    """A generic channel must not inherit horror trade-reality policy."""
    generic = NamedChannelStrategy(
        strategy_id="generic_test", writer_rules="w", critic_rules="c",
        annotation_rules="a",
    )
    assert generic.plan_self_audit == ""
    prompt = _plan_prompt_for(generic)
    assert "BEFORE YOU RETURN" not in prompt
    assert "Trade reality" not in prompt


def test_the_self_audit_does_not_ask_for_extra_output():
    """It is a pass over the plan, not a new field or a narrated checklist — the
    schema is unchanged and this must not tempt the model to pad it."""
    prompt = _plan_prompt_for(_horror_strategy())
    assert "Do not narrate this pass" in prompt
    assert "return only the JSON" in prompt


def test_the_repair_prompt_states_the_constraint_that_killed_every_16_03_repair():
    plan = _plan()
    prompt = np._plan_repair_prompt(
        plan, ["story_1"],
        [PlanIssue(story_id="story_1", category="physical", severity="major",
                   problem="p", plan_fix="f", evidence_quote="different human threat 1")],
        _horror_strategy(),
    )
    assert "24 WORDS OR FEWER" in prompt
    assert "thrown away unjudged" in prompt
    assert "compact" in prompt
    # Every required field named, so a repair cannot omit one by accident.
    for field in ("continuity_ledger", "topic_promise", "safety_obligation",
                  "narrator_age_band", "threat_mechanism", "voice_rules"):
        assert field in prompt, field


# ---------------------------------------------------------------------------
# 11. Live 2026-07-17 13:34 (575.1s, zero stories, planner=6 / plan_audit=10 /
#     plan_audit_escalation=5): every rejected plan must keep its OWN reasons.


@pytest.mark.asyncio
async def test_each_rejected_plan_keeps_its_own_reasons_in_order():
    """The 13:34 audit persisted rejected_plans[5] and one trailing blocker list,
    so four of the five could not be matched to why they died."""
    state = {"n": 0}

    def plan_handler(_prompt, _schema):
        state["n"] += 1
        return _variant_plan(state["n"] - 1)

    quotes = {1: "different human threat 1", 2: "different human threat 2"}

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            index = min(state["n"], 2)
            return PlanPlausibilityReview(issues=[PlanIssue(
                story_id=f"story_{index}", category="physical", severity="critical",
                problem=f"objection number {state['n']}",
                plan_fix="fix it", evidence_quote=quotes[index],
            )])
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler),
        _FakeStructuredLLM(lambda _p, _s: pytest.fail("writer must not be called")),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    # Repair returns a CompilationPlan (not a repair object), so every repair is
    # rejected too — which is itself a rejection record we want to see.
    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    rejections = excinfo.value.rejections
    audit_rejections = [item for item in rejections if item.stage == "audit"]
    assert len(audit_rejections) == pipe.max_plan_attempts
    # One-to-one: each record carries the plan it rejected and that plan's reasons.
    for index, item in enumerate(audit_rejections, 1):
        assert item.plan is not None
        assert item.plan_fingerprint and item.material_digest
        assert item.audit is not None and item.audit.status == "blocked"
        assert any("objection number" in reason for reason in item.errors)
        assert item.call_counts["planner"] >= index
        assert item.latency_s >= 0.0
    # Distinct plans produce distinct records, not one blurred trailing list.
    assert len({item.material_digest for item in audit_rejections}) == len(audit_rejections)
    assert [item.planner_attempt for item in audit_rejections] == [1, 2, 3]
    # And the repair attempts are recorded as their own stage.
    assert [item.stage for item in rejections if item.stage == "repair"]


@pytest.mark.asyncio
async def test_a_schema_invalid_planner_response_is_recorded_not_silently_burned():
    """The live planner omitted story_2.voice_rules. That concept vanished with no
    trace: no plan object, no raw evidence, one attempt gone."""
    bad = _plan().model_dump(mode="json")
    del bad["stories"][1]["voice_rules"]
    state = {"n": 0}

    def plan_handler(_prompt, _schema):
        state["n"] += 1
        return bad

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler),
        _FakeStructuredLLM(lambda _p, _s: pytest.fail("writer must not be called")),
        _FakeStructuredLLM(lambda _p, _s: _passing_score(), auto_plan_audit=False), None,
    )
    with pytest.raises(np.PlannerUnavailable) as excinfo:
        await pipe.run(_brief(), annotate=False)

    schema_rejections = [
        item for item in excinfo.value.rejections if item.stage == "schema"
    ]
    assert len(schema_rejections) == pipe.max_plan_attempts
    first = schema_rejections[0]
    assert "voice_rules" in first.raw_evidence
    assert first.plan is None, "there is no plan object to keep — say so, do not invent one"
    assert first.call_counts["planner"] >= 1
    # A schema slip earns one contract-only retry rather than burning the concept.
    assert pipe._run_call_counts["planner_schema_retry"] == pipe.max_plan_attempts
    retry_prompts = [c for c in pipe.planner_llm.calls if "CONTRACT RETRY" in c]
    assert retry_prompts and "voice_rules" in retry_prompts[0]


@pytest.mark.asyncio
async def test_a_schema_retry_that_completes_the_plan_saves_the_concept():
    state = {"n": 0}
    bad = _plan().model_dump(mode="json")
    del bad["stories"][1]["voice_rules"]

    def plan_handler(_prompt, _schema):
        state["n"] += 1
        return bad if state["n"] == 1 else _plan()

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler),
        _FakeStructuredLLM(_story_writer(_clean_stories())),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["planner"] == 1
    assert result.call_counts["planner_schema_retry"] == 1
    assert result.content_locked is True


def _plan_with_overlong_ledger_entry() -> dict:
    """Live 2026-07-20: the planner emitted a hook_timeline entry over the 24-word
    cap. Every field was present, so a retry that only lists required fields tells
    it nothing it did not already satisfy."""
    bad = _plan().model_dump(mode="json")
    bad["stories"][1]["continuity_ledger"][0] = (
        "hook_timeline: One overnight shift that began a little before eleven at "
        "night and ran on without any real break at all until the parking lot "
        "lights finally clicked off well before sunrise."
    )
    return bad


@pytest.mark.asyncio
async def test_the_schema_retry_names_a_ledger_length_violation_not_just_fields():
    """A length violation answered with 'return the SAME plan' makes the planner
    resend the identical over-long entry and burn both tries."""
    bad = _plan_with_overlong_ledger_entry()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: bad),
        _FakeStructuredLLM(lambda _p, _s: pytest.fail("writer must not be called")),
        _FakeStructuredLLM(lambda _p, _s: _passing_score(), auto_plan_audit=False), None,
    )
    with pytest.raises(np.PlannerUnavailable) as excinfo:
        await pipe.run(_brief(), annotate=False)

    schema_rejections = [
        item for item in excinfo.value.rejections if item.stage == "schema"
    ]
    assert schema_rejections, "a ledger-length reject is a schema reject"
    assert "24 words" in schema_rejections[0].raw_evidence

    retry_prompts = [c for c in pipe.planner_llm.calls if "CONTRACT RETRY" in c]
    assert retry_prompts, "a length violation still earns its contract retry"
    retry = retry_prompts[0]
    # The retry must tell it the fields are already present and what to shorten,
    # otherwise it resends the same wording verbatim.
    assert "LENGTH" in retry
    assert "24 words" in retry
    assert "already all present" in retry


@pytest.mark.asyncio
async def test_a_shortened_ledger_entry_on_retry_saves_the_concept():
    state = {"n": 0}
    bad = _plan_with_overlong_ledger_entry()

    def plan_handler(_prompt, _schema):
        state["n"] += 1
        return bad if state["n"] == 1 else _plan()

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler),
        _FakeStructuredLLM(_story_writer(_clean_stories())),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    ).run(_brief(), annotate=False)

    assert result.call_counts["planner"] == 1
    assert result.call_counts["planner_schema_retry"] == 1
    assert result.content_locked is True


# ---------------------------------------------------------------------------
# 12. Plan-audit grounding and uncertainty calibration.
#     The live audit produced four legitimate blockers and one overclaim.


def test_the_live_geometry_and_hardware_blockers_still_block():
    """Verbatim from the 13:34 audit. These are what the gate is FOR: the auditor
    can know them from the plan text alone, and it quoted them."""
    plan = _plan()
    for category, problem in (
        ("prop_staging", "the man 'stands between her and the van' but the ledger puts "
                         "him on the laundry side of the cart"),
        ("physical", "a shed door latched from outside cannot have its latch thrown "
                     "from inside"),
        ("geography", "the escape backs toward the shed that holds the sound"),
        ("physical", "a hot-drink machine cannot complete a brew cycle after the mains "
                     "breaker is cut"),
        ("professional", "a trade tech would run the obvious diagnostic first"),
    ):
        review = PlanPlausibilityReview(issues=[PlanIssue(
            story_id="story_1", category=category, severity="major",
            problem=problem, plan_fix="fix it",
            evidence_quote="different human threat 1",
            knowledge_scope="universal",
        )])
        assert validate_plan_audit_issues(review, plan) == []
        assert evaluate_plan_audit(review, plan).status == "blocked"


def test_the_live_valet_overclaim_cannot_veto_a_concept():
    """Verbatim from the 13:34 audit: 'A staffed, lit valet booth at a
    hospital-adjacent garage at 1:25 a.m. is wrong trade knowledge'. Some hospitals
    do staff overnight valet. Absent a plan that states the hours, this is
    site-specific uncertainty — worth saying, not worth killing the concept."""
    plan = _plan()
    review = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="professional", severity="major",
        problem=(
            "a staffed lit valet booth at a hospital-adjacent garage at 1:25 a.m. is "
            "wrong trade knowledge; valet shuts down well before midnight"
        ),
        plan_fix="replace the valet booth with a security booth or the ER desk",
        evidence_quote="different human threat 1",
        knowledge_scope="site_specific",
    )])
    result = evaluate_plan_audit(review, plan)

    assert result.status == "valid", "site-specific speculation must not block"
    assert result.issues[0].severity == "minor"
    assert "demoted" in result.issues[0].problem
    # The recommendation survives for the planner to consider.
    assert "security booth" in result.issues[0].plan_fix


def test_a_site_policy_the_plan_itself_states_can_still_block():
    """The rule is about what the plan says, not about the auditor's expectations:
    when the plan states the policy and the story contradicts it, that is an
    in-plan contradiction the auditor can see."""
    plan = _plan()
    stated = plan.model_copy(update={"stories": [
        plan.stories[0].model_copy(update={
            "setting": "a garage whose valet booth closes at ten every night",
        }),
        *plan.stories[1:],
    ]})
    review = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="physical", severity="major",
        problem="the plan states the booth closes at ten, then staffs it at 1:25 a.m.",
        plan_fix="pick one",
        evidence_quote="a garage whose valet booth closes at ten every night",
        knowledge_scope="universal",
    )])
    assert validate_plan_audit_issues(review, stated) == []
    assert evaluate_plan_audit(review, stated).status == "blocked"


def test_an_unquotable_blocking_objection_is_not_a_clean_audit():
    plan = _plan()
    review = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="physical", severity="critical",
        problem="something about this feels wrong", plan_fix="fix it",
    )])
    errors = validate_plan_audit_issues(review, plan)
    assert errors and "evidence_quote" in errors[0]

    fabricated = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="physical", severity="critical",
        problem="quoting something the plan never said", plan_fix="fix it",
        evidence_quote="a sentence that appears nowhere in this plan",
    )])
    assert validate_plan_audit_issues(fabricated, plan)


@pytest.mark.asyncio
async def test_a_persistently_ungroundable_audit_fails_closed_before_the_writer():
    writer_calls: list[str] = []

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview(issues=[PlanIssue(
                story_id="story_1", category="physical", severity="critical",
                problem="ungrounded", plan_fix="fix",
                evidence_quote="text that is not in the plan",
            )])
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(lambda p, _s: writer_calls.append(p)),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )
    with pytest.raises(PlanAuditUnavailable) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert writer_calls == []
    assert excinfo.value.audit.status == "contract_failed"
    assert excinfo.value.audit.contract_errors
    # An auditor that answered and could not ground itself is neither an outage
    # nor a clean plan.
    assert excinfo.value.audit.status != "infra_failed"


# ---------------------------------------------------------------------------
# 13. Targeted plan repair: 9.6 minutes and six full replans for one bad story.


def _repair_pipeline(repair_story, *, audits, planner_log=None):
    state = {"n": 0}

    def plan_handler(prompt, schema):
        if planner_log is not None:
            planner_log.append(prompt)
        if schema is np.PlanRepairOutput:
            return np.PlanRepairOutput(stories=[repair_story])
        state["n"] += 1
        return _plan()

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return next(audits)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    return NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler),
        _FakeStructuredLLM(_story_writer(_clean_stories())),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    )


@pytest.mark.asyncio
async def test_a_blocked_story_is_repaired_without_touching_the_clean_ones():
    """The live cart/latch/escape objections were all single-story defects, and two
    of three stories were fine every time."""
    planner_log: list[str] = []
    repaired_story = _plan().stories[0].model_copy(update={
        "threat": "a man steps out from the laundry side of the cart, not behind it",
    })
    audits = iter([
        PlanPlausibilityReview(issues=[PlanIssue(
            story_id="story_1", category="prop_staging", severity="major",
            problem="the cart geometry contradicts the threat position",
            plan_fix="put the man on one side of the cart and keep him there",
            evidence_quote="different human threat 1", knowledge_scope="universal",
        )]),
        PlanPlausibilityReview(),
    ])
    pipe = _repair_pipeline(repaired_story, audits=audits, planner_log=planner_log)

    result = await pipe.run(_brief(), annotate=False)

    assert result.content_locked is True
    assert result.call_counts["planner"] == 1, "no full replan for a one-story defect"
    assert result.call_counts["plan_repair"] == 1
    assert result.call_counts["plan_audit"] == 2, "the repair is re-audited in full"
    # The repair is applied...
    assert result.plan.stories[0].threat.startswith("a man steps out")
    # ...and the approved stories are byte-identical.
    baseline = _plan()
    for index in (1, 2):
        assert result.plan.stories[index].model_dump() == baseline.stories[index].model_dump()
    repair_prompt = next(p for p in planner_log if "Repair ONLY the blocked" in p)
    assert "cart geometry" in repair_prompt
    assert "put the man on one side" in repair_prompt


# ---------------------------------------------------------------------------
# 13b. Live 2026-07-17 16:03 (504.1s, writer=0, notional $0.7666): all THREE
#      targeted repairs died on the envelope before re-audit — twice on
#      continuity_ledger entries over 24 words, once on truncated JSON. The
#      proposed fixes were never judged at all. A malformed envelope is not a
#      rejected idea.


def _repair_schema_pipeline(audits, repairs, *, planner_log=None):
    """Planner returns each item of `repairs` in turn for a PlanRepairOutput ask:
    an Exception is raised (schema failure), anything else is returned."""
    state = {"planner": 0, "repair": 0}

    def plan_handler(prompt, schema):
        if planner_log is not None:
            planner_log.append(prompt)
        if schema is np.PlanRepairOutput:
            item = repairs[min(state["repair"], len(repairs) - 1)]
            state["repair"] += 1
            if isinstance(item, Exception):
                raise item
            return item
        state["planner"] += 1
        # A genuinely fresh concept each time, or attempt 2 is (correctly)
        # rejected at freshness before it can ever reach a repair.
        return _variant_plan(state["planner"] - 1)

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return next(audits)
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler),
        _FakeStructuredLLM(_story_writer(_clean_stories())),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
        release_challenger_llm=_opus_challenger(),
        quality_strategy=_horror_strategy().model_copy(update={
            "topic_alignment_gate": False, "plan_fact_fidelity_gate": False,
            "safety_response_gate": False, "forbidden_ending_gate": False,
        }),
    )
    return pipe, state


def _cart_blocker():
    return PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="prop_staging", severity="major",
        problem="the cart geometry contradicts the threat position",
        plan_fix="put the man on one side of the cart",
        evidence_quote="different human threat 1", knowledge_scope="universal",
    )])


def _good_repair(generation: int = 0):
    return np.PlanRepairOutput(stories=[
        _variant_plan(generation).stories[0].model_copy(update={
            "threat": "a repaired threat that resolves the objection",
        }),
    ])


@pytest.mark.asyncio
async def test_a_ledger_too_long_earns_one_contract_retry_and_reaches_re_audit():
    """The exact 16:03 failure: `continuity ledger entries must be concise
    (<=24 words)`. One retry with the validator's own words, and the fix is
    finally judged."""
    planner_log: list[str] = []
    pipe, state = _repair_schema_pipeline(
        iter([_cart_blocker(), PlanPlausibilityReview()]),
        [
            ValueError(
                "1 validation error for PlanRepairOutput\nstories.0.continuity_ledger\n"
                "  Value error, continuity ledger entries must be concise (<=24 words)"
            ),
            _good_repair(),
        ],
        planner_log=planner_log,
    )
    result = await pipe.run(_brief(), annotate=False)

    assert result.call_counts["plan_repair"] == 1
    assert result.call_counts["plan_repair_schema_retry"] == 1, "counted apart"
    assert result.call_counts["plan_audit"] == 2, "the repair was actually re-audited"
    assert result.call_counts["planner"] == 1, "an envelope slip is not a burnt concept"
    assert result.plan.stories[0].threat.startswith("a repaired threat")
    assert result.content_locked is True

    retry = next(p for p in planner_log if "CONTRACT RETRY" in p)
    assert "<=24 words" in retry, "the validator's exact words go back"
    assert "THE SAME repaired stories" in retry, "a fix, not a redesign"


@pytest.mark.asyncio
async def test_truncated_json_earns_the_same_single_retry():
    """The third 16:03 repair: 'unexpected end of data: line 61 column 2'."""
    pipe, _state = _repair_schema_pipeline(
        iter([_cart_blocker(), PlanPlausibilityReview()]),
        [ValueError("unexpected end of data: line 61 column 2 (char 4812)"),
         _good_repair()],
    )
    result = await pipe.run(_brief(), annotate=False)
    assert result.call_counts["plan_repair_schema_retry"] == 1
    assert result.content_locked is True


@pytest.mark.asyncio
async def test_two_schema_failures_stop_after_exactly_two_repair_calls():
    """Bounded: the retry is one, not a loop. The 16:03 run must not become a
    schema-retry storm."""
    pipe, state = _repair_schema_pipeline(
        iter([_cart_blocker()] * 8),
        [ValueError("continuity ledger entries must be concise (<=24 words)")] * 5,
    )
    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    calls = pipe._run_call_counts
    assert calls["plan_repair"] + calls["plan_repair_schema_retry"] == 2 * 2, (
        "one repair + one schema retry per planner attempt, and max_plan_attempts=2"
    )
    assert calls["plan_repair"] == 2 and calls["plan_repair_schema_retry"] == 2
    assert calls["story_writer"] == 0
    repair_rejections = [r for r in excinfo.value.rejections if r.stage == "repair"]
    assert repair_rejections
    assert any("<=24 words" in item.raw_evidence for item in repair_rejections), (
        "the envelope failure is persisted, not just counted"
    )


@pytest.mark.asyncio
async def test_a_retry_returning_the_wrong_story_fails_closed():
    pipe, _state = _repair_schema_pipeline(
        iter([_cart_blocker()] * 8),
        [
            ValueError("continuity ledger entries must be concise (<=24 words)"),
            # story_2 was never blocked.
            np.PlanRepairOutput(stories=[_plan().stories[1]]),
        ],
    )
    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert any(
        "must return exactly the blocked stories" in error
        for item in excinfo.value.rejections for error in item.errors
    )
    assert pipe._run_call_counts["story_writer"] == 0


@pytest.mark.asyncio
async def test_a_retry_that_drifts_an_approved_story_fails_closed():
    """Byte preservation survives the retry path: a repair may only touch what was
    blocked, however many envelopes it took to arrive."""
    drifted = _plan().stories[0].model_copy(update={"threat": "repaired"})
    pipe, _state = _repair_schema_pipeline(
        iter([_cart_blocker()] * 8),
        [
            ValueError("unexpected end of data"),
            # Returns the blocked story AND an unrequested rewrite of story_3.
            np.PlanRepairOutput(stories=[
                drifted,
                _plan().stories[2].model_copy(update={"threat": "meddled with"}),
            ]),
        ],
    )
    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert any(
        "must return exactly the blocked stories" in error
        for item in excinfo.value.rejections for error in item.errors
    )
    assert pipe._run_call_counts["story_writer"] == 0


@pytest.mark.asyncio
async def test_the_schema_retry_counter_reaches_the_failure_audit():
    pipe, _state = _repair_schema_pipeline(
        iter([_cart_blocker()] * 12),
        [ValueError("continuity ledger entries must be concise (<=24 words)")] * 9,
    )
    with pytest.raises(NarrativeRunExhausted) as excinfo:
        await pipe.run_with_retry(_brief(), annotate=False, max_attempts=2)

    payload = json.loads(excinfo.value.evidence.model_dump_json())
    counts = payload["aggregate_call_counts"]
    # One repair + exactly one schema retry per blocked plan that reached a repair.
    assert counts["plan_repair"] == counts["plan_repair_schema_retry"] > 0
    assert payload["attempt_summaries"][0]["call_counts"]["plan_repair"] == 2
    assert payload["attempt_summaries"][0]["call_counts"]["plan_repair_schema_retry"] == 2
    # The aggregate is the sum of the attempts, not a separate story.
    assert counts["plan_repair_schema_retry"] == sum(
        item["call_counts"]["plan_repair_schema_retry"]
        for item in payload["attempt_summaries"]
    )


@pytest.mark.asyncio
async def test_a_repair_that_drifts_into_an_approved_story_is_rejected():
    planner_log: list[str] = []
    # A "repair" that returns story_2 when story_1 was blocked.
    wrong = _plan().stories[1].model_copy(update={"threat": "something else entirely"})
    audits = iter([
        PlanPlausibilityReview(issues=[PlanIssue(
            story_id="story_1", category="prop_staging", severity="major",
            problem="cart geometry", plan_fix="fix",
            evidence_quote="different human threat 1", knowledge_scope="universal",
        )]),
    ] + [PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="prop_staging", severity="major",
        problem="cart geometry", plan_fix="fix",
        evidence_quote="different human threat 1", knowledge_scope="universal",
    )])] * 6)
    pipe = _repair_pipeline(wrong, audits=audits, planner_log=planner_log)

    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    repair_rejections = [r for r in excinfo.value.rejections if r.stage == "repair"]
    assert repair_rejections
    assert any(
        "must return exactly the blocked stories" in error
        for item in repair_rejections for error in item.errors
    )


@pytest.mark.asyncio
async def test_a_repair_may_not_buy_its_way_past_mechanism_diversity():
    """Repair reruns every gate the planner had to satisfy."""
    planner_log: list[str] = []
    # "Fixes" story_1 by adopting story_2's escape mechanism.
    colliding = _plan().stories[0].model_copy(update={
        "escape_mechanism": _plan().stories[1].escape_mechanism,
    })
    blocker = PlanPlausibilityReview(issues=[PlanIssue(
        story_id="story_1", category="geography", severity="major",
        problem="the escape route runs toward the threat", plan_fix="turn it around",
        evidence_quote="different practical escape 1", knowledge_scope="universal",
    )])
    pipe = _repair_pipeline(colliding, audits=iter([blocker] * 8), planner_log=planner_log)

    with pytest.raises(PlanNotPlausible) as excinfo:
        await pipe.run(_brief(), annotate=False)

    repair_rejections = [r for r in excinfo.value.rejections if r.stage == "repair"]
    assert any(
        "escape_mechanism" in error
        for item in repair_rejections for error in item.errors
    ), "a repair that collides mechanisms must be rejected like any plan"


@pytest.mark.asyncio
async def test_a_premise_wide_objection_is_not_repaired_locally():
    """When every story is objected to, the concept is the defect — repairing
    story-by-story would just relitigate it three times."""
    planner_log: list[str] = []
    audits = iter([PlanPlausibilityReview(issues=[
        PlanIssue(
            story_id=f"story_{i}", category="trope", severity="major",
            problem="the whole premise is a recognizable AI-horror trope",
            plan_fix="pick a different premise",
            evidence_quote=f"different human threat {i}", knowledge_scope="universal",
        ) for i in (1, 2, 3)
    ])] * 8)
    pipe = _repair_pipeline(_plan().stories[0], audits=audits, planner_log=planner_log)

    with pytest.raises(PlanNotPlausible):
        await pipe.run(_brief(), annotate=False)

    assert pipe._run_call_counts["plan_repair"] == 0, "no local fix for a dead premise"
    assert pipe._run_call_counts["planner"] == pipe.max_plan_attempts


@pytest.mark.asyncio
async def test_an_aborted_attempt_still_reports_what_it_spent():
    state = {"attempt": 0}

    def plan_handler(_prompt, _schema):
        state["attempt"] += 1
        # Three plan attempts x (one plan + one contract-only schema retry).
        if state["attempt"] <= 6:
            raise ValueError("provider outage")
        return _plan()

    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(plan_handler), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
    ).run_with_retry(_brief(), annotate=False, max_attempts=2)

    assert result.attempts_executed == 2
    aborted = result.attempt_summaries[0]
    assert aborted.outcome == "aborted"
    assert "provider outage" in aborted.reason
    assert aborted.call_counts["planner"] == 3, "the dead attempt still billed three plans"
    assert result.aggregate_call_counts["planner"] == 4


# ---------------------------------------------------------------------------
# 10. The adversarial release challenger only runs for would-be releases,
#     and its absence fails closed.


@pytest.mark.asyncio
async def test_release_challenger_can_veto_a_would_be_release_with_a_grounded_quote():
    """The this-morning/changed-route timeline contradiction the judges both missed."""
    stories = _artifact_stories()
    quote = "This morning was ordinary right up until it wasn't."
    assert quote in stories[2].narration

    challenge = ReleaseChallenge(
        verdicts=[ChallengeVerdict(
            axis="timeline_consistency", verdict="fail", story_id="story_3",
            evidence_quote=quote,
            explanation=(
                "The encounter is 'this morning' yet the ending describes an already "
                "changed route nobody has asked about."
            ),
        )],
        summary="one grounded timeline contradiction",
    )
    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(lambda _p, _s: None),
        _FakeStructuredLLM(lambda _p, _s: None), None,
        release_challenger_llm=_FakeStructuredLLM(
            lambda _p, _s: challenge, auto_plan_audit=False
        ),
        quality_strategy=_horror_strategy(),
    )
    result, passed, issues = await pipe._release_challenge(
        _artifact_plan(), stories, pipe.quality_strategy
    )
    assert passed is False
    assert result.status == "failed"
    assert issues[0].story_id == "story_3"
    assert issues[0].severity == "major"
    assert issues[0].evidence_quote == quote


@pytest.mark.asyncio
async def test_challenger_fail_verdict_without_an_exact_quote_is_not_trusted():
    challenge = ReleaseChallenge(verdicts=[ChallengeVerdict(
        axis="physical_possibility", verdict="fail", story_id="story_3",
        evidence_quote="a sentence that does not appear anywhere",
        explanation="vibes",
    )], summary="ungrounded")
    challenger = _FakeStructuredLLM(lambda _p, _s: challenge, auto_plan_audit=False)
    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(lambda _p, _s: None),
        _FakeStructuredLLM(lambda _p, _s: None), None,
        release_challenger_llm=challenger, quality_strategy=_horror_strategy(),
    )
    result, passed, issues = await pipe._release_challenge(
        _artifact_plan(), _artifact_stories(), pipe.quality_strategy
    )
    # Two contract attempts, then fail closed: an ungrounded veto cannot be repaired,
    # and an unverifiable challenger cannot approve either.
    assert len(challenger.calls) == 2
    assert passed is False
    assert result.status == "contract_failed"
    assert issues == []


@pytest.mark.asyncio
async def test_a_required_challenger_that_is_not_configured_fails_closed_before_the_writer():
    writer_calls: list[str] = []

    def write(prompt, _schema):
        writer_calls.append(prompt)
        return StoryOutput(title="t", hook_candidates=["h"], narration="n")

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        return _passing_score()

    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
        quality_strategy=_horror_strategy(),  # requires a challenger
    )
    with pytest.raises(np.QualityPathUnavailable) as excinfo:
        await pipe.run(_brief(), annotate=False)
    assert writer_calls == []
    assert "release_challenger" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 10b. A challenger that shares the critic's provider cannot APPROVE.
#
# The whole point of the adversary is to break correlated judge error. On
# 2026-07-17 the critic and the final editor were the same provider and agreed
# with each other about a compilation neither had read carefully enough. A third
# opinion from that same provider is not a third opinion — it is the same blind
# spot, billed again. It may still VETO (a grounded quote is evidence regardless
# of who found it), but its approval carries no independent information.


def _challenger_strategy() -> NamedChannelStrategy:
    """Requires the adversary and nothing else.

    The horror profile's content gates read real prose; these tests use synthetic
    filler drafts, so running them under the full profile would fail on topic
    fidelity long before the challenger was consulted, and the test would pass
    while proving nothing about independence.
    """
    return NamedChannelStrategy(
        strategy_id="challenger_test", writer_rules="w", critic_rules="c",
        annotation_rules="a", release_challenger_required=True,
    )


def _same_provider_pipeline(challenge, *, initial=None, strategy=None):
    initial = initial or _clean_stories()

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    critic = _identified(
        _FakeStructuredLLM(judge, auto_plan_audit=False), "deepseek", "deepseek-v4-pro"
    )
    challenger = _identified(
        _FakeStructuredLLM(lambda _p, _s: challenge, auto_plan_audit=False),
        "deepseek", "deepseek-v4-pro",
    )
    return NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(_story_writer(initial)), critic, None,
        release_challenger_llm=challenger,
        quality_strategy=strategy or _challenger_strategy(),
    ), challenger


@pytest.mark.asyncio
async def test_a_required_challenger_on_the_critics_own_provider_fails_before_the_writer():
    """Identity is knowable at construction, so this costs nothing to catch early."""
    writer_calls: list[str] = []

    def write(prompt, _schema):
        writer_calls.append(prompt)
        return StoryOutput(title="t", hook_candidates=["h"], narration="n")

    critic = _identified(
        _FakeStructuredLLM(lambda _p, _s: _passing_score(), auto_plan_audit=False),
        "deepseek", "deepseek-v4-pro",
    )
    challenger = _identified(
        _FakeStructuredLLM(lambda _p, _s: None, auto_plan_audit=False),
        "deepseek", "deepseek-v4-pro",
    )
    pipe = NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()), _FakeStructuredLLM(write),
        critic, None, release_challenger_llm=challenger,
        quality_strategy=_challenger_strategy(),
    )
    with pytest.raises(np.QualityPathUnavailable) as excinfo:
        await pipe.run(_brief(), annotate=False)

    assert writer_calls == []
    assert "release_challenger" in str(excinfo.value)
    assert "independent" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_same_provider_challenger_pass_never_unlocks_a_release():
    """The defect this closes: status='passed' satisfied content_can_lock while
    provider independence was merely logged."""
    clean = ReleaseChallenge(
        verdicts=[ChallengeVerdict(axis=axis, verdict="pass")
                  for axis, _rule in np._CHALLENGE_AXES],
        summary="looks fine to me",
    )
    pipe, challenger = _same_provider_pipeline(clean)
    # Bypass the construction-time preflight to prove the challenge-time recheck
    # is a real second line rather than a duplicate of the first.
    pipe._preflight_quality_path = lambda _strategy: None

    result = await pipe.run(_brief(), annotate=False)

    assert result.release_challenge.status == "not_independent"
    assert result.release_challenge.challenger_is_independent is False
    assert result.content_locked is False, "a same-provider pass must not unlock"
    assert result.production_ready is False
    assert result.release_tier != "production_test_ready"
    assert len(challenger.calls) == 1
    assert any("same blind spot" in item for item in result.release_challenge.errors)


@pytest.mark.asyncio
async def test_a_same_provider_challenger_veto_still_blocks():
    """Evidence is evidence. A grounded quote from a correlated judge is still a
    defect, so a same-provider challenger may block even though it cannot approve."""
    initial = _clean_stories()
    quote = initial["story_2"].narration.split("\n\n")[2]
    veto = ReleaseChallenge(verdicts=[ChallengeVerdict(
        axis="physical_possibility", verdict="fail", story_id="story_2",
        evidence_quote=quote, explanation="the exit described cannot exist",
    )], summary="one grounded veto")
    pipe, _challenger = _same_provider_pipeline(veto, initial=initial)

    result, passed, issues = await pipe._release_challenge(
        _plan(), list(initial.values()), pipe.quality_strategy
    )
    assert passed is False
    assert result.status == "failed"
    assert issues and issues[0].severity == "major"
    assert issues[0].evidence_quote == quote


@pytest.mark.asyncio
async def test_a_genuinely_independent_challenger_pass_does_unlock():
    """The control: the gate must reject correlation, not adversaries."""
    clean = ReleaseChallenge(
        verdicts=[ChallengeVerdict(axis=axis, verdict="pass")
                  for axis, _rule in np._CHALLENGE_AXES],
        summary="checked every axis",
    )
    initial = _clean_stories()

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return _passing_score()

    critic = _identified(
        _FakeStructuredLLM(judge, auto_plan_audit=False), "deepseek", "deepseek-v4-pro"
    )
    challenger = _identified(
        _FakeStructuredLLM(lambda _p, _s: clean, auto_plan_audit=False),
        "anthropic", "claude-sonnet-5",
    )
    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()),
        _FakeStructuredLLM(_story_writer(initial)), critic, None,
        release_challenger_llm=challenger, quality_strategy=_challenger_strategy(),
    ).run(_brief(), annotate=False)

    assert result.release_challenge.status == "passed"
    assert result.release_challenge.challenger_is_independent is True
    assert result.content_locked is True
    assert len(challenger.calls) == 1


@pytest.mark.asyncio
async def test_challenger_does_not_run_when_the_compilation_is_not_a_release_candidate():
    """It is an adversary for would-be releases, not a tax on every failed draft."""
    challenger = _FakeStructuredLLM(
        lambda _p, _s: ReleaseChallenge(verdicts=[], summary="x"), auto_plan_audit=False
    )
    initial = {f"story_{i}": _draft(i) for i in range(1, 4)}

    def write(prompt, _schema):
        sid = next(s for s in initial if s in prompt)
        draft = initial[sid]
        return StoryOutput(
            title=draft.title, hook_candidates=draft.hook_candidates,
            narration=draft.narration,
        )

    weak = _passing_score().model_copy(update={"distinct_authentic_voices": 5})

    def judge(_prompt, schema):
        if schema is PlanPlausibilityReview:
            return PlanPlausibilityReview()
        if schema is FinalCompilationReview:
            return _approved_final_review()
        return weak

    result = await NarrativeUnitPipeline(
        _FakeStructuredLLM(lambda _p, _s: _plan()), _FakeStructuredLLM(write),
        _FakeStructuredLLM(judge, auto_plan_audit=False), None,
        release_challenger_llm=challenger,
    ).run(_brief(), annotate=False)

    assert result.content_locked is False
    assert challenger.calls == []
    assert result.call_counts["release_challenger"] == 0
