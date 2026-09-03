"""Unit-first pipeline for first-person horror recollections.

Narration is planned and written as independent stories, audited as one compilation,
repaired at story granularity, then locked before production metadata is generated.
The coordinator deliberately does not inherit BaseAgent: explicit LLM dependencies make
call count, concurrency, and paid-model routing observable and unit-testable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
from typing import Literal

from pathlib import Path

import structlog
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

# This module records its diagnostics into narrative_failure_audit.json, which
# is the right home for anything an operator reviews later. The logger exists
# for the failures that never reach an audit record because a retry papered
# over them — a first-attempt schema rejection is overwritten the moment the
# second attempt succeeds, and the only trace left is a call counter.
logger = structlog.get_logger()

from omnicast.models.script import (
    ScriptDraft,
    ScriptScene,
    ScriptSegment,
    TopicBrief,
    spoken_word_floor,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NamedChannelStrategy(_StrictModel):
    """Immutable, bounded creative contract selected by a channel config."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    strategy_id: str = Field(min_length=1, max_length=80)
    writer_rules: str = Field(min_length=1, max_length=4000)
    # Compilation-level planning rules for the PLANNER prompts only. Empty means
    # "fall back to writer_rules" so hand-built strategies keep working; the
    # profile adapter always sets it, keeping planning noise out of the story
    # prompt (observed live: invariant scaffolding drowning per-story voice).
    planner_rules: str = Field(default="", max_length=6000)
    # Channel-scoped pre-return checklist for the PLANNER. Empty on the generic
    # default, so one channel's trade-reality policy cannot leak into another.
    plan_self_audit: str = Field(default="", max_length=4000)
    critic_rules: str = Field(min_length=1, max_length=4000)
    annotation_rules: str = Field(min_length=1, max_length=2000)
    approval_score: int = Field(default=82, ge=82, le=95)
    continuity_min: int = Field(default=22, ge=22, le=25)
    voice_min: int = Field(default=12, ge=12, le=20)
    dread_min: int = Field(default=12, ge=12, le=20)
    # Run 15 accepted a plan with NO escalation ladder: the fear gate skips
    # ladders under four rungs, so an empty one was never judged. Profiles
    # that plan by ladder turn this on; hand-built test strategies do not.
    require_ladder: bool = False
    plausible_response_min: int = Field(default=6, ge=6, le=10)
    structural_variety_min: int = Field(default=6, ge=6, le=10)
    originality_min: int = Field(default=6, ge=6, le=10)
    ending_min: int = Field(default=3, ge=3, le=5)
    numeric_anchor_limit: int = Field(default=6, ge=0, le=6)
    evidence_beat_limit: int = Field(default=1, ge=0, le=1)
    human_threat_fraction_min: float = Field(default=2 / 3, ge=2 / 3, le=1.0)
    evidence_free_story_min: int = Field(default=1, ge=1, le=5)
    # The corpus's most-watched story gives 8:45, 9:00 p.m., 2:01 a.m. and
    # 11:30 in one account; exact hours are how these narrators sound true.
    precise_clock_limit: int = Field(default=4, ge=0, le=4)
    selector_confidence_min: float = Field(default=0.65, ge=0.5, le=1.0)
    max_plan_attempts: int = Field(default=3, ge=2, le=4)
    max_plan_repairs: int = Field(default=2, ge=0, le=3)
    # Layered, channel-scoped release gates. Defaults keep the generic engine
    # behaviour so one channel's editorial policy cannot leak into another.
    require_distinct_mechanisms: bool = True
    topic_alignment_gate: bool = False
    safety_response_gate: bool = False
    plan_fact_fidelity_gate: bool = False
    forbidden_ending_gate: bool = False
    release_challenger_required: bool = False
    promote_impossibility_to_major: bool = True
    # Cross-story surface-texture gate: catches sentence-level tics the typed
    # mechanism axes cannot see. Opt-in so it never touches a channel that has
    # not tuned its denylist.
    stylometric_texture_gate: bool = False
    # Premise-level freshness: every story must name what makes it unlike its
    # genre default before prose exists. Opt-in for the same reason.
    premise_freshness_gate: bool = False

    @classmethod
    def from_quality_profile(cls, profile) -> "NamedChannelStrategy":
        """Adapt the config-owned immutable profile to the runtime gate contract."""
        ratio = float(profile.dimension_floor_ratio)
        writer_sections = (
            *profile.voice_rules,
            *profile.dread_rules,
            *profile.ending_rules,
            *(f"Avoid: {item}" for item in profile.avoid_tropes),
        )
        # Planning rules are planner-side only: compilation-level constraints in
        # the story prompt are attention noise the writer cannot act on.
        planner_sections = (*profile.planning_rules, *writer_sections)
        # THE STANCE GOES TO EVERY ROLE THAT SHAPES THE STORY. channel_promise
        # used to reach only the critic, so the planner invented premises and the
        # writer drafted prose without ever being told where this channel
        # stands between "this really happened" and "this is made up". The
        # promise is now the first line of the planner's and writer's rules as
        # well — it is the frame everything else hangs on.
        stance = profile.channel_promise.strip()
        return cls(
            strategy_id=profile.profile_id,
            require_ladder=True,
            writer_rules=stance + "\n" + "\n".join(f"- {item}" for item in writer_sections),
            planner_rules=stance + "\n" + "\n".join(f"- {item}" for item in planner_sections),
            plan_self_audit="\n".join(
                f"- {item}" for item in profile.plan_self_audit_rules
            ),
            # voice_rules INCLUDED: the critic scores distinct_authentic_voices
            # /20 and previously never received a single voice criterion.
            critic_rules=(
                profile.channel_promise
                + "\n"
                + "\n".join(f"- {item}" for item in (
                    *profile.voice_rules, *profile.dread_rules, *profile.ending_rules
                ))
            ),
            annotation_rules=(
                "Narration is immutable. Production metadata must remain literal, plausible, "
                "and must not add story facts."
            ),
            approval_score=profile.editorial_floor,
            continuity_min=profile.continuity_floor,
            voice_min=math.ceil(20 * ratio),
            dread_min=math.ceil(20 * ratio),
            plausible_response_min=math.ceil(10 * ratio),
            structural_variety_min=math.ceil(10 * ratio),
            originality_min=math.ceil(10 * ratio),
            ending_min=math.ceil(5 * ratio),
            numeric_anchor_limit=profile.maximum_numeric_anchors,
            evidence_beat_limit=profile.maximum_evidence_beats_per_story,
            human_threat_fraction_min=profile.minimum_human_threat_fraction,
            evidence_free_story_min=profile.minimum_evidence_free_stories,
            precise_clock_limit=profile.maximum_precise_clock_times,
            max_plan_attempts=profile.maximum_plan_attempts,
            max_plan_repairs=profile.maximum_plan_repairs,
            require_distinct_mechanisms=profile.require_distinct_mechanisms,
            topic_alignment_gate=profile.topic_alignment_gate,
            safety_response_gate=profile.safety_response_gate,
            plan_fact_fidelity_gate=profile.plan_fact_fidelity_gate,
            forbidden_ending_gate=profile.forbidden_ending_gate,
            release_challenger_required=profile.release_challenger_required,
            promote_impossibility_to_major=profile.promote_impossibility_to_major,
            stylometric_texture_gate=getattr(
                profile, "stylometric_texture_gate", False
            ),
            premise_freshness_gate=getattr(
                profile, "premise_freshness_gate", False
            ),
        )


class ChannelStrategyRegistry:
    """Small explicit registry; no mutable global profile inheritance."""

    def __init__(self, strategies: list[NamedChannelStrategy]) -> None:
        self._items: dict[str, NamedChannelStrategy] = {}
        for strategy in strategies:
            if strategy.strategy_id in self._items:
                raise ValueError(f"Duplicate channel strategy: {strategy.strategy_id}")
            self._items[strategy.strategy_id] = strategy

    def require(self, strategy_id: str) -> NamedChannelStrategy:
        try:
            # Models are frozen; a deep copy also prevents identity-based accidental sharing.
            return self._items[strategy_id].model_copy(deep=True)
        except KeyError as exc:
            raise ValueError(f"Unknown channel strategy: {strategy_id}") from exc


_LEDGER_PREFIXES = (
    "hook_timeline:",
    "people_objects:",
    "locations_exits:",
    "props_threat_position:",
    "response_escape:",
)

# Typed semantic mechanisms. Prose fields ("a silent man blocks her shortcut" vs
# "a figure suddenly stands in her path") normalize to different strings while
# describing the same beat, so literal diversity checks pass compilations that a
# viewer experiences as one story told three times. These closed vocabularies make
# "materially the same concept" a machine-checkable property instead of a regex
# guess over prose, and they are what the freshness fingerprint is computed from.
ThreatMechanism = Literal[
    "blocks_path", "pursues", "intrudes_space", "lures_or_deceives",
    "traps_or_confines", "watches_without_approach", "ambush_reveal",
    "environmental_anomaly",
]
ProgressionMechanism = Literal[
    "silent_stillness", "steady_approach", "sudden_rush", "repeat_sightings",
    "escalating_contact", "discovery_of_evidence", "exits_close_one_by_one",
    "impersonation_or_mimicry",
]
EscapeMechanism = Literal[
    "flee_to_occupied_place", "vehicle_escape", "barricade_in_place",
    "physical_confrontation", "call_for_help", "evade_by_route_knowledge",
    "third_party_intervenes", "climb_or_vault_barrier",
    "threat_withdraws_uncontested",
]
# Who/what the threat IS, orthogonal to how it acts. Added because 8 of 9
# released/near-released stories converged on one archetype (a silent lone
# stranger) that the per-video mechanism axes could not see.
ThreatIdentity = Literal[
    "lone_stranger", "known_regular", "group", "unseen_ambiguous",
    "vehicle_mediated",
]
AftermathMechanism = Literal[
    "no_explanation_offered", "authority_response", "witness_corroboration",
    "physical_trace_found", "recurrence_later", "identity_partially_learned",
    "routine_permanently_changed", "told_no_one",
]
SafetyObligation = Literal[
    "authorities_contacted", "trusted_adult_or_witness",
    "concrete_reason_omitted", "not_applicable",
]

_MECHANISM_AXES = (
    "threat_mechanism", "progression_mechanism",
    "escape_mechanism", "aftermath_mechanism",
    "threat_identity",
)


class NarrativeStoryPlan(_Model):
    story_id: str
    title: str
    narrator_profile: str
    setting: str
    # The only ordinary setup fact that must be spoken on the page before danger.
    # setting/continuity_ledger stay private continuity constraints, never
    # exposition obligations.
    setup_requirement: str
    threat: str
    threat_type: Literal["human", "ambiguous"]
    escape_action: str
    ending_shape: str
    evidence_allowance: Literal[
        "none", "camera", "official", "physical", "witness", "recurrence"
    ] = "none"
    voice_rules: str
    # A 2-3 sentence sample paragraph in the narrator's exact voice: the writer
    # CONTINUES this demonstrated voice instead of adopting adjectives (measured
    # live: three narrators collapsing into one register under ~700 words of
    # invariant scaffolding). Optional so pre-seed plans keep validating; when
    # present it is deterministically gated in validate_plan_preflight.
    voice_seed: str = Field(default="")
    # HOW MUCH ROOM THIS PREMISE NEEDS, decided by the planner that invented it.
    # The compilation budget used to be divided equally and enforced at ±15%,
    # so three stories were required to come out the same size whatever they
    # were about. A premise that needs a long, patient setup to pay off cannot
    # get it in an equal third, and a tight one gets padded to fill its share.
    # 0 means unassigned: older plans and pre-seeded fixtures fall back to the
    # equal split.
    target_words: int = Field(default=0, ge=0, le=6000)
    # HOW THE NIGHT GETS WORSE, in stages. The plan used to carry exactly one
    # "and then": setup -> threat -> escape -> ending, which is a single scene.
    # Measured across the twelve highest-viewed competitor stories, the median
    # account turns TWENTY-ONE times, the first turn landing by 5% and the last
    # past 50% — three days in the woods, not thirty seconds at a gate. With no
    # field for the middle, every premise collapsed to its scariest sentence
    # ("he knew my plate number") and the auditor filed it as stock, because a
    # single-moment premise has nowhere to be anything else.
    #
    # Each rung is one concrete change the narrator can perceive, in order,
    # each worse than the last and none explaining the one before. Empty on
    # older plans and fixtures; gated when present.
    escalation_ladder: list[str] = Field(default_factory=list, max_length=8)
    # WHAT STAYS. Read in the corpus's most-watched stories, every one:
    # a fact learned too late ('I likely looked right at this guy ... and
    # didn't even know it'; 'they were both my items'); the exit gone ('no
    # phone in the house', 'seventy feet up, the only way down blocked');
    # the narrator inferring the threat's mind ('maybe they wanted me to
    # STAY inside'); and one thing never explained, said last ('maybe it's
    # in my head, or maybe it isn't'). Empty on legacy plans; required by
    # ladder-planning profiles.
    already_line: str = ""
    no_way_out: str = ""
    threat_mind: str = ""
    remainder: str = ""
    continuity_ledger: list[str] = Field(min_length=5, max_length=5)

    # Typed concept axes; see _MECHANISM_AXES.
    threat_mechanism: ThreatMechanism
    progression_mechanism: ProgressionMechanism
    escape_mechanism: EscapeMechanism
    aftermath_mechanism: AftermathMechanism
    threat_identity: ThreatIdentity
    # How this story concretely delivers the compilation topic's subject. Checked
    # against the topic at plan time and against the narration at release time.
    topic_promise: str = ""
    # One clause naming what makes THIS premise unlike its genre default. The
    # anti-trope machinery only ever rationed the ambiguous/watcher slot, so
    # human-threat premises (tailgating truck, demand at the van window, creepy
    # passenger) reached prose as genre defaults and the critic scored the
    # compilation originality 6/10 — one point under the release floor — on three
    # consecutive fresh topics (2026-07-20 batch). Originality is holistic and
    # therefore unrepairable after the fact, so it has to be contracted here,
    # before anyone writes a word.
    distinguishing_turn: str = ""
    narrator_age_band: Literal["minor", "adult"] = "adult"
    narrator_age_years: int | None = Field(default=None, ge=5, le=110)
    safety_obligation: SafetyObligation = "not_applicable"
    safety_omission_reason: str = ""

    @field_validator(
        "topic_promise", "safety_omission_reason", "voice_seed",
        "distinguishing_turn", mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value

    @model_validator(mode="after")
    def _minor_narrators_declare_an_age(self):
        if self.narrator_age_band == "minor" and self.narrator_age_years is None:
            raise ValueError("a minor narrator must declare narrator_age_years")
        if (
            self.narrator_age_years is not None
            and (self.narrator_age_years < 18) != (self.narrator_age_band == "minor")
        ):
            raise ValueError("narrator_age_band must agree with narrator_age_years")
        return self

    @field_validator("voice_rules", mode="before")
    @classmethod
    def _accept_listed_voice_rules(cls, value):
        """A list of markers is the same thing as a line of them.

        The prompt asks for "voice_rules LISTING 2-3 measurable idiolect
        markers" and shows three comma-separated examples, so the planner
        returns a JSON array — reasonably. The field was typed `str`, so the
        whole plan was rejected before anything read it, the concept was
        thrown away, and the contract retry regenerated it as a string. Half of
        every planner call on this channel was being spent on that disagreement
        (planner=4 / schema_retry=4 in the counters for weeks).
        Nothing downstream cares: the only consumer joins these fields into one
        block of text anyway. So accept both and stop paying for the argument.
        """
        if isinstance(value, (list, tuple)):
            return "; ".join(str(item).strip() for item in value if str(item).strip())
        return value

    @field_validator("continuity_ledger")
    @classmethod
    def _validate_ledger_contract(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value]
        if len(cleaned) != len(_LEDGER_PREFIXES):
            return cleaned
        if len({_normal(item) for item in cleaned}) != len(cleaned):
            raise ValueError("continuity ledger entries must be unique")
        for item, prefix in zip(cleaned, _LEDGER_PREFIXES, strict=True):
            if not item.lower().startswith(prefix):
                raise ValueError(f"continuity ledger entry must start with {prefix}")
            suffix = item[len(prefix):].strip()
            if len(_words(suffix)) < 3:
                raise ValueError("continuity ledger category requires at least three fact words")
            if len(_words(item)) > 24:
                raise ValueError("continuity ledger entries must be concise (<=24 words)")
        return cleaned


class CompilationPlan(_Model):
    topic: str
    cold_open: str
    target_word_count: int
    stories: list[NarrativeStoryPlan]


class StoryOutput(_Model):
    title: str
    hook_candidates: list[str] = Field(min_length=1, max_length=3)
    narration: str


class StoryDraft(StoryOutput):
    story_id: str


_REQUIRED_BEAT_IDS = (
    "ordinary_setup",
    "threat_confirmation",
    "decision_action",
    "completed_escape",
    "completed_ending",
)


class StoryBeatCheck(_StrictModel):
    beat_id: Literal[
        "ordinary_setup", "threat_confirmation", "decision_action",
        "completed_escape", "completed_ending",
    ]
    locked_requirement: str
    status: Literal["complete", "partial", "missing", "contradicted"]
    evidence_quote: str = ""
    anchor_quote: str = ""
    explanation: str = Field(default="", max_length=1200)

    @field_validator("anchor_quote", "explanation", mode="before")
    @classmethod
    def normalize_optional_anchor(cls, value: object) -> object:
        # Structured providers sometimes emit JSON null for an optional repair
        # anchor. Complete/contradicted beats are still grounded by the strict
        # evidence_quote checks below; omission/partial beats still require a
        # non-empty exact anchor in validate_story_compliance().
        return "" if value is None else value


class StoryComplianceReview(_StrictModel):
    """Narrow mechanical audit; approval is derived locally, never self-reported."""

    story_id: str
    plan_fingerprint: str
    narration_sha256: str
    beats: list[StoryBeatCheck] = Field(min_length=5, max_length=5)
    plan_facts_status: Literal[
        "preserved", "contradicted", "not_demonstrated"
    ] = "not_demonstrated"
    plan_facts_quote: str = ""
    plan_facts_explanation: str = Field(default="", max_length=1200)
    evidence_budget_status: Literal[
        "preserved", "violated", "unclear"
    ] = "unclear"
    evidence_quote: str = ""
    evidence_explanation: str = Field(default="", max_length=1200)

    @field_validator(
        "plan_facts_quote", "plan_facts_explanation",
        "evidence_quote", "evidence_explanation", mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        # Providers emit JSON null for text that is only required on a failing
        # verdict; a contradicted/violated status with an empty quote is still
        # rejected semantically by validate_story_compliance().
        return "" if value is None else value


class PlanIssue(_Model):
    """One real-world plausibility objection to a LOCKED plan, before prose."""

    story_id: str = ""
    category: Literal[
        "physical", "professional", "geography",
        "human_behavior", "prop_staging", "trope",
        # The typed axes an auditor can falsify but a deterministic check cannot:
        # whether a declared mechanism label honestly describes the prose fields,
        # and whether a story actually delivers the compilation's subject.
        "mechanism_mismatch", "topic_alignment",
        # Found by an operator read-through of the first plan to pass every
        # gate: a threat that knew a private fact with no moment it could have
        # learned it, and a voice rule that forbade the number the premise
        # hinged on. Neither is a regex.
        "knowledge_path", "voice_vs_premise",
        # A deterministic gate error handed to repair as an issue. Its own
        # category, so clearing it is visible as progress against whatever
        # the re-audit raises next.
        "gate",
        # Codex round 2: the cold open gave away the window-and-nickname beat.
        "cold_open",
        # What stays: the already_line must be learned late and re-read the night.
        "haunting",
    ] = "physical"
    severity: Literal["critical", "major", "minor"]
    problem: str
    plan_fix: str = ""
    # An objection to a plan must point at the plan. Live 2026-07-17 13:34: the
    # auditor blocked a whole concept on "valet service shuts down well before
    # midnight" — a claim about one unnamed hospital's staffing that the plan never
    # made and the auditor cannot know.
    evidence_quote: str = ""
    # universal: a physical law, a broadly established trade constraint, or a
    # contradiction inside the plan itself. site_specific: depends on one site's
    # schedule, policy, or staffing that the plan does not state — real uncertainty,
    # worth saying, never worth vetoing a concept over.
    knowledge_scope: Literal["universal", "site_specific"] = "universal"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("story_id", "plan_fix", "evidence_quote", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("knowledge_scope", mode="before")
    @classmethod
    def normalize_scope(cls, value: object) -> object:
        # Omitted scope defaults to universal: a blocking issue that forgot to
        # classify itself still blocks. The demotion below only fires when the
        # auditor explicitly admits the claim is site-dependent.
        return "universal" if value in (None, "") else value


class PlanPlausibilityReview(_StrictModel):
    issues: list[PlanIssue] = Field(default_factory=list)
    summary: str = ""

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("issues", mode="before")
    @classmethod
    def normalize_optional_list(cls, value: object) -> object:
        return [] if value is None else value


def _format_plan_issue(issue: PlanIssue) -> str:
    return (
        f"[plan_audit/{issue.category}] {issue.story_id or 'compilation'}: {issue.problem}"
        + (f" FIX: {issue.plan_fix}" if issue.plan_fix else "")
    )


def plan_story_text(item: NarrativeStoryPlan) -> str:
    """The plan's own words for one story — what an objection must quote."""
    # THE LADDER IS PART OF THE PLAN'S OWN WORDS. Every auditor objection must
    # quote a unique substring of this text; an objection quoting a rung that
    # was not listed here failed the quote contract, voided the audit verdict,
    # and cost one of two attempts — i.e. the auditor was penalised for
    # reading the one field that makes a premise more than a single scene.
    return "\n".join((
        item.title, item.narrator_profile, item.setting, item.setup_requirement,
        item.threat, item.escape_action, item.ending_shape, item.voice_rules,
        item.topic_promise, item.distinguishing_turn, item.safety_omission_reason,
        *item.continuity_ledger,
        *(getattr(item, "escalation_ladder", None) or []),
        getattr(item, "already_line", "") or "", getattr(item, "no_way_out", "") or "",
        getattr(item, "threat_mind", "") or "", getattr(item, "remainder", "") or "",
    ))


def validate_plan_audit_issues(
    review: PlanPlausibilityReview, plan: CompilationPlan
) -> list[str]:
    """Every blocking objection must quote the locked plan text it challenges.

    The story audits have required exact grounded quotes from the start; the plan
    audit did not, and a whole concept died on an unquotable claim about one
    hospital's overnight staffing. An objection that cannot point at the words it
    objects to is not an objection a planner can act on.
    """
    by_id = {item.story_id: item for item in plan.stories}
    errors: list[str] = []
    for index, issue in enumerate(review.issues):
        if issue.severity == "minor":
            continue
        label = issue.story_id or f"issue_{index + 1}"
        if issue.story_id not in by_id:
            errors.append(
                f"{label}: a blocking plan issue must name one of {sorted(by_id)}; "
                f"received {issue.story_id!r}"
            )
            continue
        if not issue.evidence_quote:
            errors.append(
                f"{label}: {issue.severity} requires an exact evidence_quote copied "
                "from the plan field it challenges"
            )
            continue
        text = plan_story_text(by_id[issue.story_id])
        # A cold_open objection quotes the compilation's cold open, which is
        # not story text. Live: the first cold_open issue the auditor raised
        # failed this check and the whole audit was thrown away as unusable.
        if issue.category == "cold_open":
            text = text + "\n" + (plan.cold_open or "")
        if text.count(issue.evidence_quote) != 1:
            errors.append(
                f"{label}: evidence_quote must be one exact, unique substring of that "
                f"story's plan text; {issue.evidence_quote[:60]!r} is not"
            )
    return errors


def calibrate_plan_issues(review: PlanPlausibilityReview) -> PlanPlausibilityReview:
    """Demote objections the auditor admits it cannot know.

    A reviewer reading a premise cannot know whether one unnamed hospital staffs a
    valet booth at 1:25 a.m. That is worth saying and is not worth killing a
    concept: absent a plan that states the hours, it is site-specific uncertainty,
    not an established trade constraint. Physics, hardware, geometry, and
    contradictions inside the plan are unaffected — those the auditor CAN know.
    """
    calibrated: list[PlanIssue] = []
    for issue in review.issues:
        if issue.knowledge_scope == "site_specific" and issue.severity in {
            "critical", "major"
        }:
            issue = issue.model_copy(update={
                "severity": "minor",
                "problem": (
                    "[demoted: the auditor classed this as site-specific, and the plan "
                    "states no policy that contradicts it] " + issue.problem
                ),
            })
        calibrated.append(issue)
    return review.model_copy(update={"issues": calibrated})


def plan_audit_blockers(review: PlanPlausibilityReview) -> list[str]:
    """Derive blocking plan defects locally; the auditor never self-approves.

    Every critical or major blocks. The previous rule discarded a lone major and
    demanded two on one story, which is how the 2026-07-17 compilation reached
    production_ready carrying a premise (a minor's abduction attempt with no adult
    response) that a knowledgeable viewer rejects on sight. A plan is cheap to
    replan and ruinous to shoot: there is no reason to spend a writer call on a
    premise an auditor already objected to.
    """
    return [
        _format_plan_issue(issue) for issue in review.issues
        if issue.severity in {"critical", "major"}
    ]


class PlanAuditResult(_StrictModel):
    """Typed plan verdict. 'No blockers' and 'no answer' are not the same fact.

    primary_healthy exists because a verdict is not the only thing this call
    produces. It is also the run's only pre-writer evidence about whether the
    provider that must score, compliance-check and final-review the prose is alive
    at all. Live 2026-07-17 13:34: all ten DeepSeek primary audits failed, Claude
    escalation answered every time, and the audit reported a clean verdict — so a
    passing plan would have bought three Opus drafts before anyone discovered the
    judges were unreachable. Escalation rescues the VERDICT; it must not launder
    the HEALTH.
    """

    status: Literal["valid", "blocked", "infra_failed", "contract_failed"]
    blockers: list[str] = Field(default_factory=list)
    issues: list[PlanIssue] = Field(default_factory=list)
    summary: str = ""
    attempts: int = 0
    escalated: bool = False
    provider_errors: list[str] = Field(default_factory=list)
    primary_healthy: bool = True
    primary_provider_errors: list[str] = Field(default_factory=list)
    verdict_source: Literal["primary", "escalation", "none"] = "primary"
    contract_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_matches_evidence(self):
        if self.status == "blocked" and not self.blockers:
            raise ValueError("a blocked plan audit must name its blockers")
        if self.status == "valid" and self.blockers:
            raise ValueError("a valid plan audit cannot carry blockers")
        if self.status == "infra_failed" and not self.provider_errors:
            raise ValueError("an infra_failed plan audit must record the provider errors")
        if self.status == "contract_failed" and not self.contract_errors:
            raise ValueError("a contract_failed plan audit must record the contract errors")
        if not self.primary_healthy and not self.primary_provider_errors:
            raise ValueError("an unhealthy primary auditor must record why")
        return self


def evaluate_plan_audit(
    review: PlanPlausibilityReview,
    plan: CompilationPlan | None = None,
    *,
    attempts: int = 1,
    escalated: bool = False,
    primary_healthy: bool = True,
    primary_provider_errors: list[str] | None = None,
    verdict_source: str = "primary",
) -> PlanAuditResult:
    """Grade one review into a typed verdict, preserving every issue as evidence.

    Grounding: an issue naming a story that does not exist in the plan is still
    kept and still blocks, but is re-attributed to the compilation so a downstream
    replan brief is not addressed to a phantom story_id. Objections the auditor
    itself classed as site-specific are demoted before blockers are derived.
    """
    calibrated = calibrate_plan_issues(review)
    known = {item.story_id for item in plan.stories} if plan is not None else None
    grounded: list[PlanIssue] = []
    for issue in calibrated.issues:
        if known is not None and issue.story_id and issue.story_id not in known:
            issue = issue.model_copy(update={
                "story_id": "",
                "problem": f"{issue.problem} (auditor named unknown story {issue.story_id})",
            })
        grounded.append(issue)
    blockers = plan_audit_blockers(PlanPlausibilityReview(issues=grounded))
    return PlanAuditResult(
        status="blocked" if blockers else "valid",
        blockers=blockers,
        issues=grounded,
        summary=review.summary,
        attempts=attempts,
        escalated=escalated,
        primary_healthy=primary_healthy,
        primary_provider_errors=list(primary_provider_errors or []),
        verdict_source=verdict_source,
    )


_SECRET_RE = re.compile(
    r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{8,}|"
    r"\b(?:api[_-]?key|authorization|bearer|token|secret|password)\b\s*[:=]\s*\S+",
    re.I,
)


def _redact(text: str, limit: int = 1200) -> str:
    """Provider and validation text is evidence; it is not a place for credentials."""
    return _SECRET_RE.sub("[redacted]", str(text or ""))[:limit]


class PlanRejection(_StrictModel):
    """One rejected plan and the exact reasons THAT plan was rejected.

    The 13:34 failure audit persisted five rejected plans and a single trailing
    blocker list, so four of the five could not be matched to why they died and the
    sixth (a schema failure) left no trace at all. A rejected premise is the most
    useful thing a failed run produces; it is worth keeping properly.
    """

    attempt: int
    planner_attempt: int
    stage: Literal["schema", "preflight", "freshness", "audit", "repair"]
    errors: list[str] = Field(default_factory=list)
    plan: CompilationPlan | None = None
    plan_fingerprint: str = ""
    material_digest: str = ""
    audit: PlanAuditResult | None = None
    call_counts: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    # Redacted validation/provider text for stages that never produced a plan object.
    raw_evidence: str = ""


class NarrativeRunAborted(ValueError):
    """Base for pre-writer aborts: the run stops before it spends on prose.

    Deliberately a ValueError: the pre-writer abort this replaced already raised
    one, and callers (including the outer retry) catch it the same way.
    """


class NarrativeRunEvidence(_StrictModel):
    """What a whole outer run spent, whether or not it produced anything.

    Accounting used to ride on the returned result, so the one case that spends
    the most and delivers the least — every attempt aborting — raised the raw
    provider error and reported nothing at all. A failed run is exactly when an
    operator needs the bill.
    """

    attempts_executed: int = 0
    attempt_summaries: list["AttemptSummary"] = Field(default_factory=list)
    aggregate_call_counts: dict[str, int] = Field(default_factory=dict)
    aggregate_cost_usd: float = 0.0
    aggregate_notional_cost_usd: float = 0.0
    aggregate_latency_s: float = 0.0


class NarrativeRunExhausted(NarrativeRunAborted):
    """Every outer attempt failed and no candidate survived.

    Carries the full bill and every rejected premise. Chains the underlying error
    as __cause__ so diagnosis is unchanged, and stays a ValueError so callers that
    caught the old raw failure still catch this.
    """

    def __init__(
        self,
        message: str,
        evidence: NarrativeRunEvidence,
        rejected_plans: list[CompilationPlan] | None = None,
        rejections: list[PlanRejection] | None = None,
    ) -> None:
        super().__init__(message)
        self.evidence = evidence
        self.rejected_plans = rejected_plans or []
        # One record per rejected plan, in order, each carrying its own reasons.
        self.rejections = rejections or []


class QualityPathUnavailable(NarrativeRunAborted):
    """The critique/compliance path required by the channel is not configured."""


class QualityPathUnhealthy(NarrativeRunAborted):
    """A mandatory post-writer judge runs on a provider account that is already
    failing this run, and no independent configured fallback can take its place.

    The plan audit is the run's live probe of the critic path. When escalation
    answers the audit but the primary provider is dead, the verdict is safe and the
    path is not: writing three drafts would only postpone the discovery until after
    they are paid for.
    """

    def __init__(
        self,
        message: str,
        audit: PlanAuditResult,
        rejections: list[PlanRejection] | None = None,
        plan: CompilationPlan | None = None,
    ) -> None:
        super().__init__(message)
        self.audit = audit
        # Whatever was learned before the abort is still worth keeping.
        self.rejections = rejections or []
        self.plan = plan


class PlanAuditUnavailable(NarrativeRunAborted):
    """The plan auditor never returned a usable verdict. Silence is not approval."""

    def __init__(self, message: str, audit: PlanAuditResult) -> None:
        super().__init__(message)
        self.audit = audit


class PlannerUnavailable(NarrativeRunAborted):
    """The planner never returned a parseable plan.

    Distinct from PlanNotPlausible: no premise was ever judged, so nothing about
    the concept is known. Reporting a provider outage as "plan_blocked" would put
    an infrastructure failure in the same bucket as a rejected idea.
    """

    def __init__(self, message: str, rejections: list[PlanRejection] | None = None) -> None:
        super().__init__(message)
        self.rejections = rejections or []


class PlanOnlyComplete(NarrativeRunAborted):
    """A plan survived preflight and the audit, and the caller asked to stop.

    Not a failure. Raised only under OMNICAST_NARRATIVE_PLAN_ONLY so a premise
    can be judged for one planner call and one audit instead of a full
    twenty-five-minute run — the difference between seeing three premises in a
    quota window and seeing thirty.
    """

    def __init__(self, plan: "CompilationPlan", audit: "PlanAuditResult") -> None:
        super().__init__("plan accepted; stopping before story drafting "
                         "(OMNICAST_NARRATIVE_PLAN_ONLY)")
        self.plan = plan
        self.audit = audit


class PlanNotPlausible(NarrativeRunAborted):
    """Every bounded planner attempt produced a plan the audit blocked."""

    def __init__(
        self,
        message: str,
        audit: PlanAuditResult,
        rejected_plans: list[CompilationPlan] | None = None,
        rejection_reasons: list[list[str]] | None = None,
        rejections: list[PlanRejection] | None = None,
    ) -> None:
        super().__init__(message)
        self.audit = audit
        # rejections is the typed, one-to-one record; rejected_plans/rejection_reasons
        # remain as parallel views for callers that already read them.
        self.rejections = rejections or []
        self.rejected_plans = rejected_plans or []
        self.rejection_reasons = rejection_reasons or []


def story_mechanism_signature(plan: NarrativeStoryPlan) -> tuple[str, ...]:
    """The typed concept of one story, independent of how its prose is worded."""
    return tuple(str(getattr(plan, axis)) for axis in _MECHANISM_AXES)


def plan_concept_fingerprint(plan: CompilationPlan) -> str:
    """A wording-independent identity for a compilation concept.

    Two plans with the same multiset of mechanism signatures tell the same three
    stories no matter how the titles and threat sentences are re-phrased, so this
    is what an outer retry must be forbidden from repeating. Sorted, because the
    running order is not part of the concept.
    """
    payload = json.dumps(
        sorted(story_mechanism_signature(item) for item in plan.stories),
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def shared_story_concepts(left: CompilationPlan, right: CompilationPlan) -> int:
    """How many stories the two plans tell with an identical typed concept."""
    remaining = [story_mechanism_signature(item) for item in right.stories]
    shared = 0
    for signature in (story_mechanism_signature(item) for item in left.stories):
        if signature in remaining:
            remaining.remove(signature)
            shared += 1
    return shared


def plans_are_materially_equivalent(left: CompilationPlan, right: CompilationPlan) -> bool:
    """A 'fresh concept' that reuses most of its beats is not a fresh concept.

    Identical fingerprints are the obvious case. A majority of stories reusing the
    same typed concept is the interesting one: the planner reshuffles the order,
    renames the narrator, and returns the same compilation.
    """
    if plan_concept_fingerprint(left) == plan_concept_fingerprint(right):
        return True
    span = min(len(left.stories), len(right.stories))
    if span == 0:
        return False
    return shared_story_concepts(left, right) >= max(2, math.ceil(span * 0.6))


class PlanRepairOutput(_Model):
    """Replacement plans for ONLY the stories the audit blocked."""

    stories: list[NarrativeStoryPlan] = Field(min_length=1, max_length=5)
    # Only when an objection is category cold_open: a replacement line that
    # sells the night, not the payoff. None otherwise.
    cold_open: str | None = None


class ChallengeVerdict(_StrictModel):
    """One typed adversarial finding about a compilation that is about to ship."""

    axis: Literal[
        "physical_possibility", "timeline_consistency", "semantic_repetition",
        "topic_alignment", "safety_response", "plan_fidelity", "forbidden_ending",
        "self_reassurance",
    ]
    verdict: Literal["pass", "fail"]
    story_id: str = ""
    evidence_quote: str = ""
    explanation: str = Field(default="", max_length=1200)

    @field_validator("story_id", "evidence_quote", "explanation", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value


class ReleaseChallenge(_StrictModel):
    verdicts: list[ChallengeVerdict] = Field(default_factory=list)
    summary: str = ""

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("verdicts", mode="before")
    @classmethod
    def normalize_optional_list(cls, value: object) -> object:
        return [] if value is None else value


class ReleaseChallengeResult(_StrictModel):
    """Fail-closed by construction: only 'passed' clears the gate.

    'not_independent' is its own status because it is its own fact: the challenger
    answered, and its answer carries no information a release can rest on. It is
    not a contract failure (nothing was malformed) and it is emphatically not a
    pass.
    """

    status: Literal[
        "passed", "failed", "contract_failed", "not_configured",
        "not_independent", "not_required",
    ]
    verdicts: list[ChallengeVerdict] = Field(default_factory=list)
    summary: str = ""
    attempts: int = 0
    errors: list[str] = Field(default_factory=list)
    challenger_is_independent: bool = False

    @model_validator(mode="after")
    def _a_pass_requires_independence(self):
        # The invariant that makes the status trustworthy at every call site,
        # rather than something each caller has to remember to check alongside it.
        if self.status == "passed" and not self.challenger_is_independent:
            raise ValueError(
                "a release challenge cannot pass on a challenger that is not "
                "provider-independent of the critic it exists to challenge"
            )
        return self


class StoryTextEdit(_Model):
    find: str
    replace: str


class StoryPatchOutput(_Model):
    edits: list[StoryTextEdit] = Field(min_length=1, max_length=8)


class StoryPatchCandidate(StoryPatchOutput):
    candidate_id: Literal["candidate_1", "candidate_2"]


class StoryPatchCandidateSet(_Model):
    candidates: list[StoryPatchCandidate] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _unique_candidate_ids(self):
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Patch candidate IDs must be unique")
        return self


class BlindPatchSelection(_StrictModel):
    selected_label: str
    confidence: float = Field(ge=0.0, le=1.0)
    preserves_locked_plan: bool
    resolves_target_issues: bool
    introduced_issues: list[str] = Field(default_factory=list)
    voice_regression: bool = False
    dread_regression: bool = False
    ending_regression: bool = False
    rationale: str = ""

    @field_validator("rationale", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("introduced_issues", mode="before")
    @classmethod
    def normalize_optional_list(cls, value: object) -> object:
        return [] if value is None else value


class PatchDecision(_StrictModel):
    story_id: str
    selected: Literal["baseline", "candidate_1", "candidate_2", "full_rewrite"]
    selected_candidate_id: str | None = None
    selector_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str


class GateFailure(_Model):
    code: str
    message: str
    story_ids: list[str] = Field(default_factory=list)


class GateReport(_Model):
    failures: list[GateFailure] = Field(default_factory=list)
    editorial_flags: list[GateFailure] = Field(default_factory=list)
    total_words: int = 0
    story_words: dict[str, int] = Field(default_factory=dict)

    @computed_field
    @property
    def passed(self) -> bool:
        return not self.failures


class StoryIssue(_Model):
    story_id: str
    severity: Literal["critical", "major", "minor"]
    problem: str
    repair_instruction: str
    issue_kind: Literal["contradiction", "omission", "style"] = "contradiction"
    evidence_quote: str = ""
    anchor_quote: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    viewer_impact: str = ""
    issue_id: str = ""
    # Set when a local calibration rule overrode the judge's own severity, so the
    # bounded disagreement re-read never asks the judge to withdraw our correction.
    promoted_from: str = ""

    @field_validator(
        "evidence_quote", "anchor_quote", "viewer_impact", "issue_id", "promoted_from",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value


class OriginalityVerdict(_StrictModel):
    originality: int = Field(ge=0, le=10)
    justification: str = ""

    @field_validator("justification", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value


class FinalCompilationReview(_StrictModel):
    approved: bool
    reviewed_story_ids: list[str] = Field(min_length=1, max_length=5)
    issues: list[StoryIssue] = Field(default_factory=list)
    summary: str = ""

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return "" if value is None else value


class NarrativeScorecard(_Model):
    continuity_believability: int = Field(ge=0, le=25)
    distinct_authentic_voices: int = Field(ge=0, le=20)
    dread_escalation: int = Field(ge=0, le=20)
    plausible_response: int = Field(ge=0, le=10)
    structural_variety: int = Field(ge=0, le=10)
    originality: int = Field(ge=0, le=10)
    ending_discipline: int = Field(ge=0, le=5)
    critical_issues: list[str] = Field(default_factory=list)
    story_issues: list[StoryIssue] = Field(default_factory=list)
    editorial_summary: str = ""

    @model_validator(mode="before")
    @classmethod
    def _clamp_weighted_dimensions(cls, value):
        """A judge cannot award more than the rubric weight for a dimension."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if data.get("editorial_summary") is None:
            data["editorial_summary"] = ""
        for field in ("critical_issues", "story_issues"):
            if data.get(field) is None:
                data[field] = []
        maxima = {
            "continuity_believability": 25,
            "distinct_authentic_voices": 20,
            "dread_escalation": 20,
            "plausible_response": 10,
            "structural_variety": 10,
            "originality": 10,
            "ending_discipline": 5,
        }
        for field, maximum in maxima.items():
            try:
                data[field] = max(0, min(int(data.get(field, 0)), maximum))
            except (TypeError, ValueError):
                data[field] = 0
        return data

    @computed_field
    @property
    def total_score(self) -> int:
        return (
            self.continuity_believability
            + self.distinct_authentic_voices
            + self.dread_escalation
            + self.plausible_response
            + self.structural_variety
            + self.originality
            + self.ending_discipline
        )


class BeatAnnotation(_StrictModel):
    beat_id: str
    visual_prompt: str
    sfx: str | None = None
    pace: Literal["slow", "normal", "fast"] = "normal"
    pause_after_ms: int = Field(default=0, ge=0, le=1500)
    emphasis: list[str] = Field(default_factory=list)


class StoryAnnotation(_StrictModel):
    story_id: str
    beats: list[BeatAnnotation]


class AttemptSummary(_StrictModel):
    """What one outer attempt actually cost, including the ones that died.

    The 2026-07-17 artifact reported attempt=2 with planner=1: the per-run counters
    reset on every attempt, so the selected attempt was billed as if the attempt
    before it had been free. Every field here is per-attempt; the result-level
    aggregate_* fields are their sum.
    """

    attempt: int
    outcome: Literal[
        "content_locked", "needs_edit", "aborted",
        "plan_blocked", "plan_audit_unavailable",
        "quality_path_unavailable", "quality_path_unhealthy",
    ]
    reason: str = ""
    call_counts: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0
    notional_cost_usd: float = 0.0
    latency_s: float = 0.0
    plan_fingerprint: str = ""
    plan: CompilationPlan | None = None
    total_score: int = 0
    gate_failures: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    # Every plan this attempt threw away, each with its own reasons.
    plan_rejections: list[PlanRejection] = Field(default_factory=list)
    plan_audit: PlanAuditResult | None = None


# AttemptSummary is only nameable here; the evidence model above forward-references it.
NarrativeRunEvidence.model_rebuild()


class NarrativePipelineResult(_Model):
    plan: CompilationPlan
    stories: list[StoryDraft]
    gate_report: GateReport
    scorecard: NarrativeScorecard
    attempt: int = 1
    attempts_executed: int = 1
    attempt_summaries: list[AttemptSummary] = Field(default_factory=list)
    aggregate_call_counts: dict[str, int] = Field(default_factory=dict)
    aggregate_cost_usd: float = 0.0
    # Subscription calls are not billed per token; this is what they WOULD have
    # cost on API pricing, kept apart so aggregate_cost_usd stays honest at zero.
    aggregate_notional_cost_usd: float = 0.0
    aggregate_latency_s: float = 0.0
    plan_audit: PlanAuditResult | None = None
    plan_audit_warnings: list[str] = Field(default_factory=list)
    # Resolved (provider, model) of every judge that actually ran this compilation.
    judge_identities: list[tuple] = Field(default_factory=list)
    # How this run was wired: "claude_only" while the DeepSeek quota is
    # exhausted, "deepseek_first" normally.
    judge_mode: str = "default"
    model_roles: dict[str, str] = Field(default_factory=dict)
    release_challenge: ReleaseChallengeResult | None = None
    content_locked: bool = False
    annotations: list[StoryAnnotation] = Field(default_factory=list)
    production_ready: bool = False
    repair_waves: int = 0
    draft: ScriptDraft | None = None
    critic_contract_valid: bool = True
    story_compliance_valid: bool = True
    story_compliance_reviews: list[StoryComplianceReview] = Field(default_factory=list)
    story_compliance_errors: dict[str, list[str]] = Field(default_factory=dict)
    final_editor_approved: bool = False
    locked_voiceover_sha256: str = ""
    patch_decisions: list[PatchDecision] = Field(default_factory=list)
    final_review: FinalCompilationReview | None = None
    release_tier: Literal[
        "needs_edit", "content_valid", "editorially_ready", "production_test_ready"
    ] = "needs_edit"
    quality_strategy: NamedChannelStrategy = Field(default_factory=lambda: NamedChannelStrategy(
        strategy_id="system_default", writer_rules="restrained narrative",
        critic_rules="skeptical content audit", annotation_rules="literal production metadata",
    ))
    call_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _release_invariants(self):
        expected_ids = [item.story_id for item in self.plan.stories]
        actual_ids = [item.story_id for item in self.story_compliance_reviews]
        compliance_bound = (
            actual_ids == expected_ids
            and len(self.stories) == len(self.plan.stories)
            and all(
                not validate_story_compliance(plan_item, story, review)
                for plan_item, story, review in zip(
                    self.plan.stories, self.stories,
                    self.story_compliance_reviews, strict=True
                )
            )
        )
        if self.content_locked:
            if not compliance_bound or not all(
                story_compliance_approved(item) for item in self.story_compliance_reviews
            ):
                raise ValueError("Content lock requires approved story compliance coverage")
        # Ordering is part of the contract: the checks that can name the exact
        # broken artifact (a drifted hash, a forged draft, uncovered beats) run
        # before the aggregate release-contract check, so a caller debugging a
        # tampered payload is told which byte is wrong rather than the catch-all
        # "violates the release contract".
        expected_hash = locked_voiceover_sha256(self.stories)
        if self.content_locked and self.locked_voiceover_sha256 != expected_hash:
            raise ValueError("Content lock requires the exact current voiceover SHA256")
        if self.production_ready and (not self.content_locked or self.draft is None):
            raise ValueError("Production release requires a locked content draft")
        if self.production_ready:
            if len(self.annotations) != len(self.stories):
                raise ValueError("Production release requires one annotation per story")
            annotation_map = {item.story_id: item for item in self.annotations}
            if set(annotation_map) != {item.story_id for item in self.stories}:
                raise ValueError("Production annotations do not cover the locked stories")
            if not all(
                _annotation_covers(annotation_map[story.story_id], _split_beats(story))
                for story in self.stories
            ):
                raise ValueError("Production annotation beat coverage is incomplete")
            expected_draft = _assemble(self.plan, self.stories, self.annotations)
            if self.draft.model_dump(mode="json") != expected_draft.model_dump(mode="json"):
                raise ValueError("Production draft does not exactly match locked narration")

        plan_audit_valid = self.plan_audit is not None and self.plan_audit.status == "valid"
        challenge_passed = self.release_challenge is not None and (
            self.release_challenge.status in {"passed", "not_required"}
        )
        if self.content_locked and not content_can_lock(
            self.scorecard,
            self.gate_report,
            self.quality_strategy,
            critic_contract_valid=self.critic_contract_valid,
            story_compliance_valid=self.story_compliance_valid,
            final_editor_approved=self.final_editor_approved,
            plan_audit_valid=plan_audit_valid,
            release_challenge_passed=challenge_passed,
        ):
            raise ValueError("Content lock violates score, gate, or editorial release contract")
        compliance_approved = (
            self.story_compliance_valid
            and compliance_bound
            and all(story_compliance_approved(item) for item in self.story_compliance_reviews)
        )
        objective_valid = (
            self.gate_report.passed
            and self.critic_contract_valid
            and compliance_approved
            and not self.scorecard.critical_issues
            and not any(
                item.severity in {"critical", "major"}
                for item in self.scorecard.story_issues
            )
        )
        expected_tier = (
            "production_test_ready" if self.production_ready
            else "editorially_ready" if self.content_locked
            else "content_valid" if objective_valid
            else "needs_edit"
        )
        if self.release_tier != expected_tier:
            raise ValueError(
                f"release_tier {self.release_tier} does not match derived {expected_tier}"
            )
        return self


_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_BANNED_RE = re.compile(
    r"\b(?:i told myself|i convinced myself|i reassured myself|"
    r"i (?:figure|figured) (?:it'?s|it was)(?: just| probably)?|"
    r"you tell yourself|i almost had myself convinced|telling myself)\b",
    re.IGNORECASE,
)
# EMPTY reassurance is the slop: the narrator waves the sign away with nothing.
# 'I told myself it was just a small company delivery' names an alternative
# and is the genre's denial-that-fails beat (Knock at the Door, twice).
_BANNED_EMPTY_RE = re.compile(
    r"\b(?:i told myself|i convinced myself|i reassured myself|telling myself|you tell yourself|"
    r"i (?:figure|figured))\b[^.;!?]{0,40}?\b(?:nothing|fine|okay|ok|all right|alright|"
    r"my imagination|imagining (?:it|things)|no big deal|nothing to worry about)\b",
    re.IGNORECASE,
)
_CTA_RE = re.compile(
    r"\b(?:subscribe|like and comment|hit the bell|this channel|in today'?s video|"
    r"our next story|dear viewers?|submitted to us|the following account)\b",
    re.IGNORECASE,
)
_PRECISE_TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[ap]m)?\b", re.I)
_NUMBER_RE = re.compile(r"\b\d+(?::\d+)?\b")
_NUMBER_SEQUENCE_RE = re.compile(r"\b\d+(?:\s*,\s*\d+){1,}\b")
_NUMBER_UNITS = {
    "zero": 0, "one": 1, "first": 1, "two": 2, "second": 2, "three": 3,
    "third": 3, "four": 4, "fourth": 4, "five": 5, "fifth": 5, "six": 6,
    "sixth": 6, "seven": 7, "seventh": 7, "eight": 8, "eighth": 8,
    "nine": 9, "ninth": 9, "ten": 10, "tenth": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_NUMBER_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_WORD_RE = re.compile(
    r"\b(?:" + "|".join((*_NUMBER_UNITS, *_NUMBER_TENS, "hundred", "thousand"))
    + r")(?:[ -]+(?:and[ -]+)?(?:"
    + "|".join((*_NUMBER_UNITS, *_NUMBER_TENS, "hundred", "thousand"))
    + r"))*\b",
    re.I,
)
_NUMBER_CONTEXT_AFTER_RE = re.compile(
    r"^\s+(?:years?|months?|weeks?|days?|hours?|minutes?|seconds?|miles?|yards?|"
    r"feet|blocks?|units?|shifts?|floors?|rooms?|doors?|windows?|people|men|women|"
    r"cars?|trucks?|calls?|times?|nights?|stops?|exits?|apartments?)\b",
    re.I,
)
_NUMBER_CONTEXT_BEFORE_RE = re.compile(
    r"\b(?:route|highway|interstate|exit|unit|room|floor|gate|apartment)\s*$",
    re.I,
)
_CLOCK_WORD_RE = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"(?:\s+(?:oh\s+)?(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"thirty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"forty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"fifty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?))?"
    r"\s*(?:a\.?m\.?|p\.?m\.?)\b",
    re.I,
)
_MANUFACTURED_SPECIFICITY_RE = re.compile(
    r"\b(?:the only .{0,45} within .{0,20} miles?|give or take (?:a|one) minute|"
    r"set (?:my|a|the) clock by it|never \w+, never \w+|every single (?:night|time|day))\b",
    re.I,
)
_EVIDENCE_PATTERNS = {
    # Count only after-the-fact corroboration, not direct survival actions such as
    # checking a live camera or calling police during the encounter.
    "camera": re.compile(
        r"\b(?:later that (?:day|night)|hours? later|days? later|afterward|"
        r"the next (?:morning|day)|after the (?:incident|encounter))\b[^.!?;\n]{0,90}"
        r"\b(?:camera|cctv|security footage|footage|recording)\b[^.!?;\n]{0,70}"
        r"\b(?:static|blank|failed|cut out|recorded|caught|showed|confirmed|revealed)\b|"
        r"\b(?:reviewed|checked)\b[^.!?;\n]{0,45}\b(?:footage|recording|camera)\b"
        r"[^.!?;\n]{0,45}\b(?:showed|confirmed|revealed|caught|was blank)\b",
        re.I,
    ),
    "official": re.compile(
        r"\b(?:police|sheriff|ranger|official|incident report|records?)\b[^.!?;\n]{0,70}"
        r"\b(?:later )?(?:confirmed|found|showed|revealed|identified)\b|"
        r"\b(?:report|records?)\b[^.!?;\n]{0,40}\b(?:showed|confirmed|revealed)\b",
        re.I,
    ),
    "physical": re.compile(
        r"\b(?:hours? later|days? later|weeks? later|later that (?:day|night)|afterward|"
        r"the next (?:morning|day)|by daylight)\b[^.!?;\n]{0,90}"
        r"\b(?:footprints?|tracks|damaged lock|scratches|blood|abandoned vehicle)\b|"
        r"\b(?:found|left behind|remained)\b[^.!?;\n]{0,45}"
        r"\b(?:footprints?|tracks|damaged lock|scratches|blood|abandoned vehicle)\b",
        re.I,
    ),
    "witness": re.compile(
        r"\b(?:witness|coworker|neighbor|manager|owner)\b[^.!?;\n]{0,35}"
        r"\b(?:later )?(?:confirmed|corroborated|backed up|said (?:they|he|she) saw)\b",
        re.I,
    ),
    "recurrence": re.compile(
        r"\b(?:days|weeks|months) later\b[^.!?;\n]{0,90}"
        r"\b(?:came back|returned|happened again|recurred)\b",
        re.I,
    ),
}


# A last paragraph that closes by disclaiming the narrator's own curiosity. The
# writer rules already forbid it ("a last-paragraph claim that the narrator never
# returned"), the profile lists it as an avoid-trope, and the 2026-07-17 build
# shipped "I never went back to find out who he was." as story 2's final line
# anyway. Prompt-only rules are not release gates.
_FORBIDDEN_ENDING_RE = re.compile(
    r"\bi\s+(?:never|didn'?t\s+ever)\s+(?:did\s+|really\s+|ever\s+)?"
    r"(?:went|go|drove|walked|came|headed)\s+back\b"
    r"|\bi\s+never\s+(?:did\s+|really\s+|ever\s+)?"
    r"(?:found\s+out|learned|figured\s+out|discovered|ask(?:ed)?)\b"
    r"|\bi\s+(?:still\s+)?(?:never\s+)?(?:did\s+)?not\s+go\s+back\b"
    r"|\b(?:to\s+this\s+day\s+)?i\s+still\s+(?:wonder|don'?t\s+know)\s+who\b"
    r"|\bwe\s+never\s+(?:did\s+|really\s+|ever\s+)?"
    r"(?:went\s+back|found\s+out|learned|ask(?:ed)?)\b",
    re.I,
)
_AUTHORITY_RE = re.compile(
    r"\b(?:police|policeman|sheriff|deput(?:y|ies)|officers?|troopers?|patrol|dispatchers?|"
    r"cops?|9\s?-?1\s?-?1|nine\s+one\s+one|emergency\s+(?:line|number|services))\b",
    re.I,
)
# Someone with standing over the narrator, not any adult who happens to be present.
# "A man let me in" is a bystander inside the escape; "I told my mom" is a response.
# Matching bare "adult"/"man"/"woman" would make the gate decorative, so it does not.
_RESPONSIBLE_ADULT_RE = re.compile(
    r"\b(?:mom|mum|mother|dad|father|parents?|stepmom|stepdad|guardian|"
    r"grand(?:ma|pa|mother|father)|aunt|uncle|older\s+(?:brother|sister)|"
    # An adult's own household counts: telling your spouse IS the real-person
    # response (live 2026-07-18: a clean story failed the gate for telling the
    # narrator's wife). Household terms require a narrator-possessive — bare
    # "husband" also appears DESCRIBING a threat ("nobody's husband"), and bare
    # "partner" matches business partners.
    r"(?:my|our)\s+(?:husband|wife|spouse|fianc[ée]e?|partner)|"
    r"teacher|principal|counselor|coach|nurse|"
    # "shift lead" is the standing figure on overnight crews (live 2026-07-19:
    # a story that told the shift lead everything failed the gate on the word).
    r"boss|manager|supervisor|foreman|dispatch|employer|landlord|"
    r"(?:shift|crew|team|site|store)[\s-]+lead(?:er)?|crew\s+chief|"
    r"mrs\.?\s+\w+|mr\.?\s+\w+|ms\.?\s+\w+|"
    r"neighbou?r|witness)\b",
    re.I,
)
# Title/compilation scaffolding and temporal framing carry no subject information:
# "3 True Encounters While Delivering Newspapers Before Dawn" promises newspapers,
# not encounters and not dawn.
_TOPIC_STOPWORDS = frozenset({
    "true", "real", "actual", "genuine", "scary", "creepy", "disturbing", "horror",
    "terrifying", "chilling", "story", "stories", "encounter", "experience",
    "experiences", "account", "accounts", "tale", "tales", "case", "cases",
    "while", "before", "after", "during", "when", "that", "this", "these", "those",
    "with", "from", "into", "onto", "and", "the", "for", "was", "were", "had",
    "her", "his", "our", "their", "you", "your", "alone", "almost", "nearly",
    "dawn", "dusk", "night", "nights", "midnight", "morning", "evening", "day",
    "days", "sunrise", "sunset", "dark", "late", "early", "hour", "hours",
})


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _normal(text: str) -> str:
    return " ".join(w.lower() for w in _words(text))


def _stem(word: str) -> str:
    """Fold the inflections that separate a promise from its payoff.

    Deliberately crude: 'newspapers'/'newspaper', 'delivering'/'delivers'/'deliver'
    must collapse. This is not linguistics, it is a same-word test.
    """
    value = word.lower()
    if len(value) > 4 and value.endswith("ies"):
        value = value[:-3] + "y"
    elif len(value) > 4 and value.endswith(("sses", "shes", "ches", "xes")):
        value = value[:-2]
    elif len(value) > 3 and value.endswith("s") and not value.endswith("ss"):
        value = value[:-1]
    if len(value) > 5 and value.endswith("ing"):
        value = value[:-3]
    elif len(value) > 4 and value.endswith("ed"):
        value = value[:-2]
    return value


def _stems(text: str) -> set[str]:
    return {_stem(word) for word in _words(text)}


def topic_subject_stem(topic: str) -> str:
    """The most specific thing a compilation title promises, or "" if it promises none.

    Heuristic and deliberately so: after dropping scaffolding and temporal words,
    the longest remaining stem is the subject ('newspaper' beats 'deliver'). It is
    wrong only in the direction that costs nothing — if it picks a term the planner
    considers secondary, the planner satisfies the gate by naming that term in
    topic_promise, which is what a title-honest plan does anyway.
    """
    candidates = [
        stem for stem in (
            _stem(word) for word in _words(topic)
            if not word.isdigit() and len(word) >= 3
        )
        if stem not in _TOPIC_STOPWORDS and len(stem) >= 3
    ]
    return max(candidates, key=len, default="")


def _covers_subject(text: str, subject: str) -> bool:
    """True when text names the subject, allowing paper/newspaper style containment."""
    if not subject:
        return True
    return any(
        stem == subject
        or (len(stem) >= 4 and (stem in subject or subject in stem))
        for stem in _stems(text)
    )


def _spoken_numbers(text: str) -> set[int]:
    """Every integer the narration actually says, in digits or in words."""
    values: set[int] = set()
    for match in _NUMBER_RE.finditer(text or ""):
        try:
            values.add(int(match.group(0)))
        except ValueError:
            continue
    for match in _NUMBER_WORD_RE.finditer(text or ""):
        values.add(_parse_number_words(match.group(0)))
    return values


def _paragraphs(narration: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", narration or "") if part.strip()]


# ── Cross-story surface-texture tics (opt-in via stylometric_texture_gate) ──
# The typed-mechanism axes guarantee three DIFFERENT premises; these guard the
# sentence-level HABITS that make three premises read in one author's voice.
# Every check is a LOCAL rephrase, never a structural rewrite, so a failure is
# always repairable by a targeted patch. Whole-text rhythm (paragraph cadence)
# is deliberately left to the critic — it is not locally fixable and would
# deadlock the repair loop.

# Fully banned (0 allowed): trailer/soma clichés a person recounting a night would not write.
_CLICHE_TELLS = (
    ("dramatic_irony", re.compile(r"\blittle did i know\b|\bif only i(?:'d| had) known\b", re.I)),
    ("soma_heart", re.compile(r"\b(?:my |his |her )?heart (?:pounded|hammered|raced|thudded|leapt|slammed)\b", re.I)),
    ("soma_blood", re.compile(r"\bblood ran cold\b", re.I)),
    ("soma_stomach", re.compile(r"\bstomach (?:dropped|sank|lurched|knotted)\b", re.I)),
    ("soma_spine", re.compile(r"\bchills?\s+(?:ran\s+|went\s+)?(?:down|up)\s+my\s+spine\b", re.I)),
    ("soma_breath", re.compile(r"\bbreath caught in my (?:throat|chest)\b", re.I)),
)

# Rationed (<=1 across the whole compilation): the house tics the corpus repeated
# near-verbatim across different narrators.
_RATIONED_TICS = (
    ("out of habit", re.compile(r"\bout of habit\b", re.I)),
    ("harder than I meant", re.compile(r"\bharder than i (?:meant|intended)\b", re.I)),
    ("voice came out (smaller/flatter)", re.compile(r"\bvoice came out (?:smaller|flatter|thinner)\b", re.I)),
    # The "body acted before the mind" panic beat, in any of its common phrasings —
    # observed verbatim-adjacent across two stories of one compilation (line cook's
    # and owner's stories both used it, differently worded).
    ("body-acted-before-mind", re.compile(
        r"\bbefore my (?:head|brain|mind) (?:caught up|could)\b"
        r"|\bbefore i (?:could (?:think|decide|move|stop)|even (?:knew|reali[sz]ed))\b"
        r"|\bhands?\b[^.!?\n]{0,32}\b(?:took over|moved|were moving|took me)\b[^.!?\n]{0,24}\bbefore\b"
        r"|\bmy hands?\s+(?:kind of\s+)?took over\b",
        re.I,
    )),
    ("un-hurried / not hurrying", re.compile(r"\bun-?hurried\b|\bnot hurrying\b", re.I)),
    ("pulse in my ears", re.compile(r"\bpulse (?:in|behind) my ears\b", re.I)),
    # "I like the quiet part of the job" / "I like the night shift best" — the
    # narrator-preference declaration. One narrator may own it; two sharing it
    # read as one author (live 2026-07-19 mall attempt 2, challenger blocker).
    # Adjacency ("I like") naturally skips negations ("I didn't like the...").
    ("'I like the ...' preference declaration", re.compile(
        r"\bI\s+(?:like|love)d?\s+the\b", re.I,
    )),
    # "I don't spook on the job" / "I don't scare easy" — the stock composure
    # claim before admitting unease. Two narrators used it at their most
    # exposed beat in one compilation (live 2026-07-19 mall attempt 2, critic
    # minor); the semantic paraphrases stay the critic's job, the classic
    # wordings are rationed here.
    ("'I don't spook/scare' composure claim", re.compile(
        r"\bI\s+(?:don'?t|do\s+not|never)\s+(?:spook|scare|rattle)\b", re.I,
    )),
    # The routine-invariance declaration: "the order of things never changes",
    # "runs the same way every night", "I have never once skipped a step". The
    # profile ASKS for an ordinary-routine opening, and without variation
    # guidance every narrator asserts their routine's sameness in the same
    # breath (cross-lineage audit 2026-07-25 found it in three of four
    # compilations). One narrator may own the claim.
    ("routine-invariance declaration", re.compile(
        r"\b(?:never changes|the same (?:way )?every (?:night|shift|run|time)|"
        r"never once (?:skipped|missed|failed|varied))\b", re.I,
    )),
    # Cold coffee on the night-shift counter — the single most reused prop in
    # the corpus (audit 2026-07-25: two separate compilations, three stories).
    ("cold-coffee prop", re.compile(
        r"\bcoffee\b[^.!?\n]{0,40}\b(?:gone|going|went)\s+cold\b"
        r"|\bcold\s+coffee\b",
        re.I,
    )),
    # The ears-before-eyes SCAFFOLD: the prompt requires every story to let
    # sound precede sight, and without variation guidance all three writers
    # converge on the literal "heard X before I saw Y" construction (live
    # 2026-07-20 ×2: shuttle 1850 critic major, courier hospital re-judge
    # found it in all three stories). The BEAT stays required; the WORDING is
    # rationed to one narrator.
    ("'heard it before I saw it' scaffold", re.compile(
        r"\bheard\b[^.!?\n]{0,40}\bbefore\s+I\s+(?:ever\s+)?saw\b", re.I,
    )),
    # The no-record aftermath device: an authority/records check that comes
    # back empty. Live 2026-07-20 (shuttle 0153): ALL THREE stories closed on
    # it under three different aftermath labels — the axis cannot see a shared
    # surface device. Classic wordings rationed to one story; paraphrases stay
    # with the critic/challenger.
    ("'nothing on file' no-record device", re.compile(
        r"\bnothing (?:on file|in the (?:system|logs?))\b"
        r"|\bno (?:record|match|report) (?:of|for|in|came back)\b"
        r"|\bnever matched (?:a|the) name\b"
        r"|\b(?:log|file|system|records?) (?:showed|turned up|had) nothing\b",
        re.I,
    )),
)

_THE_WAY_COMPARISON_RE = re.compile(
    r"\bthe way (?:you|he|she|it|they|something|someone|that)\b", re.I,
)

# The silent motionless watcher RENDERED in prose. One lone_stranger story per
# compilation may earn it; any other threat_identity claiming it contradicts its
# own plan label (live 2026-07-19: an unseen_ambiguous story described "a shape
# roughly the height of a person, arms down, standing square to the cabin" —
# fully seen, fully still, and no layer caught it).
_STILL_WATCHER_RE = re.compile(
    r"\b(?:standing|stood)\b[^.!?\n]{0,60}\b(?:still|motionless|without moving|square to)\b"
    r"|\b(?:perfectly|completely|dead)\s+still\b[^.!?\n]{0,40}\b(?:watch\w*|fac(?:e|ing))\b",
    re.I,
)

# The "menace-by-negation reversal" rhythm — near-universal across LLM horror:
# "It was no accident. It was deliberate." / "Not just late, but wrong."
_NEGATION_REVERSAL_RE = re.compile(
    r"\b(?:it|that|this)\s+(?:was|is|wasn'?t|isn'?t)\s+no\b[^.!?]*[.!?]\s*"
    r"(?:it|that|this)\s+(?:was|is)\b"
    r"|\bnot\s+just\b[^.!?,]*,?\s*but\b",
    re.I,
)

# The negation TRIAD — three drumbeat negations in one breath ("No hey, no
# here's-your-order, no wave." / "Not a sound. Not a step. Just him.") — caught
# live by the critic across two stories of one compilation after the reversal
# regex missed it: a different construction, same house rhythm.
_NEGATION_TRIAD_RE = re.compile(
    r"\b[Nn]ot?\b[^.!?\n]{1,40}?,\s*[Nn]ot?\b[^.!?\n]{1,40}?,\s*[Nn]ot?\b"
    r"|(?:^|[.!?]\s+)(?:No|Not)\b[^.!?\n]{0,40}[.!?]\s+(?:No|Not)\b[^.!?\n]{0,40}[.!?]\s+(?:No|Not|Just)\b",
)

# Similes — natural in small doses, an AI tell in bulk. Advisory, not blocking.
_SIMILE_RE = re.compile(r"\b(?:like a|like an|as if|as though)\b", re.I)


def _sentence_list(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "st", "ave", "rd", "blvd", "jr", "sr", "vs",
    "no", "etc", "inc", "co", "apt", "ste", "dept", "sgt", "lt", "capt", "det",
})


def _oneword_beats(text: str) -> list[str]:
    """Single-word sentences ('Quiet.' 'Nothing.') — a couple is style, a spray
    is the machine's punch-fragment tic. Abbreviations ('Mrs.', 'St.') split by
    the sentence tokenizer are not beats."""
    beats = []
    for sentence in _sentence_list(text):
        core = re.sub(r"[^A-Za-z']+", " ", sentence).split()
        if len(core) == 1 and len(core[0]) >= 2 and core[0].lower() not in _ABBREVIATIONS:
            beats.append(sentence)
    return beats


def _final_paragraph(text: str) -> str:
    parts = [p.strip() for p in (text or "").split("\n") if p.strip()]
    return parts[-1] if parts else ""


def _stylometric_texture_findings(
    stories: list[StoryDraft],
    plan_by_id: dict[str, NarrativeStoryPlan] | None = None,
) -> tuple[list[GateFailure], list[GateFailure]]:
    """Return (hard_failures, editorial_flags) for shared surface-texture tics.

    Attribution is minimal: a compilation-level cap names the story of the
    SECOND occurrence (the one to change), never the first legitimate use."""
    failures: list[GateFailure] = []
    flags: list[GateFailure] = []

    # 1. Fully-banned clichés — zero allowed, per story.
    for story in stories:
        for label, pattern in _CLICHE_TELLS:
            match = pattern.search(story.narration)
            if match:
                failures.append(_failure(
                    "stylometric_cliche",
                    f"{story.story_id} uses a stock cliché ({match.group(0)!r}); real "
                    "people recounting something name feeling plainly, not in stock imagery",
                    story.story_id,
                ))
                break  # one per story is enough to send it back

    # 2. Rationed house tics — at most one occurrence across the whole compilation.
    for label, pattern in _RATIONED_TICS:
        seen_story: str | None = None
        for story in stories:
            if pattern.search(story.narration):
                if seen_story is not None:
                    failures.append(_failure(
                        "stylometric_rationed_tic",
                        f"{story.story_id} repeats the compilation tic {label!r} already "
                        f"used in {seen_story}; vary it — a habit shared across narrators "
                        "reads as one author, not three different people",
                        story.story_id,
                    ))
                    break
                seen_story = story.story_id

    # THE CAPS WERE SET FOR ~750-WORD COMPILATION STORIES. A single 1,800-2,600
    # word account is held to the same 'one per story' and fails three times
    # as easily for the same texture density. Allowances scale with length:
    # the base cap per 800 spoken words. Cross-story rules are unchanged.
    def _allow(story, base: int) -> int:
        words = len(_words(story.narration))
        return base * max(1, round(words / 800))

    # 3. "the way you/he/she..." comparison — at most one per ~800 words.
    for story in stories:
        hits = _THE_WAY_COMPARISON_RE.findall(story.narration)
        if len(hits) > _allow(story, 1):
            failures.append(_failure(
                "stylometric_the_way",
                f"{story.story_id} leans on the 'the way you...' comparison "
                f"{len(hits)} times; keep at most {_allow(story, 1)} for its length",
                story.story_id,
            ))

    # 4. One-word beat sentences — a couple is fine, a spray is the tic.
    for story in stories:
        beats = _oneword_beats(story.narration)
        if len(beats) > _allow(story, 2):
            failures.append(_failure(
                "stylometric_oneword_beat",
                f"{story.story_id} sprays {len(beats)} one-word beat sentences "
                f"({', '.join(repr(b) for b in beats[:4])}); keep at most {_allow(story, 2)} for its length",
                story.story_id,
            ))

    # 4b. Negation-reversal rhythm — at most one per story.
    for story in stories:
        hits = _NEGATION_REVERSAL_RE.findall(story.narration)
        if len(hits) > _allow(story, 1):
            failures.append(_failure(
                "stylometric_negation_reversal",
                f"{story.story_id} uses the 'it was no X, it was Y / not just X but Y' "
                f"reversal {len(hits)} times; keep at most one — it is the machine's "
                "most universal rhythm",
                story.story_id,
            ))

    # 4d. Negation triad — one per story is a beat; shared across stories it is
    # the house rhythm (the later user changes, like the shared coda rule).
    # Messages carry the EXACT offending text: an unquoted cross-story triad
    # failure survived 7 repair calls blind (live 2026-07-18 build 2357).
    triad_seen: tuple[str, str] | None = None  # (story_id, quoted text)
    for story in stories:
        matches = [m.group(0).strip() for m in _NEGATION_TRIAD_RE.finditer(story.narration)]
        if len(matches) > _allow(story, 1):
            failures.append(_failure(
                "stylometric_negation_triad",
                f"{story.story_id} drums the negation triad {len(matches)} times "
                f"({'; '.join(repr(m[:60]) for m in matches[:3])}); keep at most one",
                story.story_id,
            ))
        if matches:
            if triad_seen is not None:
                failures.append(_failure(
                    "stylometric_negation_triad",
                    f"{story.story_id} repeats the negation-triad rhythm "
                    f"({matches[0][:80]!r}) already used in {triad_seen[0]} "
                    f"({triad_seen[1][:80]!r}); rephrase THIS story's triad into a "
                    "different construction — two narrators sharing one drumbeat "
                    "read as one author",
                    story.story_id,
                ))
            else:
                triad_seen = (story.story_id, matches[0])

    # 4c. Simile density — advisory only (false-positive prone: "looked like a
    # delivery guy"), so it informs the critic without risking a deadlock.
    for story in stories:
        similes = _SIMILE_RE.findall(story.narration)
        budget = 3 + len(_words(story.narration)) // 400
        if len(similes) > budget:
            flags.append(_failure(
                "stylometric_simile_density",
                f"{story.story_id} uses {len(similes)} similes (soft budget {budget}); "
                "someone recounting a night rarely reaches for this many",
                story.story_id,
            ))

    # 4e. The still-watcher rendering: one lone_stranger story may earn it; any
    # other identity claiming it contradicts its own plan label, and two stories
    # rendering it is the monoculture the identity axis exists to kill.
    def _threat_pose(narration: str):
        """First still-pose match whose subject is not the narrator ("I stood
        with my back to the cooler" is the narrator hiding, not the trope)."""
        for m in _STILL_WATCHER_RE.finditer(narration):
            lead = narration[max(0, m.start() - 28):m.start()]
            if re.search(r"\bI\s+(?:was\s+|had\s+been\s+|just\s+)?$", lead):
                continue
            return m
        return None

    watcher_seen: str | None = None
    for story in stories:
        match = _threat_pose(story.narration)
        if not match:
            continue
        identity = ""
        if plan_by_id and story.story_id in plan_by_id:
            identity = getattr(plan_by_id[story.story_id], "threat_identity", "")
        if identity and identity != "lone_stranger":
            failures.append(_failure(
                "stylometric_still_watcher",
                f"{story.story_id} renders a silent motionless watcher "
                f"({match.group(0)[:80]!r}) but its locked threat_identity is "
                f"{identity} — an unseen or non-stranger threat must act or stay "
                "truly unseen, not pose; the one still-watcher slot belongs to a "
                "lone_stranger story",
                story.story_id,
            ))
        elif watcher_seen is not None:
            failures.append(_failure(
                "stylometric_still_watcher",
                f"{story.story_id} renders the still-watcher pose "
                f"({match.group(0)[:80]!r}) already used in {watcher_seen}; at most "
                "one story per compilation may play that card",
                story.story_id,
            ))
        else:
            watcher_seen = story.story_id

    # 5. Shared closing-move family — the later duplicate must change. Started
    # as the "I still..." anaphora; widened after a live build (2026-07-19,
    # 78/100) closed all three stories on the interchangeable "now I always
    # perform this small ritual" shape under three different aftermath labels.
    _CODA_FAMILY_RE = re.compile(
        r"^\s*(?:And\s+|But\s+|So\s+)?"
        r"(?:I still\b|Now I\b|These days I\b|Ever since\b|"
        r"Every (?:night|morning|shift|day)\b[^.!?\n]{0,30}\b(?:since|now)\b|"
        r"I (?:always|never)\b[^.!?\n]{0,40}\bnow\b)",
        re.I,
    )
    coda_seen: tuple[str, str] | None = None
    for story in stories:
        final = _final_paragraph(story.narration)
        tail_sentences = _sentence_list(final)[-2:] or _sentence_list(story.narration)[-2:]
        hit = next(
            (s for s in [final, *tail_sentences] if _CODA_FAMILY_RE.match(s.strip())),
            None,
        )
        if hit:
            if coda_seen is not None:
                failures.append(_failure(
                    "stylometric_shared_coda",
                    f"{story.story_id} closes on the changed-ritual coda "
                    f"({hit.strip()[:70]!r}) — the same closing move already used in "
                    f"{coda_seen[0]} ({coda_seen[1][:70]!r}); give this story a "
                    "different closing move (an image, an unanswered detail, a flat "
                    "report — not another ritual)",
                    story.story_id,
                ))
                break
            coda_seen = (story.story_id, hit.strip())

    # 6. Verbatim phrase reuse across stories — the GENERIC form of 1-5.
    # Checks 1-5 each name ONE tic, every one added reactively after a live
    # catch; the critic kept surfacing new instances the whitelist could not
    # see (live 2026-07-20 front desk, 74/100: "hands loose at his sides"
    # verbatim across two unrelated men, plus a shared decisive-pivot
    # scaffold). Any rare five-word run shared by two narrators reads as one
    # author whichever tic it happens to instantiate, so match the SHAPE
    # instead of enumerating the instances. Domain nouns from the locked plans
    # are exempt — three shuttle drivers must be allowed to say "the overnight
    # shuttle van" — and two content words are required so shared function-word
    # runs ("and I went back to") never fire.
    failures.extend(_shared_phrase_failures(stories, plan_by_id))
    # Titles are read together on the card beats — an unchecked surface until
    # the 2026-07-25 cross-lineage audit found all three cut from one formula.
    failures.extend(_title_template_failures(stories))

    return failures, flags


_PHRASE_NGRAM = 5

# Content words the window must carry to count. Replayed over the channel's
# 66-script corpus, a two-word floor flagged procedural idiom any two workers
# would land on independently ("and put it in park", "the stairs two at a
# time"); a three-word floor keeps only the DESCRIPTIVE phrases ("hands loose
# at his sides") that two narrators cannot invent word-for-word, and fires on
# none of the scripts that were actually released.
_PHRASE_MIN_CONTENT = 3

# Function words plus the handful of bare narrative verbs that carry no voice.
_PHRASE_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "so", "if", "than", "then", "that",
    "this", "these", "those", "of", "to", "in", "on", "at", "by", "for", "with",
    "from", "into", "out", "up", "down", "over", "back", "off", "about",
    "i", "me", "my", "mine", "myself", "he", "him", "his", "she", "her", "hers",
    "it", "its", "they", "them", "their", "we", "us", "our", "you", "your",
    "is", "was", "were", "are", "be", "been", "am", "do", "did", "does", "done",
    "have", "has", "had", "will", "would", "could", "can", "should", "not",
    "no", "there", "here", "when", "what", "who", "which", "all", "one", "two",
    "just", "like", "as", "got", "get", "went", "go", "said", "say", "know",
    "s", "t", "re", "ve", "ll", "d", "m",
})


def _phrase_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z']+", (text or "").lower())


def _plan_domain_words(
    plan_by_id: dict[str, NarrativeStoryPlan] | None,
) -> frozenset[str]:
    """Vocabulary the premises legitimately share — the topic, the workplace,
    the narrator's trade. Two stories using it verbatim is the assignment, not
    a shared habit."""
    if not plan_by_id:
        return frozenset()
    words: set[str] = set()
    for plan in plan_by_id.values():
        for field in ("topic_promise", "setting", "narrator_profile"):
            words.update(_phrase_tokens(getattr(plan, field, "") or ""))
    return frozenset(words)


def _maximal_shared_run(
    tokens: list[str], start: int, owner_tokens: list[str],
) -> tuple[int, list[str]]:
    """Grow the matching window outward in both texts while the tokens agree.

    Returns (start index of the run in `tokens`, the run)."""
    n = _PHRASE_NGRAM
    gram = tokens[start:start + n]
    origin = next(
        (o for o in range(len(owner_tokens) - n + 1)
         if owner_tokens[o:o + n] == gram),
        None,
    )
    if origin is None:  # pragma: no cover - owner always holds the gram
        return start, gram
    lo, hi = start, start + n
    olo, ohi = origin, origin + n
    while lo > 0 and olo > 0 and tokens[lo - 1] == owner_tokens[olo - 1]:
        lo -= 1
        olo -= 1
    while hi < len(tokens) and ohi < len(owner_tokens) and tokens[hi] == owner_tokens[ohi]:
        hi += 1
        ohi += 1
    return lo, tokens[lo:hi]


def _shared_phrase_failures(
    stories: list[StoryDraft],
    plan_by_id: dict[str, NarrativeStoryPlan] | None = None,
) -> list[GateFailure]:
    """One failure per story that repeats an earlier story's rare phrase."""
    domain = _plan_domain_words(plan_by_id)
    failures: list[GateFailure] = []
    seen: dict[tuple[str, ...], str] = {}  # ngram -> story that owns it first
    story_tokens: dict[str, list[str]] = {}

    for story in stories:
        tokens = _phrase_tokens(story.narration)
        story_tokens[story.story_id] = tokens
        own: set[tuple[str, ...]] = set()
        hits: list[tuple[str, str]] = []  # (quoted run, owner)
        consumed = 0  # end of the last reported run, so one habit reports once
        for start in range(len(tokens) - _PHRASE_NGRAM + 1):
            gram = tuple(tokens[start:start + _PHRASE_NGRAM])
            own.add(gram)
            owner = seen.get(gram)
            if owner is None or owner == story.story_id or start < consumed:
                continue
            content = {
                tok for tok in gram
                if tok not in _PHRASE_STOPWORDS and tok not in domain
            }
            if len(content) < _PHRASE_MIN_CONTENT:
                continue
            # Quote the WHOLE shared run, not the window that found it — a
            # half-quoted phrase sent earlier repair waves at the wrong half of
            # the sentence.
            lo, run = _maximal_shared_run(tokens, start, story_tokens[owner])
            consumed = lo + len(run)
            hits.append((" ".join(run), owner))
        if hits:
            quoted = "; ".join(f"{run!r} (also in {owner})" for run, owner in hits)
            failures.append(_failure(
                "stylometric_shared_phrase",
                f"{story.story_id} reuses {len(hits)} phrase(s) word-for-word "
                f"from an earlier story: {quoted}. Two narrators sharing an "
                "exact turn of phrase read as one author — rewrite EVERY "
                "occurrence listed here in wording specific to THIS narrator's "
                "vantage and trade, keeping each beat unchanged",
                story.story_id,
            ))
        for gram in own:
            seen.setdefault(gram, story.story_id)

    return failures


def _finishing_wave_allowed(
    score: NarrativeScorecard,
    gate: GateReport,
    strategy: NamedChannelStrategy,
    failing_ids: set[str],
) -> bool:
    """Whether a compilation has earned the one FINISHING repair wave.

    The wave budget (2) protected against debate loops, but it also discarded
    candidates standing at the release door: courier 1726 hit 84/84 with every
    dimension floor passed and exactly two quoted majors on one story, and the
    run ended needs_edit with the fix instructions sitting unread in the
    scorecard. A third wave is allowed only when the compilation is already in
    release range (>= floor - 2), gates pass, nothing is critical, at most two
    stories still carry blockers, and every remaining blocker is quoted — the
    locally-repairable kind. Everything else still stops at two waves."""
    if not gate.passed or score.critical_issues:
        return False
    # "Nothing critical" means STRUCTURED criticals too — external review
    # 2026-07-20 constructed a score-84 card with a quoted critical story
    # issue and this guard returned True (spec said it must not).
    if any(issue.severity == "critical" for issue in score.story_issues):
        return False
    if score.total_score < strategy.approval_score - 2:
        return False
    if not failing_ids or len(failing_ids) > 2:
        return False
    remaining = [
        issue for issue in score.story_issues
        if issue.story_id in failing_ids
        and issue.severity in {"critical", "major"}
    ]
    return bool(remaining) and all(
        (issue.evidence_quote or issue.anchor_quote).strip()
        for issue in remaining
    )


_TITLE_LEADING_ARTICLE_RE = re.compile(r"^\s*the\b", re.I)
# "The Room That Isn't There", "The Uniform That Changed", "The Waypoint That
# Wasn't There" — noun phrase plus a restrictive clause announcing the anomaly.
_TITLE_ANOMALY_CLAUSE_RE = re.compile(
    r"^\s*the\s+\w+[\w\s'-]*\s+(?:that|which|nobody|no one|who)\b", re.I,
)


def _title_template_failures(stories: list[StoryDraft]) -> list[GateFailure]:
    """Story TITLES are a surface no gate has ever read.

    Cross-lineage audit 2026-07-25 (codex, two separate compilations): all
    three story titles in a compilation shared one template — "The <noun
    phrase>" and, worse, "The <noun> That <anomaly>". A viewer sees the three
    titles together on the card beats; three variations of one formula is a
    production-template tell in the exact place the channel looks most
    manufactured. Two may rhyme; three is the formula."""
    titles = [(s.story_id, (s.title or "").strip()) for s in stories]
    named = [(sid, t) for sid, t in titles if t]
    if len(named) < 3:
        return []
    failures: list[GateFailure] = []

    anomaly = [(sid, t) for sid, t in named if _TITLE_ANOMALY_CLAUSE_RE.match(t)]
    if len(anomaly) >= 2:
        failures.append(_failure(
            "stylometric_title_template",
            f"{anomaly[-1][0]} titles its story {anomaly[-1][1]!r} on the same "
            f"'The <thing> that <anomaly>' formula already used by "
            f"{anomaly[0][0]} ({anomaly[0][1]!r}); the three titles are read "
            "together on the card beats — give this one a different shape "
            "(a plain place or object, a spoken fragment, a time)",
            anomaly[-1][0],
        ))
        return failures

    leading = [(sid, t) for sid, t in named if _TITLE_LEADING_ARTICLE_RE.match(t)]
    if len(leading) == len(named):
        failures.append(_failure(
            "stylometric_title_template",
            f"all {len(named)} story titles open with 'The' "
            f"({', '.join(repr(t) for _sid, t in named)}); vary at least one — "
            "three titles cut from one pattern read as a template",
            named[-1][0],
        ))
    return failures


def _near_miss_minor_ids(
    score: NarrativeScorecard,
    gate: GateReport,
    strategy: NamedChannelStrategy,
    expected_ids: set[str],
    repair_waves: int,
) -> set[str]:
    """Stories eligible for the one bounded minor-repair wave.

    A compilation with clean gates, zero critical/major issues, and a score
    just under the floor used to die needs_edit with ZERO repair calls (live
    2026-07-19 mall: 83 vs floor 84, three quoted repairable minors,
    repair_writer=0) — repair only ever chased gate failures and majors.
    Quoted minors are exactly the locally-patchable kind; one wave may close
    the gap. Guards keep this from rescuing weak drafts: gates must pass, no
    critical/major anywhere, the gap must be small, and only the first wave
    qualifies."""
    if repair_waves != 0 or not gate.passed or score.critical_issues:
        return set()
    if any(i.severity in {"critical", "major"} for i in score.story_issues):
        return set()
    gap = strategy.approval_score - score.total_score
    if gap <= 0 or gap > 3:
        return set()
    return {
        issue.story_id for issue in score.story_issues
        if issue.story_id in expected_ids
        and issue.severity == "minor"
        and issue.evidence_quote.strip()
    }


def _ending_region(narration: str) -> str:
    """The last paragraph — where an ending discipline defect can actually live."""
    paragraphs = _paragraphs(narration)
    return paragraphs[-1] if paragraphs else ""


def _aftermath_region(narration: str) -> str:
    """The tail where an after-the-fact response lives.

    A safety obligation is an AFTERMATH obligation — what the narrator does once
    they are out. Scoping to the tail is what separates "I told my mom what
    happened" from "my mom always said the dark before dawn is the darkest dark
    there is", and the neighbour who is told afterwards from the neighbour who
    merely opens a door mid-escape. Searching the whole narration would let any
    incidental family noun discharge the obligation, which is no gate at all.

    The window is a WORD budget, not a paragraph count. Live 2026-09-04
    (hotel front desk, 89/100 rejected): the genre's one-line paragraphing
    made "last 3 paragraphs" a three-sentence window, and the mandatory
    what-stays coda (already_line, routine change, remainder) now occupies
    exactly that tail — so a draft that reported to the deputies in a full
    aftermath scene 8 paragraphs from the end failed the gate that its own
    coda contract pushed it out of. The budgeted window is always a superset
    of the old three-paragraph one, so nothing that passed before can fail now.
    """
    paras = _paragraphs(narration)
    total_words = sum(len(p.split()) for p in paras)
    # Proportional, no absolute floor: a fixed floor (first cut used 150 words)
    # swallowed a fifth of a short story and pulled mid-escape bystanders into
    # the window — the release-integrity fixtures caught it. Three paragraphs
    # is the only minimum; 15% scales the window to the story.
    budget = int(total_words * 0.15)
    tail: list[str] = []
    words = 0
    for para in reversed(paras):
        tail.append(para)
        words += len(para.split())
        if words >= budget and len(tail) >= 3:
            break
    return "\n\n".join(reversed(tail))


def _parse_number_words(phrase: str) -> int:
    total = current = 0
    for token in re.split(r"[\s-]+", phrase.lower()):
        if token == "and":
            continue
        if token in _NUMBER_UNITS:
            current += _NUMBER_UNITS[token]
        elif token in _NUMBER_TENS:
            current += _NUMBER_TENS[token]
        elif token == "hundred":
            current = max(1, current) * 100
        elif token == "thousand":
            total += max(1, current) * 1000
            current = 0
    return total + current


def _numeric_anchors(text: str) -> set[str]:
    source = text or ""
    sequence_spans: list[tuple[int, int]] = []
    anchors: set[str] = set()
    for match in _NUMBER_SEQUENCE_RE.finditer(source):
        anchors.add(re.sub(r"\s+", "", match.group(0).lower()))
        sequence_spans.append(match.span())
    for match in _NUMBER_RE.finditer(source):
        if not any(
            start <= match.start() and match.end() <= end for start, end in sequence_spans
        ):
            anchors.add(match.group(0).lower())
    for match in _NUMBER_WORD_RE.finditer(source):
        after = source[match.end():match.end() + 32]
        before = source[max(0, match.start() - 24):match.start()]
        if _NUMBER_CONTEXT_AFTER_RE.search(after) or _NUMBER_CONTEXT_BEFORE_RE.search(before):
            anchors.add(str(_parse_number_words(match.group(0))))
    return anchors


def _failure(code: str, message: str, *story_ids: str) -> GateFailure:
    return GateFailure(code=code, message=message, story_ids=list(story_ids))


def gate_compilation(
    plan: CompilationPlan,
    stories: list[StoryDraft],
    strategy: NamedChannelStrategy | None = None,
) -> GateReport:
    """Run objective release gates. Ambiguous literary quality remains critic-owned."""
    failures: list[GateFailure] = []
    editorial_flags: list[GateFailure] = []
    strategy = strategy or NamedChannelStrategy(
        strategy_id="system_default", writer_rules="restrained narrative",
        critic_rules="skeptical content audit", annotation_rules="literal production metadata",
    )
    expected_ids = [story.story_id for story in plan.stories]
    actual_ids = [story.story_id for story in stories]
    if actual_ids != expected_ids:
        failures.append(_failure(
            "story_count_or_order",
            f"Expected story IDs {expected_ids}; received {actual_ids}",
            *actual_ids,
        ))

    target_total = max(1, int(plan.target_word_count))
    per_target = target_total / max(1, len(plan.stories))
    story_words = {story.story_id: len(_words(story.narration)) for story in stories}
    total_words = sum(story_words.values())
    if total_words < GENRE_FLOOR_TOTAL_WORDS:
        length_target = (
            min(stories, key=lambda item: story_words[item.story_id]).story_id
            if stories and total_words < target_total
            else max(stories, key=lambda item: story_words[item.story_id]).story_id
            if stories else ""
        )
        failures.append(_failure(
            "total_length",
            f"Compilation has {total_words} words; under the genre floor of "
            f"{GENRE_FLOOR_TOTAL_WORDS} (about eight minutes spoken). Length is the "
            f"account's to decide above that; this is not a video yet.",
            *([length_target] if length_target else []),
        ))

    evidence_free = 0
    plan_by_id = {item.story_id: item for item in plan.stories}
    all_paragraphs: dict[str, str] = {}
    story_ngrams: dict[str, set[tuple[str, ...]]] = {}
    subject = topic_subject_stem(plan.topic)
    for story in stories:
        sid = story.story_id
        story_plan = plan_by_id.get(sid)
        count = story_words[sid]

        if strategy.forbidden_ending_gate and _FORBIDDEN_ENDING_RE.search(
            _ending_region(story.narration)
        ):
            failures.append(_failure(
                "forbidden_ending",
                f"{sid} closes on a forbidden self-referential disclaimer "
                f"({_FORBIDDEN_ENDING_RE.search(_ending_region(story.narration)).group(0)!r}); "
                "end on the strongest image, not on what the narrator declined to learn",
                sid,
            ))
        if strategy.plan_fact_fidelity_gate and story_plan is not None:
            # A plan fact the story never says is a fact the viewer never gets.
            # The 2026-07-17 story 1 locked a sixteen-year-old narrator, compliance
            # called ordinary_setup "complete", and the age is nowhere on the page.
            if (
                story_plan.narrator_age_band == "minor"
                and story_plan.narrator_age_years is not None
                and story_plan.narrator_age_years not in _spoken_numbers(story.narration)
            ):
                failures.append(_failure(
                    "plan_fact_age",
                    f"{sid} locks a {story_plan.narrator_age_years}-year-old narrator but "
                    "the narration never states that age; a minor's age changes how every "
                    "beat reads and must be spoken",
                    sid,
                ))
            if subject and not _covers_subject(story.narration, subject):
                failures.append(_failure(
                    "plan_fact_topic_promise",
                    f"{sid} never names the compilation subject {subject!r} that the topic "
                    f"promises ({plan.topic!r}); the plan promised {story_plan.topic_promise!r}",
                    sid,
                ))
        # A declared safety path is a promise, not a loophole: without this, the
        # softer trusted_adult path would be strictly easier to declare and ignore
        # than the police ending it exists to replace.
        if strategy.safety_response_gate and story_plan is not None:
            aftermath = _aftermath_region(story.narration)
            if (
                story_plan.safety_obligation == "authorities_contacted"
                and not _AUTHORITY_RE.search(aftermath)
            ):
                failures.append(_failure(
                    "safety_response",
                    f"{sid} locks an authorities_contacted response but no police, sheriff, "
                    "officer, or emergency call appears in the aftermath",
                    sid,
                ))
            elif (
                story_plan.safety_obligation == "trusted_adult_or_witness"
                and not _RESPONSIBLE_ADULT_RE.search(aftermath)
                and not _AUTHORITY_RE.search(aftermath)
            ):
                failures.append(_failure(
                    "safety_response",
                    f"{sid} locks a trusted_adult_or_witness response but nobody with "
                    "standing (a parent, guardian, spouse, teacher, employer, named "
                    "neighbour, or witness) is told in the aftermath",
                    sid,
                ))
        # AGAINST ITS OWN BUDGET. This used to compare every story to an equal
        # share of the compilation, which is a uniformity rule wearing a length
        # rule's clothes: a 900-word premise and a 2,200-word premise both
        # failed for being what they are. The compilation total is still
        # checked above — that is the constraint that actually matters, because
        # it is the one the viewer experiences as video length.
        own_target = float(getattr(story_plan, "target_words", 0) or 0) or per_target
        if count < GENRE_FLOOR_STORY_WORDS:
            failures.append(_failure(
                "story_length",
                f"{sid} has {count} words; under the genre floor of {GENRE_FLOOR_STORY_WORDS}. "
                f"(The plan estimated {own_target:.0f}; that is a shape, not a law.)",
                sid,
            ))
        # EVERY match is quoted, not just the first: a repair that fixes one
        # occurrence while a second survives fails the trial gate and gets
        # thrown away looking "unfixable" (live 2026-07-18: one sentence held
        # 'telling myself' twice; three repairs and a rewrite all died blind).
        banned_hits = [m.group(0) for m in _BANNED_RE.finditer(story.narration)]
        # 'I told myself it was just a small company delivery' — the genre's
        # denial-that-fails beat, in the corpus's most-watched story twice.
        # Two per story is the account reasoning; three or more is a tic.
        empty_hits = [m.group(0) for m in _BANNED_EMPTY_RE.finditer(story.narration)]
        if empty_hits or len(banned_hits) > 2:
            banned_hits = empty_hits or banned_hits
            failures.append(_failure(
                "banned_self_reassurance",
                f"{sid} uses stock self-reassurance {len(banned_hits)} time(s): "
                + "; ".join(repr(h) for h in banned_hits[:4])
                + " — remove or rephrase EVERY occurrence, including negated or "
                "self-correcting uses",
                sid,
            ))
        cta_hits = [m.group(0) for m in _CTA_RE.finditer(story.narration)]
        if cta_hits:
            failures.append(_failure(
                "cta_or_meta",
                f"{sid} contains channel/meta framing: "
                + "; ".join(repr(h) for h in cta_hits[:3]),
                sid,
            ))
        # Repeating a decision-relevant unit/route number is one anchor, not a new
        # attempt at fake precision every time it is referenced.
        numbers = _numeric_anchors(story.narration)
        clocks = {
            *(match.group(0).lower() for match in _PRECISE_TIME_RE.finditer(story.narration)),
            *(match.group(0).lower() for match in _CLOCK_WORD_RE.finditer(story.narration)),
        }
        if (
            len(numbers) > strategy.numeric_anchor_limit
            or len(clocks) > strategy.precise_clock_limit
        ):
            failures.append(_failure(
                "specificity_budget",
                f"{sid} has {len(numbers)} numeric anchors {sorted(numbers)} and "
                f"{len(clocks)} precise clock times {sorted(clocks)}; keep only values "
                "that affect identity, navigation, timing, or a decision",
                sid,
            ))
        manufactured = _MANUFACTURED_SPECIFICITY_RE.search(story.narration)
        if manufactured:
            editorial_flags.append(_failure(
                "manufactured_specificity",
                f"{sid} may use decorative precision: {manufactured.group(0)!r}",
                sid,
            ))

        evidence = [name for name, pattern in _EVIDENCE_PATTERNS.items() if pattern.search(story.narration)]
        if not evidence:
            evidence_free += 1
        if len(evidence) > strategy.evidence_beat_limit:
            failures.append(_failure(
                "evidence_budget",
                f"{sid} has {len(evidence)} corroboration types; profile allows "
                f"{strategy.evidence_beat_limit}: {', '.join(evidence)}",
                sid,
            ))
        allowance = plan_by_id.get(sid).evidence_allowance.lower() if sid in plan_by_id else "none"
        if evidence and "none" in allowance:
            failures.append(_failure(
                "unplanned_evidence",
                f"{sid} uses {', '.join(evidence)} despite a no-evidence plan",
                sid,
            ))

        local_seen: set[str] = set()
        for paragraph in re.split(r"\n\s*\n", story.narration):
            normalized = _normal(paragraph)
            if len(normalized.split()) < 8:
                continue
            if normalized in local_seen:
                failures.append(_failure("repeated_paragraph", f"{sid} repeats a paragraph", sid))
                break
            local_seen.add(normalized)
            other = all_paragraphs.get(normalized)
            if other and other != sid:
                failures.append(_failure(
                    "cross_story_repeated_paragraph", f"{sid} repeats a paragraph from {other}", other, sid
                ))
            all_paragraphs[normalized] = sid

        tokens = _normal(story.narration).split()
        story_ngrams[sid] = {tuple(tokens[i:i + 10]) for i in range(max(0, len(tokens) - 9))}

    required_evidence_free = min(len(stories), strategy.evidence_free_story_min)
    if stories and evidence_free < required_evidence_free:
        failures.append(_failure(
            "evidence_free_story",
            f"At least {required_evidence_free} stories must end without corroborating evidence",
            *actual_ids,
        ))

    for i, left in enumerate(stories):
        for right in stories[i + 1:]:
            overlap = story_ngrams.get(left.story_id, set()) & story_ngrams.get(right.story_id, set())
            if overlap:
                failures.append(_failure(
                    "cross_story_repeated_phrase",
                    f"{left.story_id} and {right.story_id} share an exact 10-word phrase",
                    left.story_id,
                    right.story_id,
                ))
                break

    for field, code in (("narrator_profile", "plan_voice_diversity"),
                        ("threat", "plan_threat_diversity"),
                        ("ending_shape", "plan_ending_diversity")):
        values = [_normal(getattr(item, field)) for item in plan.stories]
        if len(set(values)) != len(values):
            failures.append(_failure(code, f"Plan repeats {field}", *expected_ids))
    human_count = sum(item.threat_type == "human" for item in plan.stories)
    required_human = math.ceil(
        len(plan.stories) * strategy.human_threat_fraction_min
    )
    if human_count < required_human:
        failures.append(_failure(
            "plan_threat_mix",
            f"Plan has {human_count} human threats; requires at least {required_human}",
            *expected_ids,
        ))

    # Cross-story surface-texture tics (opt-in). Runs only with the full
    # compilation in hand; caught here rather than per-story because the whole
    # point is repetition ACROSS narrators.
    if getattr(strategy, "stylometric_texture_gate", False) and (
        actual_ids == expected_ids
    ):
        tex_failures, tex_flags = _stylometric_texture_findings(
            stories, plan_by_id=plan_by_id,
        )
        failures.extend(tex_failures)
        editorial_flags.extend(tex_flags)

    # MEASURED AGAINST REAL COMPETITOR SCRIPTS, which no other gate here does.
    # Everything above compares the compilation to rules this team wrote; this
    # compares it to 147 captions from the channels it competes with. The first
    # build put through it read at 24 words a sentence against a genre whose
    # whole distribution runs 10-15, opened with no concrete anchor where the
    # genre anchors in line one, and never once used three short sentences in a
    # row. Every internal gate passed it at 89/100.
    _sk_channel = getattr(strategy, "skeleton_bounds_channel", "") or ""
    if _sk_channel and actual_ids == expected_ids:
        from omnicast.analytics.skeleton import skeleton_problems

        narration = "\n\n".join(s.narration for s in stories if s.narration)
        for problem in skeleton_problems(narration, _sk_channel):
            failures.append(_failure(
                "skeleton_out_of_bounds", problem, *actual_ids))

    # De-duplicate identical diagnostics without hiding which stories failed.
    unique: list[GateFailure] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for item in failures:
        key = item.code, tuple(item.story_ids)
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return GateReport(
        failures=unique,
        editorial_flags=editorial_flags,
        total_words=total_words,
        story_words=story_words,
    )


# A judge that files an impossible action as taste has not found a small problem;
# it has mislabelled a large one. These phrases are the judge's OWN words about its
# OWN finding, so matching them is severity calibration, not prose analysis.
_IMPOSSIBILITY_CLAIM_RE = re.compile(
    r"\b(?:physically|spatially|geometrically|causally|logically)\s+"
    r"(?:impossible|unclear|implausible|improbable|incoherent|inconsistent|"
    r"contradictory|unworkable)\b"
    r"|\bnot\s+(?:physically|spatially|causally)\s+possible\b"
    r"|\b(?:impossible|cannot\s+(?:happen|physically|fit|pass)|can'?t\s+(?:happen|fit|pass)|"
    r"could\s+not\s+have\s+(?:happened|fit|passed))\b"
    r"|\bno\s+(?:way|space|room|gap)\s+to\s+(?:pass|fit|get|squeeze)\b"
    r"|\bcontradicts?\s+(?:the\s+)?(?:established\s+|stated\s+|locked\s+)?"
    r"(?:geometry|geography|physics|dimensions|spatial\s+\w+)\b",
    re.I,
)


def promote_miscalibrated_issues(
    score: NarrativeScorecard,
    strategy: NamedChannelStrategy | None = None,
) -> NarrativeScorecard:
    """Promote a 'minor' whose own text asserts a physical/causal impossibility.

    The 2026-07-17 critic wrote that a man fills a fence gap shoulder-to-shoulder
    and the narrator rode "straight past his shoulder", called it "physically
    unclear", and filed it severity=minor / issue_kind=style. The compilation
    locked at 93. A judge may be wrong about whether an action is impossible; it
    may not be wrong about what "impossible" means for release. Grounding still
    applies: without the judge's own exact quote there is nothing to repair, so an
    unquoted claim stays minor rather than becoming an unfixable blocker.
    """
    if strategy is not None and not strategy.promote_impossibility_to_major:
        return score
    promoted: list[StoryIssue] = []
    for issue in score.story_issues:
        if (
            issue.severity == "minor"
            and issue.evidence_quote
            and _IMPOSSIBILITY_CLAIM_RE.search(issue.problem)
        ):
            issue = issue.model_copy(update={
                "severity": "major",
                "issue_kind": "contradiction",
                "promoted_from": "minor",
                "problem": (
                    "[severity corrected: an impossible physical/causal action is not a "
                    f"style note] {issue.problem}"
                ),
            })
        promoted.append(issue)
    return score.model_copy(update={"story_issues": promoted})


_TIME_SKIP_RE = re.compile(
    r"\b(the next (morning|day|night|evening|afternoon)|next (morning|day|night)|"
    r"(two|three|four|five|a few|several|some) (nights?|days?|evenings?|mornings?) (later|after)|"
    r"the (night|day|evening|morning) after|(a|one) week (later|after)|days later|"
    r"the (second|third|fourth|fifth|sixth) (night|day|evening)|that (same )?(night|evening) after|"
    r"later that (week|night)|by (the )?(next|second|third) (night|day)|"
    r"(when|after) (I|she|he) (came|got) back from|the following (night|day|morning))\b", re.I)


def _demote_cross_night_contradictions(score: "NarrativeScorecard",
                                       stories: list) -> "NarrativeScorecard":
    """A major 'contradiction' whose two quotes sit on either side of a time
    skip is the judge reading two nights as one scene. Demoted to minor so
    it cannot block a release; the note survives for the editor."""
    by_id = {st.story_id: st.narration for st in stories}
    changed = False
    out = []
    for issue in score.story_issues:
        text = by_id.get(issue.story_id, "")
        if (issue.severity in {"critical", "major"} and issue.issue_kind == "contradiction"
                and issue.evidence_quote and issue.anchor_quote and text):
            a = text.find(issue.anchor_quote)
            b = text.find(issue.evidence_quote)
            if a >= 0 and b >= 0 and a != b:
                between = text[min(a, b):max(a, b)]
                if _TIME_SKIP_RE.search(between):
                    issue = issue.model_copy(update={
                        "severity": "minor",
                        "problem": issue.problem + " [demoted: the two quotes are separated by a "
                                                   "time skip; different scenes are not a contradiction]"})
                    changed = True
        out.append(issue)
    if not changed:
        return score
    return score.model_copy(update={"story_issues": out})


_SELF_NEGATING_RE = re.compile(
    r"(no contradiction (was )?found|matches (this|the plan|the locked plan)( exactly)?|"
    r"within the allowed limit|not a (plot|logic|continuity) (break|defect|issue)|"
    r"is not egregious|this is consistent|no issue here|resolves the previous)", re.I)
_NO_CALL_OBJECTION_RE = re.compile(
    r"(fails? to (contact|call)|does not (call|contact)|never (calls?|contacts?)|without calling|"
    r"no (call|report) (is|was) made|did not call)", re.I)
_CALL_ON_PAGE_RE = re.compile(
    r"\b(call(ed|ing)?|dial(ed|ing)?|phon(ed|ing)|rang|reported?( it)?( to)?)\b[^.]{0,80}"
    r"\b(sheriff|911|non-?emergency|police|deput(y|ies)|dispatch(er)?|substation)\b", re.I)


def _demote_unfounded_editor_issues(issues: list, stories: list) -> list:
    """Live 02:25, 88/100: a 'major' that ended 'No contradiction found', and a
    'major' that she never called the sheriff, filed against a page on which
    she calls the sheriff's non-emergency line before the climax. Self-
    negating text, or a no-call objection when a call is on the page before
    the last third, is demoted to minor. Everything else stands."""
    by_id = {st.story_id: st.narration for st in stories}
    out = []
    for issue in issues:
        text = (issue.problem or "")
        sev = issue.severity
        if sev in {"critical", "major"}:
            if _SELF_NEGATING_RE.search(text):
                issue = issue.model_copy(update={"severity": "minor",
                    "problem": text + " [demoted: the objection negates itself]"})
            elif _NO_CALL_OBJECTION_RE.search(text):
                narr = by_id.get(issue.story_id, "")
                cut = int(len(narr) * 0.67)
                if narr and _CALL_ON_PAGE_RE.search(narr[:cut]):
                    issue = issue.model_copy(update={"severity": "minor",
                        "problem": text + " [demoted: a report beat is on the page before the climax]"})
        out.append(issue)
    return out


def content_can_lock(
    score: NarrativeScorecard,
    gate: GateReport,
    strategy: NamedChannelStrategy | None = None,
    *,
    critic_contract_valid: bool = True,
    story_compliance_valid: bool = True,
    final_editor_approved: bool = True,
    plan_audit_valid: bool = True,
    release_challenge_passed: bool = True,
) -> bool:
    strategy = strategy or NamedChannelStrategy(
        strategy_id="system_default", writer_rules="restrained narrative",
        critic_rules="skeptical content audit", annotation_rules="literal production metadata",
    )
    mins = (
        score.continuity_believability >= strategy.continuity_min,
        score.distinct_authentic_voices >= strategy.voice_min,
        score.dread_escalation >= strategy.dread_min,
        score.plausible_response >= strategy.plausible_response_min,
        score.structural_variety >= strategy.structural_variety_min,
        score.originality >= strategy.originality_min,
        score.ending_discipline >= strategy.ending_min,
    )
    unresolved_major = any(
        issue.severity in {"critical", "major"} for issue in score.story_issues
    )
    return (
        gate.passed
        and score.total_score >= strategy.approval_score
        and all(mins)
        and not score.critical_issues
        and not unresolved_major
        and critic_contract_valid
        and story_compliance_valid
        and final_editor_approved
        # A plan nobody could audit and an adversary nobody could reach are both
        # absences of evidence, and neither is evidence of quality.
        and plan_audit_valid
        and release_challenge_passed
    )


def _story_plan_fingerprint(plan: NarrativeStoryPlan) -> str:
    payload = json.dumps(
        plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _narration_sha256(story: StoryDraft) -> str:
    return hashlib.sha256(story.narration.encode("utf-8")).hexdigest()


def _canonical_quote(narration: str, quote: str) -> str | None:
    """Return the exact source bytes for a quote that differs only in
    whitespace or typography. Live 00:41: three judges in a row quoted
    \"the sheriff's substation\" with a straight apostrophe against a
    narration holding a curly one; 'found 0 times' voided the review and
    the attempt scored 0/100 on a text every judge had approved before."""
    parts = re.split(r"\s+", (quote or "").strip())
    if not parts or not all(parts):
        return None
    def _part_pattern(part: str) -> str:
        out = []
        for ch in part:
            if ch in "'\u2018\u2019":
                out.append("['\u2018\u2019]")
            elif ch in '"\u201c\u201d':
                out.append('["\u201c\u201d]')
            elif ch in "-\u2013\u2014":
                out.append("[-\u2013\u2014]")
            else:
                out.append(re.escape(ch))
        return "".join(out)
    pattern = r"\s+".join(_part_pattern(part) for part in parts)
    matches = list(re.finditer(pattern, narration))
    if len(matches) != 1:
        return None
    match = matches[0]
    return narration[match.start():match.end()]


def _canonicalize_story_compliance(
    story: StoryDraft, review: StoryComplianceReview
) -> StoryComplianceReview:
    beats: list[StoryBeatCheck] = []
    for item in review.beats:
        evidence = _canonical_quote(story.narration, item.evidence_quote)
        anchor = _canonical_quote(story.narration, item.anchor_quote)
        beats.append(item.model_copy(update={
            "evidence_quote": evidence or item.evidence_quote,
            "anchor_quote": anchor or item.anchor_quote,
        }))
    return review.model_copy(update={
        "beats": beats,
        "plan_facts_quote": (
            _canonical_quote(story.narration, review.plan_facts_quote)
            or review.plan_facts_quote
        ),
        "evidence_quote": (
            _canonical_quote(story.narration, review.evidence_quote)
            or review.evidence_quote
        ),
    })


def _canonicalize_issue_quotes(
    issues: list[StoryIssue], stories: list[StoryDraft]
) -> list[StoryIssue]:
    """Repair whitespace-only quote drift in forensic issues before validation.

    Judges cite narration through a JSON round-trip that sometimes collapses or
    pads whitespace; compliance reviews already get this repair, and without it
    a genuinely grounded review dies on 'quote not found' (observed live
    2026-07-17: three clean 93-100 compilations blocked only by the final
    editor's contract)."""
    story_map = {story.story_id: story.narration for story in stories}
    fixed: list[StoryIssue] = []
    for issue in issues:
        narration = story_map.get(issue.story_id)
        if narration is None:
            fixed.append(issue)
            continue
        fixed.append(issue.model_copy(update={
            "evidence_quote": (
                _canonical_quote(narration, issue.evidence_quote) or issue.evidence_quote
            ),
            "anchor_quote": (
                _canonical_quote(narration, issue.anchor_quote) or issue.anchor_quote
            ),
        }))
    return fixed


def validate_story_compliance(
    plan: NarrativeStoryPlan,
    story: StoryDraft,
    review: StoryComplianceReview,
) -> list[str]:
    """Verify audit identity, coverage and grounding without judging prose itself."""
    errors: list[str] = []
    if review.story_id != story.story_id or story.story_id != plan.story_id:
        errors.append("story compliance has the wrong story_id")
    if review.plan_fingerprint != _story_plan_fingerprint(plan):
        errors.append("story compliance has the wrong plan fingerprint")
    if review.narration_sha256 != _narration_sha256(story):
        errors.append("story compliance has the wrong narration SHA256")
    ids = [item.beat_id for item in review.beats]
    if ids != list(_REQUIRED_BEAT_IDS):
        errors.append(
            "story compliance beat coverage/order must be exactly "
            + ", ".join(_REQUIRED_BEAT_IDS)
        )

    requirements = {
        "ordinary_setup": plan.setup_requirement,
        "threat_confirmation": plan.threat,
        "decision_action": plan.escape_action,
        "completed_escape": plan.escape_action,
        "completed_ending": plan.ending_shape,
    }

    spans: list[tuple[int, int]] = []
    used_quotes: set[str] = set()
    for item in review.beats:
        if item.locked_requirement != requirements[item.beat_id]:
            errors.append(f"{item.beat_id} does not echo its exact locked requirement")
        quote = item.evidence_quote if item.status != "missing" else item.anchor_quote
        if not quote:
            errors.append(f"{item.beat_id} requires an exact evidence/anchor quote")
            continue
        count = story.narration.count(quote)
        if count != 1:
            errors.append(
                f"{item.beat_id} quote must be exact and unique in the named story "
                f"(found {count} times): {quote[:120]!r}"
            )
            continue
        if len(_words(quote)) < 4:
            errors.append(f"{item.beat_id} quote is too short to ground the judgment")
        normalized_quote = " ".join(quote.split())
        if normalized_quote in used_quotes:
            errors.append("story compliance requires distinct evidence for every beat")
        used_quotes.add(normalized_quote)
        start = story.narration.index(quote)
        spans.append((start, start + len(quote)))
        if item.status in {"partial", "missing"} and not item.anchor_quote:
            errors.append(f"{item.beat_id} omission requires an exact insertion anchor")
        elif item.status == "partial" and story.narration.count(item.anchor_quote) != 1:
            errors.append(f"{item.beat_id} insertion anchor must be exact and unique")
    if len(spans) == len(review.beats) and any(
        current_start < previous_end
        for (_previous_start, previous_end), (current_start, _current_end)
        in zip(spans, spans[1:], strict=False)
    ):
        errors.append(
            "story compliance beat evidence must be strictly ordered and non-overlapping"
        )

    for name, status, quote in (
        ("plan facts", review.plan_facts_status, review.plan_facts_quote),
        ("evidence budget", review.evidence_budget_status, review.evidence_quote),
    ):
        needs_quote = status in {"contradicted", "violated"}
        if needs_quote and (not quote or story.narration.count(quote) != 1):
            errors.append(f"{name} failure requires an exact unique quote")
    if review.evidence_budget_status == "unclear":
        errors.append("evidence budget status must be resolved, not unclear")
    return errors


def story_compliance_issues(
    review: StoryComplianceReview,
) -> list[StoryIssue]:
    """Convert constrained statuses to deterministic, grounded repair issues."""
    issues: list[StoryIssue] = []
    for item in review.beats:
        if item.status == "complete":
            continue
        omission = item.status in {"partial", "missing"}
        issues.append(StoryIssue(
            story_id=review.story_id,
            severity="major",
            problem=(
                f"Required beat {item.beat_id} is {item.status}: {item.explanation}"
            ),
            repair_instruction=(
                f"Complete only the locked {item.beat_id} beat without changing clean facts."
            ),
            issue_kind="omission" if omission else "contradiction",
            evidence_quote="" if omission else item.evidence_quote,
            anchor_quote=item.anchor_quote if omission else "",
            viewer_impact="The locked story action is incomplete or contradicted on the page.",
            issue_id=f"{review.story_id}:{item.beat_id}",
        ))
    if review.plan_facts_status == "contradicted":
        issues.append(StoryIssue(
            story_id=review.story_id, severity="major",
            problem=f"Locked plan facts are contradicted: {review.plan_facts_explanation}",
            repair_instruction="Restore the locked geography, threat position, and causal facts.",
            issue_kind="contradiction", evidence_quote=review.plan_facts_quote,
            viewer_impact="The physical sequence no longer matches its commissioned plan.",
            issue_id=f"{review.story_id}:plan_facts",
        ))
    if review.evidence_budget_status == "violated":
        issues.append(StoryIssue(
            story_id=review.story_id, severity="major",
            problem=f"Evidence allowance is violated: {review.evidence_explanation}",
            repair_instruction="Remove only unplanned aftermath corroboration.",
            issue_kind="style", evidence_quote=review.evidence_quote,
            viewer_impact="Extra proof makes the account feel manufactured.",
            issue_id=f"{review.story_id}:evidence_budget",
        ))
    return issues


def story_compliance_approved(review: StoryComplianceReview) -> bool:
    return (
        all(item.status == "complete" for item in review.beats)
        and review.plan_facts_status != "contradicted"
        and review.evidence_budget_status == "preserved"
    )


def _story_failure_count(report: GateReport, story_id: str) -> int:
    return sum(story_id in failure.story_ids for failure in report.failures)


# Plan-shape diagnostics cannot be fixed by rewriting one story's prose.
_UNRECOVERABLE_GATE_CODES = frozenset({
    "story_count_or_order", "plan_voice_diversity", "plan_threat_diversity",
    "plan_ending_diversity", "plan_threat_mix",
})
# The compilation total names one story for targeting, but is not attributable to
# that story alone: it triggers a recovery yet is excluded from the acceptance
# count, so a total-length-only story ties at zero and must win on length instead.
# LENGTH IS WHAT THE ACCOUNT NEEDS. The operator's standing rule: never force a
# word count; a premise that needs setup is ruined by a cap and a thin one is
# ruined by padding. The plan's target is the planner's estimate and the
# writer's shape. The only length gates are floors that decide whether it is
# a video at all: about eight minutes spoken in total, and no story so short
# it cannot hold a ladder.
GENRE_FLOOR_TOTAL_WORDS = 1200
GENRE_FLOOR_STORY_WORDS = 600
_COMPILATION_LEVEL_GATE_CODES = frozenset({"total_length"})


def _story_recovery_ids(plan: CompilationPlan, gate: GateReport) -> set[str]:
    expected = {item.story_id for item in plan.stories}
    ids: set[str] = set()
    for failure in gate.failures:
        if failure.code in _UNRECOVERABLE_GATE_CODES:
            continue
        ids.update(sid for sid in failure.story_ids if sid in expected)
    return ids


def _story_attributable_failures(gate: GateReport, story_id: str) -> int:
    return sum(
        story_id in failure.story_ids
        for failure in gate.failures
        if failure.code not in _UNRECOVERABLE_GATE_CODES
        and failure.code not in _COMPILATION_LEVEL_GATE_CODES
    )


def _story_count_for(brief) -> int:
    """How many stories a topic with no number in its title should carry.

    Scaled to the room available rather than fixed, so the same engine can make
    one long account or four short ones. The bands are the genre's own: 86
    competitor compilations that state a count give each story a median 1,492
    words, so this asks for roughly that much per story and lets a very short
    brief be a single account rather than a set of fragments.
    """
    words = spoken_word_floor(getattr(brief, "target_duration_min", 0))
    return max(1, min(5, round(words / 1500)))


# WHAT MAKES A RUNG FRIGHTENING, measured rather than assumed. Across 2,320
# escalation sentences in 147 competitor scripts, 36% have the threat ACTING
# while the narrator is present (a tap on the glass, a handle turning, a
# figure that stays) and 3% are traces found afterwards (a woodpile
# restacked, a key missing). The first two accepted plans on this channel
# were 0/7 and 1/7 present-tense and 3/7 trace: detective stories, not
# horror. The auditor judged plausibility and freshness and was never asked
# about fear, so it passed them.
# A rung is a TRACE when the narrator arrives and sees a state. The frame
# decides, not the vocabulary: "its hook-and-eye unlatched, swings inward
# and his voice calls out" is the threat arriving.
_RUNG_TRACE_STRONG_RE = re.compile(
    r"\b(had been|was gone|were gone|gone from|goes missing|"
    r"the (next|following) (morning|afternoon|evening|day)|(next|following) (morning|afternoon)|"
    r"one morning|when (s?he|they|I) (arrives?|returns?|comes? back|gets? (back|home)|wakes?)|"
    r"on (arriving|returning)|(comes?|came|gets?|got) (back|home) (from|to)|"
    r"already (at|on|in|up|off|lit|glowing|open|standing)|though (s?he|they|I) (never|remembers?|swears?|is sure|had|locked|latched|left)|despite|"
    r"sits? (a few|an? inch)|off its (usual )?mark|cushion flattened|"
    r"that wasn'?t there|different(ly)? than|(isn'?t|aren'?t|wasn'?t|weren'?t) where|"
    r"(when|as) (s?he|they|I) (gets?|got) (back|home)|the kind of thing a \w+ could explain|"
    r"(listing|lists) the exact|a note (on|listing|taped|under))\b", re.I)
_RUNG_TRACE_WEAK_RE = re.compile(
    r"\b(found|finds?|discover\w*|missing|re-?arranged|restacked|unlatched|unlocked|propped|wedged|prints?|tracks? in|tread|"
    r"out of order|rubber band off|unscrewed|out of place|moved|shifted|wrong way)\b", re.I)
# An actor the narrator can see or hear ...
_RUNG_AGENT_RE = re.compile(
    r"\b(he|him|his|she|her|they|it|someone|somebody|nobody|"
    r"an? (man|woman|figure|shape|hand|face|voice|person|stranger|calm voice|knuckle-knock|knock|tap|sedan|car|truck|pickup)|"
    r"the (man|woman|figure|shape|hand|face|voice|stranger|person|driver|thing|same car|car|truck|pickup)|"
    r"(man|woman|figure|shape|hand|face|voice|stranger)'?s|headlights|[A-Z][a-z]+)\b")
# ... doing something, now.
_RUNG_ACTION_RE = re.compile(
    r"\b(steps?|stepping|stepped|crosses|crossing|comes?|coming|arrives?|walks?|walking|moves?|moving|"
    r"pushes|pushing|pulls?|pulling|grips?|gripping|grabs?|jiggles?|jiggling|rattles?|rattling|wrenches|"
    r"turns?|turning|twists?|slides?|sliding|eases?|opens?|opening|gives?|cracks?|knocks?|knocking|raps?|"
    r"taps?|tapping|scratches|scrapes?|says?|saying|states?|recites?|asks?|calls?|calling|whispers?|speaks?|"
    r"tells?|mentions?|insist\w*|names?|stands?|standing|stops?|waits?|stays?|watches|watching|staring|"
    r"stares?|looks? (in|at|through)|linger\w*|leans?|reaches|blocks?|climbs?|forces?|breaks?|kicks?|"
    r"bangs?|pounds?|presses|holds?|follows?|crouches|gets?|puts?|plants?|swings?|idles?|idling|"
    r"circl\w*|returns?|keys? in|appears?|emerges?|does not (stop|leave|move)|doesn'?t (stop|leave|move)|"
    r"won'?t (stop|leave)|lurches|closes over|works into|lifts|begins|tests?|testing)\b", re.I)
_RUNG_PERCEIVE_RE = re.compile(
    r"\b(hears?|hearing|heard|sees?|seeing|feels?|watches|smells?|footsteps?|breathing|"
    r"gravel crunch\w*|crunch(es|ing)|"
    r"(handle|knob|latch|sash|door|window|slider|frame|chair|curtain).{0,30}(turns?|rattles?|rattling|jiggles?|"
    r"moves?|slides?|gives?|wrenched|forced|creaks?|whines?|cracks?|eases? open|swings? (inward|open)|"
    r"lurches|scrapes?|takes? a|begins|lifts)|beam (crosses|sweeps)|"
    r"(while|as) (s?he|they|I) (stands?|sits?|lies?|is|am|are|carr\w+|glance\w*)|"
    r"(knock|tap|rap)s? (lands?|raps?|comes?|against|on|at) )", re.I)


def rung_kind(rung: str) -> str:
    """'trace' when the narrator arrives and sees a state (or a state word
    with nothing happening); 'present' when an actor does something now or
    the narrator perceives it happening; else 'other'."""
    text = rung or ""
    if _RUNG_TRACE_STRONG_RE.search(text):
        return "trace"
    happening = bool(_RUNG_PERCEIVE_RE.search(text)) or (
        bool(_RUNG_AGENT_RE.search(text)) and bool(_RUNG_ACTION_RE.search(text)))
    if happening:
        return "present"
    if _RUNG_TRACE_WEAK_RE.search(text):
        return "trace"
    return "other"


def ladder_fear_problems(plan) -> list[str]:
    """Ladders that cannot frighten, caught before any paid call.

    A rung the narrator is not present for costs nothing and scares no one.
    Traces are allowed early — that is how a real account starts — but the
    back half of the ladder has to be happening TO the narrator, and the last
    three rungs must be, without exception.
    """
    out: list[str] = []
    for item in getattr(plan, "stories", ()) or ():
        rungs = [r for r in (getattr(item, "escalation_ladder", None) or []) if str(r).strip()]
        if len(rungs) < 4:
            continue
        kinds = [rung_kind(r) for r in rungs]
        present = sum(k == "present" for k in kinds)
        last3 = kinds[-3:]
        sid = getattr(item, "story_id", "?")
        if present * 2 < len(rungs):
            out.append(
                f"{sid}: only {present} of {len(rungs)} rungs have the threat acting "
                "while the narrator is present; competitors run ~36% present-tense "
                "and ~3% trace. Traces found afterwards are a detective story. Make "
                "the back half of the ladder happen TO the narrator, closer each time.")
        elif any(k == "trace" for k in last3):
            out.append(
                f"{sid}: a trace (found afterwards) sits in the last three rungs. The "
                "end of the ladder must be present tense: the threat acting, the "
                "narrator there, the distance closing.")
    return out


# DISTANCE CLOSES IN STEPS NOBODY CAN SKIP. Plan v1 of "The Man Who Knew
# Her Medicine" went from a polite daytime question at the door straight to
# the handle being wrenched that night: present tense both, so the fear gate
# passed it, and it read as a jump cut. The genre's ladders approach
# (heard or seen near, stopping outside), then contact (a hand on the
# structure), then breach (forcing in). The first breach must be preceded
# by an approach.
_RUNG_BREACH_RE = re.compile(
    r"\b(wrench|forc(e|ed|ing)|pr(y|ied|ying)|kick(s|ed)? (the|at)|"
    r"(handle|knob|door|sash|window).{0,30}\b(turn|rattl|wrench|shak|jerk|forc|pull|pr[iy])\w*|"
    r"(inside|in) the (house|room|hall|kitchen|cabin|trailer)|climb(s|ed|ing)? (in|through)|"
    r"com(es|ing) through|breaks? (the )?(glass|window|door))",
    re.I)
_RUNG_APPROACH_RE = re.compile(
    r"\b(footsteps?|gravel|crunch\w*|stops? (outside|at|just|right|by)|stand(s|ing)? (outside|at|by|under|beneath)|"
    r"outside the (door|window|glass)|(pauses?|waits?) (outside|at|by)|circl(es|ing)|"
    r"walk(s|ing) (along|around|past|up)|com(es|ing) (up|along|around|closer)|"
    r"(tap|knock)(s|ed|ing)? (on|at) the (glass|window)|breath\w* (at|against|outside)|"
    r"shadow (crosses|passes|moves)|silhouette)\b",
    re.I)


def ladder_order_problems(plan) -> list[str]:
    """The first rung that forces the structure must follow a rung that
    brings the threat near and lets it wait there. Without that step the
    ladder is a jump cut, and a jump cut is not fear."""
    out: list[str] = []
    for item in getattr(plan, "stories", ()) or ():
        rungs = [str(r) for r in (getattr(item, "escalation_ladder", None) or []) if str(r).strip()]
        if len(rungs) < 4:
            continue
        sid = getattr(item, "story_id", "?")
        first_breach = next((i for i, r in enumerate(rungs) if _RUNG_BREACH_RE.search(r)), None)
        if first_breach is None:
            continue
        if not any(_RUNG_APPROACH_RE.search(r) for r in rungs[:first_breach]):
            out.append(
                f"{sid}: rung {first_breach + 1} forces the structure with no earlier rung "
                "bringing the threat NEAR and letting it wait there (footsteps that stop "
                "outside the door, a shape standing at the glass). Distance closes in "
                "steps nobody can skip: approach, then contact, then breach.")
    return out


# THE ESCAPE IS SOMETHING THE NARRATOR DID. Plan v1's threat stopped when a
# neighbour's headlights happened to sweep the drive. A rescue that arrives
# on its own is a coincidence; the genre's escapes are an action taken
# (lights thrown, a door locked, a call made, a run to the truck) and help
# that the narrator CALLED arriving.
_ESCAPE_COINCIDENCE_RE = re.compile(
    r"\b(happens? to|happened to|just then|luckily|by (sheer )?(luck|chance)|"
    r"neighbou?r'?s? (headlights|car|truck|lights)|someone (pulls|drives|comes) (up|in|by)|"
    r"a (car|truck|vehicle) (pulls|drives|turns) (in|up|into)|passer-?by|"
    r"(headlights|lights) (sweep|hit|come|appear)|out of nowhere|for no reason|"
    r"(gives|gave) up|loses? interest|wanders? (off|away)|simply (leaves|stops)|"
    # Codex on the run-15 plan: "the prying stops as gravel crunches away" —
    # nothing the narrator did made him leave.
    r"(stops?|stopped|ceases?|quits?) (as|when|while|and) .{0,40}\b(away|leaves?|gone|crunch\w*|fades?|retreats?)|"
    r"(footsteps?|gravel|engine|truck|car) .{0,20}\b(away|fad\w+|recedes?))\b",
    re.I)
_ESCAPE_CALLED_HELP_RE = re.compile(
    r"\b(deput(y|ies)|police|officers?|sheriff|troopers?|cruiser|squad car|911|dispatcher|dispatch)\b", re.I)
_ESCAPE_DISENGAGE_RE = re.compile(
    r"\b(happens? to|happened to|just then|luckily|by (sheer )?(luck|chance)|out of nowhere|for no reason|"
    r"(gives|gave) up|loses? interest|wanders? (off|away)|simply (leaves|stops)|"
    r"neighbou?r'?s? (headlights|car|truck|lights)|passer-?by|someone (pulls|drives|comes) (up|in|by)|"
    r"(stops?|stopped|ceases?|quits?) (as|when|while|and) .{0,40}\b(away|leaves?|gone|crunch\w*|fades?|retreats?))\b", re.I)
_ESCAPE_AGENCY_RE = re.compile(
    r"\b(lock|bolt|throw|flip|switch|shout|yell|scream|call|dial|run|sprint|climb|drive|floor|slam|block|"
    r"wedge|barricade|jam|drag|shove|grab|flee|revers|back|pull|pedal|walk|leave|hang|honk|flash|"
    r"swerv|accelerat|turn|cross|hide|crawl|duck|wait|stay|hold|press|push|kick|swing|jump|vault)\w*",
    re.I)


def escape_agency_problems(plan) -> list[str]:
    out: list[str] = []
    for item in getattr(plan, "stories", ()) or ():
        text = str(getattr(item, "escape_action", "") or "")
        if len(text.split()) < 5:  # placeholders and fragments are not judged on agency
            continue
        sid = getattr(item, "story_id", "?")
        hit = _ESCAPE_COINCIDENCE_RE.search(text)
        # Help the narrator CALLED arriving is the gate's own definition of an
        # earned escape. Run 15, repair round 2: 'headlights sweep up the drive,
        # the prying stops, and a deputy arrives nine minutes after the call'
        # was thrown away as a coincidence. Arrival words are exempt when the
        # called help is named; disengagement words never are.
        if hit and _ESCAPE_CALLED_HELP_RE.search(text) and not _ESCAPE_DISENGAGE_RE.search(text):
            hit = None
        if hit:
            out.append(
                f"{sid}: escape_action ends on a coincidence ({hit.group(0)!r}). The threat "
                "stops because of something the narrator DID, or because help the narrator "
                "CALLED arrives. Name the action and, if help comes, who called it and how long "
                "it took.")
        elif not _ESCAPE_AGENCY_RE.search(text):
            out.append(
                f"{sid}: escape_action names no action by the narrator. Locks, lights, a call, "
                "a run to the truck: the narrator must DO something that changes the geometry.")
    return out


_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "a": 1, "an": 1}
_SPAN_RE = re.compile(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an)\s+(days?|nights?|weeks?)\b", re.I)


def _span_nights(text: str) -> int:
    total = 0
    for num, unit in _SPAN_RE.findall(text or ""):
        n = int(num) if num.isdigit() else _NUM_WORDS.get(num.lower(), 0)
        total += n * (7 if unit.lower().startswith("week") else 1)
    return total


def night_arithmetic_problems(plan) -> list[str]:
    """Codex, twice: 'mailbox left unlocked three days' then 'two nights later'
    inside a four-night stay. The auditor was told to count and did not.
    Conservative: only the stay length stated in hook_timeline, against the
    sum of explicit spans in the ladder."""
    out: list[str] = []
    for item in getattr(plan, "stories", ()) or ():
        ledger = getattr(item, "continuity_ledger", None) or []
        hook = next((l for l in ledger if str(l).lower().startswith("hook_timeline")), "")
        stay = _span_nights(hook)
        if not stay:
            continue
        used = sum(_span_nights(r) for r in (getattr(item, "escalation_ladder", None) or []))
        if used > stay:
            out.append(
                f"{getattr(item, 'story_id', '?')}: the ladder spends {used} days/nights "
                f"('{_SPAN_RE.search(hook).group(0) if _SPAN_RE.search(hook) else hook[:40]}' is the "
                "whole stay). Count the nights: shorten the spans or lengthen the stay in hook_timeline.")
    return out


_GENERIC_SCENE = {
    "door", "window", "house", "room", "night", "kitchen", "porch", "yard", "drive", "driveway",
    "hall", "hallway", "bedroom", "bathroom", "uncle", "aunt", "mother", "father", "home", "place",
    "time", "week", "morning", "evening", "something", "someone", "outside", "inside", "never",
    "still", "remember", "anymore", "since", "that", "this", "with", "from", "there", "where",
    "when", "what", "then", "than", "just", "back", "front", "side", "after", "before", "while",
    "first", "last", "into", "onto", "over", "under", "through", "across", "around", "again",
    "behind", "beside", "above", "below", "toward", "towards", "against", "between", "along",
    "until", "every", "about", "being", "there", "their", "them", "they", "have", "were", "been",
    "would", "could", "should", "once", "hard", "slow", "slowly", "loud", "quiet", "dark", "light",
    "hour", "minute", "second", "year", "summer", "winter", "spring", "autumn", "october",
    "start", "started", "starts", "begin", "began", "stop", "stopped", "turn", "turned", "look", "looked",
    "hear", "heard", "sound", "sounds", "thing", "things", "come", "came", "going", "went", "made", "make",
    "mudroom", "attic", "cellar", "basement", "garage", "barn", "shed", "closet", "laundry",
    "stairs", "stair", "staircase", "landing", "pantry", "trailer", "cabin", "farmhouse",
    "apartment", "upstairs", "downstairs", "nights", "night", "days", "week", "weeks", "alone",
    "someone", "knock", "knocked", "name", "nickname", "uncle", "aunt",
}


def _stem(word: str) -> str:
    w = re.sub(r"'s$", "", word.lower()).strip("'")
    for suf in ("ing", "ed", "es", "s"):
        if suf == "s" and w.endswith("ss"):
            continue
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[:-len(suf)]
    return {"said": "say", "says": "say", "saying": "say"}.get(w, w)


_COLD_OPEN_HOOK_RE = re.compile(
    r"\b(never|anymore|still|can'?t|won'?t|haven'?t|don'?t|to this day|"            # a lasting change
    r"(19|20)\d\d|\d{1,2}\s*(a\.?m\.?|p\.?m\.?|o'clock)|midnight|\d{1,2} years old|when i was \w+|"  # an anchor
    r"i was (\d{1,2}|(twenty|thirty|forty|fifty|sixty)(-\w+)?|nineteen|eighteen|seventeen|sixteen)\b|"
    r"stopped|started|quit|kept|keep|sleep\w* with|ever since|now|"                 # a habit that changed
    r"man|woman|someone|somebody|stranger|figure|shape|voice|knock\w*|footsteps?|handle|"
    r"tap(ped|ping)?|scratch\w*|breath\w*|whisper\w*|watch\w*|follow\w*|stood|standing|"
    r"screen|glass|lock\w*|bolt\w*|deadbolt|latch\w*|police|deputy|911|sheriff|"
    r"hanging open|swinging|wide open|(was|were) gone|had been moved|wasn'?t where|"   # an object that changed
    r"padlock|chain|inside with me|in the house|in the room)\b", re.I)


_VOICE_TIC_RE = re.compile(
    r"(repeats? (the|a|his|her) (hedge|phrase|word|line|saying)|repeats? ['\"\u2018\u2019]|catchphrase|verbal tic|\btic\b|"
    r"always (says|calls|refers to)|instead of (a |his |her |their )?name|by comparison to (his|her|their)|"
    r"compar\w+ (everything|people and things|people|things) to)", re.I)


def voice_tic_problems(plan) -> list[str]:
    """Nobody in the corpus performs a character. Voice rules that install a
    catchphrase, a repeated hedge, or a comparison habit read as a writer
    doing a voice; the genre's voice is plain, dated, reasoning out loud."""
    out = []
    for item in getattr(plan, "stories", ()) or ():
        rules = str(getattr(item, "voice_rules", "") or "")
        hit = _VOICE_TIC_RE.search(rules)
        if hit:
            out.append(f"{getattr(item, 'story_id', '?')}: voice_rules installs a performed tic "
                       f"({hit.group(0)!r}). The corpus voice is plain: exact times, reasoning out "
                       "loud, at most one image. Replace with rules about WHAT the narrator notices "
                       "and how they reason, not a catchphrase.")
    return out


def cold_open_hook_problems(plan) -> list[str]:
    """The spoiler gate alone produced 'That week I house-sat my uncle's
    farmhouse, I learned our mailbox had been sitting unlocked for days':
    no payoff given away, and no reason to keep watching. A cold open
    carries a lasting change, an anchor in time, or a sign that someone
    came."""
    cold = (getattr(plan, "cold_open", "") or "").strip()
    if not cold:
        return []
    if _COLD_OPEN_HOOK_RE.search(cold):
        return []
    return ["story_1: cold_open has no hook: no lasting change ('I never ... anymore', 'I still'), "
            "no anchor (a year, an hour, an age) and no sign that someone came (a man, a voice, a "
            "knock, a handle, a lock). It sells nothing. Keep the payoff hidden, but give the "
            "viewer the fear."]


def cold_open_spoiler_problems(plan) -> list[str]:
    """Codex, twice: the cold open gave away 'his nickname through the glass',
    the rung-five payoff. A cold open that repeats a three-word run from the
    last two rungs is telling the ending first."""
    cold = re.findall(r"[a-z']+", (getattr(plan, "cold_open", "") or "").lower())
    if len(cold) < 3:
        return []
    cold_tri = {tuple(cold[i:i + 3]) for i in range(len(cold) - 2)}
    out: list[str] = []
    for item in getattr(plan, "stories", ()) or ():
        rungs = [str(r) for r in (getattr(item, "escalation_ladder", None) or []) if str(r).strip()]
        if len(rungs) < 4:
            continue
        tail = " ".join(rungs[-2:]).lower()
        words = re.findall(r"[a-z']+", tail)
        tail_tri = {tuple(words[i:i + 3]) for i in range(len(words) - 2)}
        shared = [" ".join(t) for t in cold_tri & tail_tri
                  if not all(w in {"the", "a", "an", "of", "in", "on", "at", "to", "and", "his", "her", "my", "it", "that"} for w in t)]
        # Paraphrase: Codex three times on 'said his nickname through the glass'
        # vs the rung 'a voice says Boot ... rap the glass'. Content words that
        # live ONLY in the last two rungs (not the setup half) and recur in
        # the cold open are the payoff being told first. Generic location
        # nouns do not count; two such words do.
        head = " ".join(rungs[:-2]).lower()
        head_stems = {_stem(w) for w in re.findall(r"[a-z']+", head)}
        tail_stems = {_stem(w) for w in words if len(w) >= 4} - head_stems - _GENERIC_SCENE
        # The object that changed belongs to the ending; naming it is the rule,
        # not the spoiler ('I still check that mudroom latch').
        ending = (getattr(item, "ending_shape", "") or "").lower()
        ending_stems = {_stem(w) for w in re.findall(r"[a-z']+", ending)}
        cold_stems = {_stem(w) for w in cold if len(w) >= 4} - _GENERIC_SCENE - ending_stems
        payoff = sorted(cold_stems & tail_stems)
        strong = [w for w in payoff if len(w) >= 5]
        if not shared and (len(payoff) >= 2 or strong):
            shared = [" + ".join(payoff[:3])]
        if shared:
            out.append(
                f"{getattr(item, 'story_id', '?')}: cold_open repeats the last rungs "
                f"({shared[0]!r}). The cold open sells the night, not the payoff: name the "
                "place, the fear or the object that changed, never the last rung's action.")
    return out


def narrator_pronoun_conflicts(plan) -> list[str]:
    """Stories whose narrator changes gender between plan fields.

    Live 2026-08-04: a plan described its narrator as "He drives … I've hauled"
    and then wrote "She backs" into escape_action. plan_audit caught it, but
    that spent a paid audit call and one of only two attempts on a
    contradiction nobody needed judgement to see.

    Deliberately narrow. escape_action legitimately mentions the threat, who in
    this genre is usually a man, so this fires only when each side is
    internally unambiguous and the two disagree. A false positive here blocks
    generation outright, which is worse than the bug it would catch.
    """
    # Word boundaries are load-bearing: without them "he" matches inside
    # "the", every field reads as both genders, and the check silently
    # never fires. A shell heredoc once replaced these two escapes with
    # literal 0x08 bytes, which looked fine and disabled the check.
    def _gender(text: str, subject_only: bool = False) -> set[str]:
        low = f" {(text or '').lower()} "
        found = set()
        # escape_action is judged on SUBJECT pronouns only. Run 15's repaired
        # plan read 'the man hears her say deputies are close' — 'her' was the
        # dispatcher — and the gate threw away the best plan of the day.
        male = r"\b(he)\b" if subject_only else r"\b(he|him|his)\b"
        female = r"\b(she)\b" if subject_only else r"\b(she|her|hers)\b"
        if re.search(male, low):
            found.add("male")
        if re.search(female, low):
            found.add("female")
        return found

    out: list[str] = []
    for item in getattr(plan, "stories", ()) or ():
        who = _gender(getattr(item, "narrator_profile", "")) | _gender(
            getattr(item, "voice_seed", ""))
        act = _gender(getattr(item, "escape_action", ""), subject_only=True)
        if len(who) == 1 and len(act) == 1 and who != act:
            out.append(
                f"{getattr(item, 'story_id', '?')}: narrator is described as "
                f"{next(iter(who))} but escape_action uses "
                f"{next(iter(act))} pronouns; one narrator, one gender")
    return out


def _gate_errors_as_issues(errors: list[str]) -> list["PlanIssue"]:
    """Deterministic gate errors ('story_1: escape_action ends on a coincidence
    ...') as typed, story-scoped MAJOR issues, so _repair_plan — which repairs
    only what audit.issues names — can act on them. Errors without a story
    prefix are compilation-level and are left out (repair will decline)."""
    out = []
    for err in errors:
        m = re.match(r"^(story_\d+):\s*(.*)$", err.strip(), re.S)
        if not m:
            continue
        out.append(PlanIssue(
            story_id=m.group(1),
            category="cold_open" if "cold_open" in m.group(2) else "gate", severity="major",
            problem=m.group(2).strip(), plan_fix=m.group(2).strip(),
            knowledge_scope="universal", confidence=1.0))
    return out


def _changed_fields(before: "CompilationPlan", after: "CompilationPlan") -> dict[str, list[str]]:
    """Per story, the plan fields a repair actually changed."""
    out: dict[str, list[str]] = {}
    prev = {item.story_id: item.model_dump() for item in before.stories}
    for item in after.stories:
        old = prev.get(item.story_id)
        if old is None:
            out[item.story_id] = ["(new story)"]
            continue
        new = item.model_dump()
        changed = [k for k in new if new.get(k) != old.get(k)]
        if changed:
            out[item.story_id] = changed
    return out


def _issue_sig(issue: "PlanIssue") -> str:
    return " ".join((issue.evidence_quote or issue.problem or "").split()).lower()[:80]


def _demote_goalpost_moves(audit: "PlanAuditResult", raised_keys: set,
                           changed: dict[str, list[str]],
                           candidate: "CompilationPlan | None" = None) -> "PlanAuditResult":
    """A NEW major complaint, in a category already answered, that quotes the
    text the repair just wrote is a moved goalpost: demoted to minor. A new
    complaint about an unchanged field is a real objection and stands. If
    nothing major is left, the audit is valid."""
    changed_text: dict[str, str] = {}
    if candidate is not None:
        for item in candidate.stories:
            fields = changed.get(item.story_id) or []
            data = item.model_dump()
            changed_text[item.story_id] = " ".join(
                " ".join(map(str, v)) if isinstance(v, list) else str(v)
                for k, v in data.items() if k in fields).lower()
    kept, demoted = [], []
    for issue in audit.issues:
        key = (issue.story_id, issue.category)
        # The SAME complaint again means unresolved: still blocking. A NEW
        # complaint in an already-answered category is the moved goalpost.
        seen = raised_keys.get(key) if isinstance(raised_keys, dict) else (set() if key in raised_keys else None)
        quote = " ".join((issue.evidence_quote or "").split()).lower()
        about_repaired_text = (
            bool(quote) and quote in changed_text.get(issue.story_id, "")
            if candidate is not None else bool(changed.get(issue.story_id)))
        if (issue.severity in {"critical", "major"} and issue.category != "gate"
                and seen is not None and _issue_sig(issue) not in seen
                and about_repaired_text):
            demoted.append(issue.model_copy(update={"severity": "minor"}))
        else:
            kept.append(issue)
    if not demoted:
        return audit
    blocking = [i for i in kept if i.severity in {"critical", "major"}]
    if blocking:
        return audit.model_copy(update={"issues": kept + demoted,
                                        "blockers": [_format_plan_issue(i) for i in blocking]})
    return audit.model_copy(update={"status": "valid", "blockers": [], "issues": kept + demoted,
                                    "summary": audit.summary + " (repeat objections demoted)"})


def _reaudit_contract(before: "CompilationPlan", after: "CompilationPlan",
                      audit: "PlanAuditResult") -> str:
    """A re-audit judges the repair. Three rounds on one plan each cleared
    every objection they were given and each re-audit raised three or four
    new ones on fields that had already passed. The contract: say whether
    each listed objection is resolved; a NEW major issue is allowed only if
    the changed fields caused it."""
    # A synthetic gate audit never read the plan. After a gate repair the
    # re-audit must be the FULL audit, or the scope rule hides every field the
    # real auditor has not yet judged (live: a plan accepted in 32 seconds with
    # the knowledge-path hole untouched).
    if getattr(audit, "verdict_source", "") == "none" or not audit.issues:
        return ""
    objections = [
        {"story_id": i.story_id, "category": i.category, "problem": i.problem}
        for i in audit.issues if i.severity in {"critical", "major"}
    ]
    changed = _changed_fields(before, after)
    return (
        "\n\nRE-AUDIT CONTRACT. This plan was already audited and the ONLY blocking "
        "objections were the ones below. The author has repaired them; the fields that "
        "changed are listed per story. Your job now:\n"
        "1. For each objection below, decide whether the repaired plan resolves it. If it "
        "does not, raise it again (same category) quoting the text that still fails.\n"
        "2. You may raise a NEW critical/major issue ONLY if it is caused by text in the "
        "changed fields, and an informed viewer would reject the video for it. Fields that "
        "did not change already passed: do not re-open them, and do not raise issues the "
        "previous audit chose not to raise.\n"
        "3. Minor notes on anything are welcome; they do not block.\n"
        "PREVIOUS OBJECTIONS:\n" + json.dumps(objections, ensure_ascii=False, indent=1) +
        "\nCHANGED FIELDS:\n" + json.dumps(changed, ensure_ascii=False, indent=1) + "\n"
    )


def load_draft_file(path: str | Path, item: "NarrativeStoryPlan") -> "StoryDraft":
    """A needs_edit.txt / draft file: optional cold-open line, optional
    '[Title]' line, then the narration. Hook candidates come from the plan
    title; the narration is the file's prose."""
    text = Path(path).read_text(encoding="utf-8").strip()
    lines = text.split("\n")
    title = item.title
    body_start = 0
    # drop a leading cold-open line if it is followed by a '[Title]' marker
    for i, ln in enumerate(lines[:4]):
        if ln.strip().startswith("[") and ln.strip().endswith("]"):
            title = ln.strip()[1:-1] or title
            body_start = i + 1
            break
    narration = "\n".join(lines[body_start:]).strip()
    if not narration:
        raise ValueError(f"{path}: no narration found")
    return StoryDraft(story_id=item.story_id, title=title,
                      hook_candidates=[title], narration=narration)


def load_approved_plan(path: str | Path, index: int = 0) -> "CompilationPlan":
    """A plan the operator read and approved, from a plan_only.py save file.

    The file holds a list; each entry is either a bare plan dump (older
    saves) or {"plan": ..., "audit": ...}. Only the plan is trusted from the
    file: preflight re-runs on it in run(), because the gates may have
    tightened since it was saved.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = raw if isinstance(raw, list) else [raw]
    if not entries:
        raise ValueError(f"{path}: no plans in file")
    entry = entries[index]
    if isinstance(entry, dict) and "plan" in entry and "stories" not in entry:
        entry = entry["plan"]
    return CompilationPlan.model_validate(entry)


def load_approved_audit(path: str | Path, index: int = 0) -> "PlanAuditResult | None":
    """The audit plan_only saved beside the plan, if any and if valid."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = raw if isinstance(raw, list) else [raw]
    entry = entries[index] if entries else None
    audit = entry.get("audit") if isinstance(entry, dict) else None
    if not isinstance(audit, dict):
        return None
    try:
        parsed = PlanAuditResult.model_validate(audit)
    except Exception:
        return None
    return parsed if parsed.status == "valid" else None


def validate_plan_preflight(
    plan: CompilationPlan,
    story_count: int,
    strategy: NamedChannelStrategy | None = None,
) -> list[str]:
    """Reject structurally weak plans before any paid story drafting calls."""
    errors: list[str] = []
    expected = [f"story_{index}" for index in range(1, story_count + 1)]
    actual = [item.story_id for item in plan.stories]
    if actual != expected:
        errors.append(f"story IDs/order must be {expected}; received {actual}")
    if len(plan.stories) != story_count:
        errors.append(f"expected {story_count} stories; received {len(plan.stories)}")

    errors.extend(narrator_pronoun_conflicts(plan))
    # Run 15 accepted a plan with NO ladder: the fear gate skips ladders under
    # four rungs, so an empty one was never judged. The ladder is the plan.
    for _item in (plan.stories if getattr(strategy, "require_ladder", False) else ()):
        for _f, _what in (("already_line", "a fact learned too late that re-reads the whole night"),
                          ("no_way_out", "the named reason the easy exit is gone"),
                          ("threat_mind", "what the narrator infers the threat wants, and from what"),
                          ("remainder", "the one thing never explained, said last")):
            if len(str(getattr(_item, _f, "") or "").split()) < 6:
                errors.append(f"{_item.story_id}: {_f} is missing: {_what}. Without it the story "
                              "is a crime report, not something that stays.")
        _rungs = [r for r in (getattr(_item, 'escalation_ladder', None) or []) if str(r).strip()]
        if len(_rungs) < 4:
            errors.append(
                f"{_item.story_id}: escalation_ladder has {len(_rungs)} rungs; a story needs "
                "at least four, each nearer than the last, the back half present tense.")
    errors.extend(ladder_fear_problems(plan))
    # ladder_order_problems is NOT a hard gate: on 2026-08-22 it rejected five
    # of five ladders it saw, every one a real approach the regex missed
    # (a truck parked across the road, boots crossing the porch, a latch
    # lifting under a hand). The planner rule and the auditor carry it.
    errors.extend(escape_agency_problems(plan))
    errors.extend(night_arithmetic_problems(plan))
    errors.extend(cold_open_spoiler_problems(plan))
    if getattr(strategy, "require_ladder", False):
        errors.extend(cold_open_hook_problems(plan))
        errors.extend(voice_tic_problems(plan))
    # A LADDER WITH ONE RUNG IS A SCENE. Enforced only when the planner used the
    # field, so older plans and fixtures still validate; when it did, fewer
    # than four rungs means the premise will collapse to its scariest sentence
    # and be rejected as stock two paid calls from now.
    for item in plan.stories:
        rungs = [r for r in (getattr(item, "escalation_ladder", None) or []) if str(r).strip()]
        if rungs and len(rungs) < 4:
            errors.append(
                f"{item.story_id}: escalation_ladder has {len(rungs)} rung(s); a "
                "story needs at least four distinct things that get worse, or it "
                "is one scene")
        seen = set()
        for r in rungs:
            key = " ".join(str(r).lower().split())[:60]
            if key in seen:
                errors.append(f"{item.story_id}: escalation_ladder repeats a rung")
                break
            seen.add(key)

    # PER-STORY BUDGETS ARE FREE TO DIFFER, NOT FREE TO BE ANYTHING. Letting the
    # planner size each premise is the point; letting it hand one story 90% of
    # the compilation, or hand out budgets that do not add up to the video we
    # agreed to make, is not. Checked here because a bad allocation is cheap to
    # reject before drafting and expensive to discover after three writer calls.
    budgets = [int(getattr(item, "target_words", 0) or 0) for item in plan.stories]
    if any(budgets):
        if not all(budgets):
            errors.append("target_words must be set on every story or none")
        else:
            total = int(plan.target_word_count)
            equal = total / max(1, len(budgets))
            if abs(sum(budgets) - total) > math.ceil(total * 0.02):
                errors.append(
                    f"story target_words sum to {sum(budgets)}; the compilation "
                    f"target is {total}")
            # ONLY A FLOOR. An earlier version of this also capped a story at
            # double the equal share, "so no story swallows the compilation" —
            # but if one premise deserves the whole video then the answer is a
            # one-story video, not three stories filed down to the same size.
            # The floor is the real protection: below roughly a third of a
            # normal story there is no room to set anything up, and what ships
            # is a fragment padding out someone else's video.
            for item, budget in zip(plan.stories, budgets):
                if budget < max(400, equal * 0.4):
                    errors.append(
                        f"{item.story_id} is budgeted {budget} words, too few to "
                        f"set anything up; give it room or drop it and write "
                        f"fewer, longer stories")
    for item in plan.stories:
        # A human threat that walks away uncontested leaves an unresolved danger;
        # the plan must declare what the narrator does about it afterwards.
        if (
            item.escape_mechanism == "threat_withdraws_uncontested"
            and item.threat_type == "human"
            and item.safety_obligation == "not_applicable"
        ):
            errors.append(
                f"{item.story_id}: threat_withdraws_uncontested with a human threat "
                "requires a declared safety response; not_applicable is not allowed"
            )
        # NOTE deliberately NOT a deterministic rule: "recurring human threat +
        # not_applicable" needs to know whether the recurrence spans separate
        # nights, which lives in prose fields — a typed check false-positived on
        # single-shift repeat sightings. The plan prompt warns the planner and
        # the semantic plan audit enforces it (proven live 2026-07-18).
        # voice_seed gating happens by SALVAGE (_salvage_voice_seeds blanks a
        # poisoned seed before preflight), never by rejecting the plan: a bad
        # 2-sentence sample is not worth a full replan.
        ledger = [str(entry).strip() for entry in item.continuity_ledger]
        if len(ledger) != 5 or len({_normal(entry) for entry in ledger}) != 5:
            errors.append(f"{item.story_id} ledger must contain five unique entries")
            continue
        for entry, prefix in zip(ledger, _LEDGER_PREFIXES, strict=True):
            suffix = entry[len(prefix):].strip() if entry.lower().startswith(prefix) else ""
            if (
                not entry.lower().startswith(prefix)
                or len(_words(suffix)) < 3
                or len(_words(entry)) > 24
            ):
                errors.append(
                    f"{item.story_id} ledger must use ordered concise category {prefix}"
                )
    for field in (
        "narrator_profile", "setting", "setup_requirement", "threat",
        "ending_shape", "escape_action",
    ):
        values = [_normal(getattr(item, field)) for item in plan.stories]
        if any(not value for value in values) or len(set(values)) != len(values):
            errors.append(f"plan must give every story a distinct non-empty {field}")
    for item in plan.stories:
        setup_words = len(_words(item.setup_requirement))
        if setup_words < 3 or setup_words > 35:
            errors.append(
                f"{item.story_id} setup_requirement must be a concise 3-35 word "
                "spoken setup obligation"
            )

    if strategy is None or strategy.require_distinct_mechanisms:
        # The 2026-07-17 plan gave three stories different sentences and one beat
        # sheet: a silent watcher blocks the route, the narrator flees to a lit
        # occupied place and is locked in. Every prose field differed, so nothing
        # caught it. Typed axes are what a viewer actually experiences as repetition.
        for axis in _MECHANISM_AXES:
            seen: dict[str, str] = {}
            for item in plan.stories:
                value = str(getattr(item, axis))
                if value in seen:
                    errors.append(
                        f"{seen[value]} and {item.story_id} share {axis}={value}; every "
                        "story needs its own threat, progression, escape, and aftermath "
                        "mechanism or the compilation is one story told three times"
                    )
                else:
                    seen[value] = item.story_id

    if strategy is not None and strategy.topic_alignment_gate:
        subject = topic_subject_stem(plan.topic)
        promises = [_normal(item.topic_promise) for item in plan.stories]
        if any(not value for value in promises):
            errors.append("every story must declare how it delivers the topic (topic_promise)")
        elif len(set(promises)) != len(promises):
            errors.append("plan must give every story a distinct topic_promise")
        if subject:
            for item in plan.stories:
                if not _covers_subject(item.topic_promise, subject):
                    errors.append(
                        f"{item.story_id} topic_promise {item.topic_promise!r} does not "
                        f"deliver the topic subject {subject!r} from {plan.topic!r}; a "
                        "compilation may not advertise one subject and plan another"
                    )

    if strategy is not None and strategy.premise_freshness_gate:
        errors.extend(_premise_freshness_errors(plan))

    if strategy is not None and strategy.safety_response_gate:
        for item in plan.stories:
            if item.narrator_age_band != "minor" or item.threat_type != "human":
                continue
            # Three legal paths, not one. The obligation is that a child who
            # survives a human threat tells SOMEONE responsible, or the plan says
            # concretely why not — telling a parent is a real response, and forcing
            # police onto every story manufactures exactly the formulaic ending the
            # channel promise exists to avoid. Whichever path is declared, the
            # narration has to deliver it (see gate_compilation/safety_response).
            if item.safety_obligation in {"authorities_contacted", "trusted_adult_or_witness"}:
                continue
            reason_words = len(_words(item.safety_omission_reason))
            if item.safety_obligation == "concrete_reason_omitted" and reason_words >= 5:
                continue
            errors.append(
                f"{item.story_id} safety_obligation={item.safety_obligation} is not a "
                "plausible aftermath for a minor who survived a human threat: plan "
                "authorities_contacted or trusted_adult_or_witness, or state a concrete "
                "reason (>=5 words) in safety_omission_reason for why no adult or police "
                "response follows"
            )
    human_fraction = strategy.human_threat_fraction_min if strategy else 2 / 3
    required_human = math.ceil(story_count * human_fraction)
    human_count = sum(item.threat_type == "human" for item in plan.stories)
    if human_count < required_human:
        errors.append(f"plan needs at least {required_human} human threats; received {human_count}")
    evidence_count = sum(item.evidence_allowance != "none" for item in plan.stories)
    evidence_limit = strategy.evidence_beat_limit if strategy else 1
    minimum_free = strategy.evidence_free_story_min if strategy else 1
    max_evidence_stories = min(
        1 if evidence_limit > 0 else 0,
        max(0, story_count - minimum_free),
    )
    if evidence_count > max_evidence_stories:
        errors.append(
            f"plan may allocate evidence to at most {max_evidence_stories} stories "
            "under the selected profile"
        )
    if len(_words(plan.cold_open)) > 28:
        errors.append("cold_open exceeds 28 spoken words")
    return errors


def _mechanism_vocabulary() -> str:
    def options(annotation) -> str:
        return " | ".join(annotation.__args__)
    return (
        f"threat_mechanism: {options(ThreatMechanism)}\n"
        f"progression_mechanism: {options(ProgressionMechanism)}\n"
        f"escape_mechanism: {options(EscapeMechanism)}\n"
        "  (threat_withdraws_uncontested: the threat disengages before the narrator "
        "can act — the withdrawal must read as menace, it chose to leave, not relief)\n"
        f"aftermath_mechanism: {options(AftermathMechanism)}\n"
        f"threat_identity: {options(ThreatIdentity)}\n"
        "  (who the threat IS, not how it acts; unseen_ambiguous implies "
        "threat_type=ambiguous, so it cannot appear twice under the at-most-one-"
        "ambiguous rule)"
    )


def _premise_shapes(channel_id: str, limit: int = 6) -> str:
    """Real competitor openings, offered as SHAPES the planner may study.

    Across 48 saved plans the auditor issued 108 trope rejections — more than
    every other category combined. The plans were not repetitive on the
    surface: they carried 132 distinct threat sentences. What repeated was
    STRUCTURE ("a man recites her plate number" / "her patient's name" / "the
    name on her folder" are one premise in three coats), and the only guidance
    the planner had was a list of things to avoid. Nothing had ever shown it
    what a fresh premise looks like in this genre.

    Returns "" when no bank has been built, so a channel without a measured
    corpus plans exactly as before.
    """
    bank_file = (Path(__file__).resolve().parents[3] / "output" / "research"
                 / channel_id / "premise_bank.json")
    try:
        bank = json.loads(bank_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    picked = [row for row in bank if row.get("opening")][:limit]
    if not picked:
        return ""
    lines = []
    for row in picked:
        opening = " ".join(str(row["opening"]).split())[:260]
        lines.append(f"  - {opening}")
    return (
        "\nHOW REAL ACCOUNTS IN THIS GENRE BEGIN (study the SHAPE, never the "
        "words):\n" + "\n".join(lines) +
        "\nNotice what these establish first: a person, a time, and why they "
        "were there. The danger arrives into a life that is already specific. "
        "Do NOT reuse a phrase, a job, a place or a detail from these — they "
        "are other people's accounts, and copying one would fail the same "
        "freshness gate it is meant to help you pass.\n")


def _plan_prompt(brief: TopicBrief, story_count: int, target_words: int,
                 brand: dict | None, recent_avoid: str,
                 strategy: NamedChannelStrategy,
                 forbidden_fingerprints: set[str] | None = None) -> str:
    subject = topic_subject_stem(brief.title)
    spent = (
        "\nCONCEPTS ALREADY SPENT: a compilation with this exact combination of typed "
        "mechanisms has already been generated for this channel and was rejected or "
        "used. Choose materially different mechanisms — not different wording for the "
        "same beats.\n"
        if forbidden_fingerprints else ""
    )
    return f"""Create a locked plan for a first-person horror recollection.
TOPIC: {brief.title}
STORIES: exactly {story_count}
TOTAL NARRATION TARGET: {target_words} words
SPLIT THAT TOTAL BETWEEN THE STORIES AS EACH PREMISE ACTUALLY NEEDS, in each
story's target_words. They must sum to the total, and no story may take less
than half or more than double an equal share. Do NOT divide it evenly out of
caution: a premise that needs a long patient setup should be given the room,
and one that lands quickly should be allowed to end.
CHANNEL VOICE: {json.dumps(brand or {}, ensure_ascii=False)}
RECENT MATERIAL TO AVOID: {recent_avoid or 'none supplied'}
{_premise_shapes(getattr(brief, 'channel_id', '') or '')}
CHANNEL QUALITY STRATEGY ({strategy.strategy_id}):
{strategy.planner_rules or strategy.writer_rules}
{spent}
Return exactly one compact JSON object and no commentary. Top-level keys are:
topic (string), cold_open (string), target_word_count (integer), stories (array).
target_word_count is YOUR ESTIMATE of what these accounts need, spoken: count the rungs,
the setup each premise needs, the worst rung slowed down. Single accounts in this genre run
anywhere from 1,800 to 4,500 words; compilations 3,500-6,000. The number you give is handed
to the writer as a shape, never enforced as a quota, so estimate honestly rather than
rounding to the duration you were given.
Every stories item has exactly these keys: story_id, title, narrator_profile, setting,
setup_requirement, threat, threat_type (human or ambiguous), escape_action, ending_shape,
evidence_allowance (MUST be exactly one enum string: none, camera, official, physical,
witness, or recurrence; put any description in continuity_ledger instead), voice_rules,
voice_seed, threat_mechanism, progression_mechanism, escape_mechanism,
aftermath_mechanism, threat_identity, topic_promise, distinguishing_turn,
narrator_age_band, target_words, escalation_ladder, already_line, no_way_out, threat_mind, remainder,
narrator_age_years, safety_obligation, safety_omission_reason, continuity_ledger
(array of exactly 5 unique short strings in this exact order and with these exact
prefixes: "hook_timeline:", "people_objects:", "locations_exits:",
"props_threat_position:", "response_escape:"). Each entry must state the relevant
locked facts after its prefix and stay at or under 24 words. COUNT the words in each
ledger entry before emitting: one entry over 24 words voids the ENTIRE plan and the
attempt is wasted (live: hook_timeline is the usual offender — compress it to bare
clock facts, no narrative). Keep every other scalar
under 35 words — EXCEPT voice_seed, which is a 2-3 sentence sample and is exempt from
that cap.

EVIDENCE BUDGET FOR THIS PLAN: with {story_count} stor{'y' if story_count == 1 else 'ies'}, at most {max(0, min(1, story_count - 1))} may carry evidence_allowance other than "none"{' — so this story MUST be "none"' if story_count == 1 else ''}. At least one story always ends with nothing corroborated; the fear is not allowed to be proven.

WHAT STAYS. The most-watched accounts in this genre are not remembered for the knock;
they are remembered for one sentence learned too late. Every story needs all four:
- already_line (<=35 words): a fact the narrator learns AFTER the worst of it that makes the
  listener re-read the whole night. 'I likely looked right at this guy when he first
  knocked on the window and didn't even know it.' 'They were both my items.' 'Someone had
  taken apart a section of staircase while we sat directly above them.' 'If the lights
  were on one night and off the next, he assumed the house was empty.' It must be a fact
  the ladder quietly set up and the listener could not have known. It is about PRESENCE,
  never identity: 'he had been in the house', 'I read the card aloud at the lit window',
  'the chair in the loft faced my window' — never 'it turned out to be the fired hand'.
- no_way_out (<=35 words): the named reason the easy exit is gone that night. No phone in
  the house. Seventy feet up with the only way down blocked. Police an hour out. The car
  keys in the room he is in. A working phone and a nine-minute deputy is a safe story.
- threat_mind (<=35 words): the moment the narrator reasons out what the threat WANTS from
  what it does. 'Why knock four nights and never come in? He was checking whether the
  pattern changed.' 'Nothing was stopping him. Maybe he wanted me to stay inside.' The
  inference is the fear; the threat must visibly think (a schedule, a sequence, patience).
- remainder (<=35 words): the one thing never explained, and it is the LAST thing said.
  Never caught. Denied the knocking. No fire pit where the fire was. 'Maybe it's in my
  head, or maybe it isn't.' 'Deputies found nothing' is a shrug, not a remainder.
THE REPORT BEAT. After the first sign that cannot be explained away (a print under the
window, prints circling the house, a stranger reciting a private fact), the account
either shows the narrator reporting it — and receiving the genre's half-answer: 'sounds
like someone checking whether the house is occupied; install a camera; call 911 if he
comes back' — or states plainly why no report was possible (no phone, no signal, the
office closed, nobody to call at that hour). A narrator with a working phone who says
nothing for days is a human-safety failure, and the listener stops believing her.
VOICE IS PLAIN. Exact clock times, the narrator reasoning out loud, at most one image in
the whole account. No verbal tics, no catchphrases, no comparing everything to a relative:
nobody in the corpus does that, and it reads as a writer performing a character.
THE LADDER. escalation_ladder is an array of 4-7 strings: the sequence of concrete
things that get worse, in order. Rung one is small and deniable — the kind of thing a
person explains away. Each later rung is worse than the last, is something the narrator
could actually perceive at that distance and light, and does NOT explain the earlier
rungs. The threat field is the rung where denial runs out; the escape follows the last
rung. The LAST rung must leave no room to keep watching: it is the moment a person
has to move, not a thing they notice from a window. If your final rung ends with the
narrator observing, you have written rung N-1 — add the one that forces the escape.
FEAR IS PRESENT TENSE AND DISTANCE. A rung the narrator is not there for — a woodpile
restacked, a key gone, a note found in the morning — is a clue, and clues frighten no
one. In the accounts this genre rewards, the threat is ACTING while the narrator is
present and each rung is nearer than the last: a tap on the glass, then a tap closer to
the centre, then the bathroom window starting to move. Use at most two trace rungs, and
only at the start. At least half the rungs, and ALL of the last three, must be things
happening to the narrator right now, with the distance between them closing.
DISTANCE CLOSES IN STEPS NOBODY CAN SKIP: approach (heard or seen near, stopping
outside), then contact (a hand on the structure), then breach (forcing in). A polite
question at the door in daylight followed by the handle wrenched that night is a jump
cut; put the footsteps that stop outside the kitchen door between them.
WHAT THE THREAT KNOWS, IT GOT SOMEWHERE. If the threat recites a private fact — a
prescription, a name, a schedule — the plan must contain the moment it could have been
taken (a bag on a car seat, mail in an unlocked box, a form read over a shoulder). Plant
it so the narrator only understands it afterwards; never explain it aloud.
THE COLD OPEN SELLS THE NIGHT, NOT THE PAYOFF. It may name the place, the fear, the
object that changed — never the last rung's action. 'Something said his nickname through
the glass' gives away the best beat; 'I never leave a window unlatched anymore' does not.
THE ESCAPE IS GEOMETRY, NOT A MOOD. The threat stops because of something the narrator DID, or because
help the narrator CALLED arrives after a stated wait. Never a neighbour's headlights,
never a threat that simply loses interest. Before writing escape_action, place two things on
the floor plan from your own ledger: where the narrator stands at the last rung, and
where the threat stands. The escape must move AWAY from the threat through an exit in
locations_exits without crossing the threat's position, and it must begin the moment
the last rung lands — a narrator who watches an intruder pocket her phone, or who has
to walk past him to reach the door, has been given no escape at all. If the only exit
is past him, change the rung or the room, not the person. A story whose ladder has one rung is a single scene, and a single scene is what
the trope auditor keeps rejecting — not because the moment is stock, but because a
premise with nowhere to go has nothing to be except its own scariest line. The top
accounts in this genre turn twenty times across several days; give yours at least four.

WHO THIS PERSON IS, BEFORE ANYTHING THREATENS THEM. narrator_profile is not a job
title. Write the LIFE: roughly how old they were, what stage they were at, and the
specific reason they were in that place on that night — a shift they had swapped, a
thing they were saving for, someone they were avoiding, a habit they had kept for
years. Then derive the threat from that life.
This order is not a preference. Across 147 competitor captions in this genre, 98% open
on a person and a reason; two open on the threat, and those two are the lowest-viewed
scripts in the corpus. It is also the difference this channel keeps failing on: this
plan format gives the danger eight typed fields and the person one, so premises come
out built threat-first, and threat-first lands in the small stock catalogue every
viewer already knows. A life is specific by construction and cannot be stock.

VOICE DIFFERENTIATION (the axis most often faked with adjectives): for each story emit
(a) voice_seed — a 2-3 sentence sample paragraph WRITTEN IN that narrator's exact
voice, differing sharply from the other two stories in sentence length, register, and
verbal habit; and (b) voice_rules listing 2-3 MEASURABLE idiolect markers (e.g. "short
clipped sentences, calls everything by its trade name", "rambles and self-corrects
mid-sentence", "never swears, hedges every estimate" — invent this story's own markers,
never reuse these examples). No two stories may share a marker. The sample and markers
must be SATISFIABLE under the writer's gates: no marker may rely on exact numbers,
clock times, counts, or measurements (the narration has a hard numeric budget); no
stock self-reassurance phrasing; no evidence/corroboration framing; the sample must not
introduce any fact, prop, place, or event absent from the plan — demonstrate voice on
ordinary pre-story material only. setup_requirement is the ONLY ordinary spoken setup obligation: one
concise 3-35 word statement of the ordinary context the narrator must establish on the
page before danger (who they are, where, doing what). setting and continuity_ledger are
private continuity constraints the story must never contradict, but they are NOT
exposition obligations — do not put an exact unit, floor, exit, or prop into
setup_requirement unless it affects the threat, a choice, the escape, or the ending.
The inverse is a hard rule: EVERY object, opening, or mechanism the escape_action or
ending_shape DEPENDS on (a propped fire door, a manual release lever, a service gap
in a fence) MUST already be planted in setup_requirement or a continuity_ledger entry
as an established fact for THAT night — an escape through a door the plan never
propped is a staging contradiction the audit rejects.
IDs must be
story_1..story_{story_count}. Give each
story a physically coherent continuity ledger, different narrator life context and
sentence rhythm, different human or under-confirmed threat, a practical response — an
action the narrator takes, or a deliberate decision while the threat disengages on its
own — and a different ending shape. If escape_mechanism is threat_withdraws_uncontested,
escape_action MUST be two ordered clauses: first the narrator's deliberate decision
under pressure, then the threat's withdrawal (e.g. "stays flat behind the counter with
911 dialed AND the man steps back off the porch before anyone arrives"); with a human
threat this mechanism forbids safety_obligation=not_applicable.
escape_action clauses are a PERFORMANCE SEQUENCE: the story must deliver them in
clause order and the compliance auditor must quote each clause as a separate span in
that order. So every clause must be a discrete, timestampable EVENT. A continuous
state ("keeps to the main route", "stays calm") is not an event — it cannot be
ordered against one, and a chain that mixes them becomes unauditable and kills the
story after it is written. Standing states belong in the continuity_ledger; keep the
escape chain to 2-3 actions a viewer could put on a clock.
escape_action and ending_shape must not SHARE an event: the escape chain ends
BEFORE the ending begins. If the same moment appears in both fields ("...flags down
the deputy as the man slips through the fence gap" / "deputies arrive as the man
slips through the fence gap"), the auditor must quote one span for two beats and the
story is unauditable no matter how it is written. Give the ending its own subsequent
moment. At most one story may use one restrained evidence
beat; at least one must use none. cold_open is one short first-person line whose promised
moment will occur in a story. No monsters, omniscient knowledge, CTAs, analysis, police-
report framing, camera static, disappearing footprints, or proof-stacking. For three
stories, at least two threat_type values must be human; at most one may be ambiguous.

TYPED MECHANISMS — pick exactly one value per axis from these closed vocabularies:
{_mechanism_vocabulary()}
Across the compilation, NO TWO STORIES MAY SHARE A VALUE ON ANY AXIS. This is checked
before any prose is written and is the single most common reason a plan is rejected:
three stories where a silent figure blocks a route and the narrator flees indoors to
safety are ONE story told three times, no matter how different the jobs and streets
are. Label honestly — a mechanism label that flatters a duplicate premise is a defect,
not a workaround. The labels must describe the threat/escape/ending you actually wrote.
threat_identity is an axis like the others — no two stories may share a value. At most
one story per compilation may feature a silent, motionless lone stranger; a threat that
speaks normally but says something subtly wrong is often scarier than stillness.
That one slot must EARN itself with a concrete distinguishing mechanism the audit can
name. Stock renderings are rejected as the tall-still-figure trope REGARDLESS of
setting: a figure glimpsed at a distance (or in glass) that is gone when approached,
tapping or knocking that stops when observed, a motionless shape that leaves one
inexplicable trace. Relocating the trope is not a fresh angle. If you cannot state in
one clause what makes this watcher unlike the stock one, plan a threat that ACTS.
The same one-slot rationing applies to the NO-RECORD aftermath: an authority or
records check that comes back empty ("nothing on file", "no one matched the name",
"the log showed nothing") may close AT MOST ONE story per compilation — three empty
searches under three different aftermath labels are one device worn three ways. Vary
what the aftermath YIELDS: a partial answer that explains nothing, a wrong explanation
others accept, an object that should not exist, or no check at all.
distinguishing_turn: 4-25 words, one per story, all three different. Name what the
STOCK version of this premise would do and what this one does instead. A deterministic
check reads it, and a clause that only restates your own threat field is rejected. This
exists because the compilation is scored on originality as a whole and that score
cannot be repaired once the prose is written — three competently written genre defaults
lose on this axis no matter how clean the continuity is.
HUMAN-THREAT STOCK LIST — human threats are the majority of every compilation and are
where the genre default hides, because they draw no attention from the ambiguous-threat
rules below. These are stock: a vehicle tailgating or running the narrator off a dark
road; strangers surrounding the vehicle demanding what is in it; a passenger who grabs
the wheel or gives a wrong destination; a man who will not leave the counter at closing;
someone waiting by the narrator's car in an empty lot; a knock from someone claiming a
plausible errand. You may still use one of these SHAPES, but distinguishing_turn must
then name the concrete thing the stock version does not have — what the threat wants,
knows, or does that a random predator would not. "The threat behaves oddly" is not a
turn; "he asks for the cooler by the patient's name, which is not written on the van"
is.
AMBIGUOUS-THREAT STOCK LIST — the audit rejects these on sight unless the plan names
a concrete fresh mechanism in one clause (ten recent plans died here; do not spend an
attempt discovering it again): doors/exits closing in sequence behind the narrator;
lights failing or extinguishing just ahead of or behind them; an elevator travelling
on its own to a sealed floor; knocking/tapping/sound that stops exactly when observed
or when they disengage; the environment "performing" the narrator's own presence back
at them (mirrored footsteps, echoed breathing); a stranger faking car trouble as a
lure; a disconnected or dead phone line that rings anyway. An ambiguous threat is
scarier when something concrete is WRONG about a normal thing than when the building
performs a haunting.
Vary the recognition point across the three stories — one narrator may read the danger
early, another late, another only in hindsight. Where a narrator has a trade or role,
write that story's voice_rules to include 2-3 role-specific ways of seeing; in at least
ONE story per compilation the escape must turn on something only that role would notice.
Give each story a DISTINCT pacing profile so the three do not read as one evenly-covered
template — choose a different one per story from: [one beat developed at roughly twice
the depth of the rest] / [two adjacent beats moderately expanded] / [even coverage with
a single long dwell moment]. The three stories must not all use the same profile.

topic_promise: 6-20 words. This is an INTERNAL GATE STRING, not prose and not a
pitch — a deterministic check reads it before anything is written. It must do two
things at once:
  1. repeat the compilation's exact subject wording{f" — the literal word {subject!r}" if subject else ""}, verbatim; and
  2. name the concrete site or job this story actually depicts.
Both, in the same string. A promise that describes a real site but paraphrases the
subject FAILS the gate and throws away the whole plan: "rekeying a laundromat after
closing" loses to "rekeying a laundromat business after closing" purely because the
subject word is missing. Naming a specific site is not a substitute for the subject
word, and the subject word alone is not a substitute for the site.
If the topic promises newspapers, every story is about newspapers — a package route,
a milk round, or a generic "delivery" is a different video than the one the title
sold.

narrator_age_band: "minor" or "adult". narrator_age_years: the exact age integer for a
minor, otherwise null. If the narrator is under 18, say so and the story will be
required to speak that age on the page.
A minor narrator raises the safety bar sharply — any physical contact or credible
threat then requires the full real-world reporting chain (management, parents, police
where warranted), and a plan that skips it dies in audit. Choose a minor only when the
age IS the premise, and then plan that chain explicitly; an adult narrator is the
default.

safety_obligation: one of authorities_contacted | trusted_adult_or_witness |
concrete_reason_omitted | not_applicable — what the narrator does about the danger
afterwards. A minor who survives a human threat must plan authorities_contacted OR
trusted_adult_or_witness (a parent, guardian, teacher, employer, named neighbour, or
witness is told), unless safety_omission_reason gives a concrete reason (>=5 words)
why nobody is told. Prefer the response the real person would actually make: police
for a violent or abduction-grade encounter, a parent or another responsible adult for
a frightening one. Do not reach for police in every story — a compilation where three
narrators all file reports is as formulaic as one where nobody tells anyone.
But a human threat that RECURS across separate nights or visits forbids
not_applicable: a real worker menaced repeatedly reports it, tells someone with
standing, or the plan states the concrete reason they cannot — and an in-progress
deliberate entrapment gets an immediate call, never a next-day mention.
Whichever you declare, the STORY MUST PUT IT ON THE PAGE; a declared response that
never happens is a release-blocking defect. This is the narrator reporting what
happened; it is NOT police-report framing and it is NOT after-the-fact proof that the
threat was real — nobody confirms anything.
When safety_obligation is not not_applicable, decide at plan time where the safety
response lands: it may sit inside the final two beats (a flat report sentence there
does not violate the ending-stop rule), or earlier in the aftermath when the
aftermath_mechanism carries a different final image.
safety_omission_reason: "" unless safety_obligation is concrete_reason_omitted.
{_self_audit_section(strategy)}"""


def _self_audit_section(strategy: NamedChannelStrategy) -> str:
    """The planner's own pre-return pass, from the channel profile.

    Every rule here is a defect a paid auditor already caught after the plan was
    written (live 2026-07-17 16:03). Checking it inside the planner's own call is
    free; discovering it downstream costs a replan. This does not replace the
    auditor — it is the same reader the plan has to survive anyway, asked earlier.
    """
    if not strategy.plan_self_audit:
        return ""
    return f"""
BEFORE YOU RETURN, re-read your own plan against this list and fix what fails. A
skeptical domain reviewer — an electrician, a night-shift worker, an ex-cop, a
paramedic — reads it next and blocks the whole compilation on any one of these:
{strategy.plan_self_audit}
Do not narrate this pass or add fields for it. Fix the plan and return only the JSON."""


def _plan_audit_prompt(plan: CompilationPlan, strategy: NamedChannelStrategy) -> str:
    payload = json.dumps(plan.model_dump(), ensure_ascii=False, indent=1)
    return f"""Audit this LOCKED story plan for real-world plausibility BEFORE any prose exists.
You are a skeptical domain reviewer: an electrician, a night-shift worker, an ex-cop and
a paramedic reading these premises. Report an issue ONLY where an informed viewer would
object — do not invent objections and do not review prose style (there is no prose yet).

Check each story for exactly these categories:
- physical: impossible physics, devices behaving in ways they cannot (a standard breaker
  resetting itself, a deadbolt locking from both sides, phones with no signal AND working data).
- professional: wrong trade/procedure knowledge (maintenance, police response, hospital,
  retail closing routines).
- geography: the escape route must actually work — exits, floors, sightlines, distances.
- human_behavior: a reasonable person's response — fight, flight, or a deliberate
  defensive decision while the threat disengages on its own; no one preserves mystery
  over safety. Judge WHETHER they act, not whether they picked the best available
  action. A frightened person takes the exit they see, not the optimal one, and 125
  of 147 scripts in this genre contain a choice the narrator second-guesses later
  ("I don't know why I did it", "I should have known better"). Reject passivity,
  curiosity that outranks safety, and choices no frightened person would make —
  never a real escape for being tactically imperfect.
  STAYING AFTER A DENIABLE SIGN IS NOT A DEFECT. Every one of the twenty most-watched
  accounts in this genre has the narrator notice something, explain it away, and stay -
  a median of five times; the first time anyone leaves or calls is a third of the way in,
  and 59 of 147 never do. A lock found open, a light found on, a sound under the floor:
  a person explains these and goes back to bed, and that is the genre, not a failure of
  the person. Object to staying ONLY after a sign that cannot be explained away - a
  stranger reciting private information, a hand on the door, a figure inside - or to
  passivity AT the final rung. Do not run the ladder backwards and declare that rung two
  should have ended the story.
  THE PLAN MUST CARRY THE REPORT BEAT: after the rung that cannot be explained away, a
  later rung (or no_way_out) must show the report and its half-answer, or why none was
  possible. A ladder that goes print -> prints -> footsteps -> knock with no call and no
  reason is MAJOR (human_behavior): the final editor will block the page for it anyway.
  STAYING AFTER A SIGN THAT CANNOT BE EXPLAINED AWAY is still the genre when the plan
  names BOTH a reason leaving is not available (the animals, no car, the relative asked,
  nowhere to go at that hour) AND a precaution taken (reported to police, told someone,
  locked up, phone kept in hand). Object only when neither is named. 'A reasonable person
  would leave' is not an objection to a house-sitter with a cat and a reported stranger.
- human_behavior also covers the THREAT, at ONE point only: the moment he finally stops —
  stops prying, walks away, drives off — needs a cause the plan names (a light thrown, a
  shout that police are on the line, a siren, a dog). A threat that simply leaves at the
  end is a coincidence; raise it as MAJOR and name the missing cause. Moving between
  rungs (door to window, yard to porch) needs no cause: that is the ladder. Knowing which
  window to try needs no path: he can see the lit one.
- haunting: already_line must be a fact the narrator could only learn AFTER the worst of
  it, set up by an earlier rung the listener passed over, and it must change what the
  night meant (he had been inside; I looked right at him; they were my items). A fact
  known from rung one, or a restatement of the threat, is not an already_line: MAJOR.
  NEITHER IS AN EXPLANATION. 'Weeks later my uncle confirmed it was a fired hand' tells
  the listener who; it RELIEVES. An already_line is about PRESENCE and PROXIMITY that had
  already happened while the narrator felt safe: he had been in the house; the chair in
  the loft faced my window; I had read the card aloud at the lit window; the bowl had been
  moved nights before. If the line answers 'who' or 'why', it is the wrong line: MAJOR.
  remainder must be about the threat's presence or intent, never logistics ('how he knew
  which window' is a logistics nit, not a remainder): MAJOR.
  remainder must be something nobody explains, not something police merely failed to
  find. no_way_out must be structurally true of the plan (a dead spot in the kitchen
  while the phone works in the bathroom is not no way out). threat_mind must be an
  inference from the threat's behaviour, not a label.
- cold_open: the compilation's cold_open must not reveal the last rung's action (the
  nickname said through the glass, the hand through the screen). It may name the place,
  the fear, the object that changed. A spoiled payoff is MAJOR; file it against story_1.
- prop_staging: every object used during threat/escape must exist in the setup or ledger first.
  AN OBJECT WHOSE CHANGE IS THE ENDING (a bent screen, a moved chair, a missing key) must
  be staged before the threat touches it, or the ending is a prop appearing from nowhere:
  MAJOR, name the object and the missing setup clause.
  STAGED MEANS NAMED WITH A CONDITION. If setup_requirement or the ledger names the object
  and its state ('the mudroom screen, patched last summer', 'the screen checked snug each
  night'), it is staged. Do not ask for it to be more specific or more memorable; that is
  the writer's job, not the plan's.
  COUNT THE NIGHTS: every 'three days', 'two nights later', 'the fourth night' must fit
  inside hook_timeline's stay. A mailbox neglected three days inside a four-night stay
  whose threat arrives 'two nights later' does not add up: MAJOR, show the arithmetic.
  A SHOUT THAT 911 IS ON THE LINE is either true — the call connected, the dispatcher
  speaking — or declared a bluff in the plan. 'dials 911 already ringing' and then shouts
  deputies are on the line is neither: MAJOR, say which it is.
  THE ORDINARY CONTENTS OF A NAMED ROOM COME WITH THE ROOM: a dresser in a bedroom, a
  knife in a kitchen, a broom in a mudroom, a phone in a house need no ledger line. Object
  only to load-bearing or unusual props (a gun, a specific key, a vehicle, a second exit)
  and to objects whose POSITION the escape depends on (a phone that must be in hand in
  the hallway). Run 14 lost two repair rounds to a dresser.
- knowledge_path: every private fact the threat uses (a prescription, a name, a schedule,
  which room the narrator sleeps in) must have a moment in the plan where it could have
  been taken: a bag on a car seat, mail in an unlocked box, a form read over a shoulder.
  A missing pill the narrator carried from the hospital himself has no such moment and
  reads as a hole, not a mystery. Quote the fact and name the missing moment.
  EVERY fact the threat says aloud is load-bearing, and each one needs its own path: a
  card that shows a nickname does not show that the uncle is in the hospital. A missing
  path for a spoken fact is MAJOR, not minor — it is the thing the viewer will say in the
  comments.
  A PLANTED MOMENT IS ENOUGH. If the plan contains a moment where the fact could have
  been taken (a get-well card in an unlocked mailbox, a thumbprint on it), do not demand
  proof that the threat took it — the viewer infers, and the genre never explains. Object
  only when NO such moment exists, or when the moment cannot yield the fact spoken.
- voice_vs_premise: voice_rules must not forbid what the ladder needs. A rule of 'never
  exact numbers' in a story that turns on a stranger reciting an exact dosage, or 'never
  describes faces' where the turn is a face at the glass, will break the draft. Quote
  the rule and the rung it collides with.
- trope: the premise is a recognizable AI-horror trope (tall-still figure, smiling stranger
  at the door, knocking that stops when observed) without a fresh angle. This applies to
  HUMAN threats too, and that is where it is most often missed: a tailgating vehicle, a
  demand at the vehicle window, a wheel-grabbing passenger, a man loitering at a counter
  at closing. Read each story's distinguishing_turn and ask whether it names something
  the stock version of that premise lacks. A turn that restates the threat, promises
  atmosphere ("more unsettling than it sounds"), or names only a setting detail does not
  clear the trope — quote it and raise the issue.
  ANTI-ANCHORING DISCIPLINE: the distinguishing_turn is the planner's CLAIM, never your
  evidence. Judge freshness from the LOCKED FIELDS ALONE (threat, escape_action,
  ending_shape, ledger, escalation_ladder) as if the turn sentence were deleted: if
  what remains reads as the stock version, the premise IS stock no matter how novel
  the claim sounds. A turn whose named mechanism does not appear in any locked field
  is marketing — quote the turn AND name the missing mechanism.
  THE LADDER IS WHERE FRESHNESS USUALLY LIVES. A premise is not its scariest
  sentence; it is the sequence of things that get worse. Two stories can share a
  threat line and be different stories if their ladders diverge. Read the rungs in
  order and ask whether THAT sequence — not the threat alone — is one you have seen.
  A ladder of four or more perceivable, non-explaining, escalating rungs is evidence
  of a worked premise; quote the rung that breaks the stock pattern if one does.

severity: critical = the premise cannot survive an informed viewer; major = a knowledgeable
viewer would flinch but the story could limp through; minor = worth noting, not blocking.

WHAT MAY BLOCK (critical/major). Only these four:
- a contradiction INSIDE the plan (two locked facts that cannot both be true);
- a physical or causal impossibility;
- a broadly established trade/hardware/electrical constraint true almost everywhere;
- a human choice no reasonable person makes, which stays unreasonable across any
  plausible version of the site.

WHAT MAY NOT BLOCK (minor at most, however confident you feel). A major/critical
kills the whole concept, so it must be something you KNOW, not something you expect:
- one site's staffing, hours, schedule or policy that the plan does not state. You are
  reading a premise, not the building. Whether one unnamed hospital garage staffs a
  valet booth at 1:25 a.m., whether one store locks at eleven, whether one depot has a
  night guard: real places vary, and the plan is free to be the place where it is true.
  Say it as a minor recommendation ("a security booth or ER desk would be the safer
  choice") — do not veto the concept over it.
- your preference about which detail would be more interesting or typical.
If the plan ITSELF states the hours or policy and the story then contradicts them, that
is an in-plan contradiction and may block. The rule is about what the plan says, not
about what you would have chosen.

Set knowledge_scope accordingly on EVERY issue: "universal" for physics, hardware,
established trade practice, or an in-plan contradiction; "site_specific" for anything
that depends on how one particular place happens to be run. A site_specific issue is
automatically demoted to minor, so do not mislabel to get a veto.

GROUNDING. Every major/critical MUST copy one exact, unique substring of the plan text
it challenges into evidence_quote — verbatim, character for character, from that
story's own fields (title, narrator_profile, setting, setup_requirement, threat,
escape_action, ending_shape, voice_rules, topic_promise, or a continuity_ledger entry) —
and must name that story_id. An objection you cannot quote is one the planner cannot
act on, and it will be rejected. If you cannot quote it exactly, make it a minor.

CHANNEL QUALITY STRATEGY ({strategy.strategy_id}):
{strategy.critic_rules}

LOCKED PLAN:
{payload}

Return valid JSON only:
{{"issues": [{{"story_id": "story_N", "category": "physical|professional|geography|human_behavior|prop_staging|trope|mechanism_mismatch|topic_alignment|knowledge_path|voice_vs_premise|cold_open|haunting", "severity": "critical|major|minor", "knowledge_scope": "universal|site_specific", "confidence": 0.0-1.0, "evidence_quote": "exact substring of that story's plan text", "problem": "concrete objection", "plan_fix": "instruction to the planner"}}], "summary": "one line"}}
Return an empty issues array if the plan is sound."""


def _spoken_obligations(plan: NarrativeStoryPlan, topic: str = "") -> str:
    """The locked facts that must reach the page, not merely the plan.

    Every line here is a deterministic release gate, so the writer is told the rule
    and the reason rather than being left to infer it from the plan object.
    """
    lines: list[str] = []
    if plan.topic_promise:
        subject = topic_subject_stem(topic)
        lines.append(
            f"- TOPIC PROMISE: {plan.topic_promise}. Name the compilation's subject"
            + (f" ({subject!r}) " if subject else " ")
            + "in the narration itself. The title sold it; the page must deliver it."
        )
    if plan.narrator_age_band == "minor" and plan.narrator_age_years is not None:
        lines.append(
            f"- NARRATOR AGE: state on the page that the narrator is "
            f"{plan.narrator_age_years}. A minor's age changes how every beat reads, "
            "so it is spoken, not implied. It does not count against the numeric budget."
        )
    if plan.safety_obligation == "authorities_contacted":
        lines.append(
            "- SAFETY RESPONSE: the narrator (or an adult with them) reports this to "
            "police after reaching safety, and the narration says so plainly. One or "
            "two sentences. This is the report, not proof: no officer confirms the "
            "threat, finds anything, or validates the story."
        )
    elif plan.safety_obligation == "trusted_adult_or_witness":
        lines.append(
            "- SAFETY RESPONSE: after reaching safety the narrator tells someone with "
            "STANDING — a parent, guardian, spouse, boss, teacher, or a neighbour or "
            "witness the story NAMES — and the narration says so plainly. A stranger or "
            "on-duty clerk who merely happens to be present does not count; telling the "
            "gas-station clerk is escape, not the response. No corroboration follows."
        )
    elif plan.safety_obligation == "concrete_reason_omitted" and plan.safety_omission_reason:
        lines.append(
            "- SAFETY RESPONSE: nobody is told, and the page makes the concrete reason "
            f"legible: {plan.safety_omission_reason}. Never omit help merely to keep a "
            "mystery intact."
        )
    return "\n".join(lines)


def _writer_max_tokens(target_words: int) -> int:
    """Live 2026-08-23: every writer-path call was capped at 2,600 tokens
    (~1,900 words) while asking for 2,600 words; two attempts came back 46%
    short and the rewrite fallback could not help. Room for the envelope's
    top, the JSON wrapper and hook candidates."""
    return int(max(2600, int(target_words) * 1.7 + 1200))


def _story_prompt(plan: NarrativeStoryPlan, target_words: int, cold_open: str,
                  strategy: NamedChannelStrategy, repair: str = "", original: str = "",
                  topic: str = "") -> str:
    mode = "REPAIR ONLY THIS STORY" if repair else "WRITE THIS STORY FROM SCRATCH"
    # The planner sized this premise; the caller's number is only the equal
    # share, used when a plan predates per-story budgets. Enforcing the equal
    # share made three unrelated stories come out the same length whatever they
    # were about — a premise needing a patient setup could not get it, and a
    # tight one was padded to fill its third.
    # The envelope stays ±10% as it was; the freedom comes from the planner
    # choosing the number it is drawn around, not from loosening the band.
    target_words = int(getattr(plan, "target_words", 0) or target_words)
    length_low = math.floor(target_words * 0.9)
    length_high = math.ceil(target_words * 1.1)
    # HOW THE MOST-WATCHED ACCOUNTS SPEND THEIR WORDS. Read in the corpus: a long
    # calm setup (who I am, the routine, the house), then every sign gets its
    # own stretch - the hour, what I was doing, what I heard or saw, what I
    # told myself, what I did, what I noticed after - and the worst rung gets
    # the most. A draft that gives each rung one paragraph comes in 46% short
    # and reads as a summary of a frightening night.
    _rungs = [r for r in (getattr(plan, "escalation_ladder", None) or []) if str(r).strip()]
    if _rungs:
        # The corpus's most-watched stories land the first wrongness at 130-300
        # words (median ~220, about ninety seconds spoken). Our first draft took
        # 470 and the operator called it: three minutes is too long to wait.
        _setup = min(300, int(target_words * 0.18))
        _after = int(target_words * 0.12)
        _worst = int(target_words * 0.22)
        _each = int((target_words - _setup - _after - _worst) / max(1, len(_rungs) - 1))
        dwell_block = (
            "SHAPE OF THE ACCOUNT (how the most-watched accounts spend their words; a shape, not a law):\n"
            f"  setup, before anything is wrong: at most {_setup} words - who you are, why you are there, the\n"
            "    routine, the house; the listener must be able to draw the floor plan, and every sentence\n"
            "    must load something that fires later. The FIRST WRONGNESS lands inside the first 300 words:\n"
            "    the most-watched accounts land it at ninety seconds. No mood paragraphs before it; anything\n"
            "    the floor plan does not need can arrive later, between signs.\n"            f"  each rung except the worst: about {_each} words - the exact hour, what you were doing, what you\n"
            "    heard or saw, what you did next, what you noticed afterwards. The denial-that-fails ('I\n"
            "    figured it was X, until...') is allowed TWICE in the whole account, early; every other rung is\n"
            "    a reaction - a lock checked, a light left on, a call made - not an explanation.\n"
            f"  the worst rung: about {_worst} words - slow it down; the body; the reasoning; the distances.\n"
            f"  after: about {_after} words - what was found, the line learned too late, what it cost, the remainder.\n"
        )
    else:
        dwell_block = ""
    obligations = _spoken_obligations(plan, topic)
    # Demonstrated voice beats described voice: the sample leads the prompt so
    # the writer CONTINUES a specific person instead of adopting adjectives.
    voice_block = (
        "CONTINUE THIS EXACT VOICE. The sample below is this narrator's own "
        "writing; your narration must read as the same person continuing the "
        "account. Do not slide into a generic storytelling voice.\n"
        f"VOICE SAMPLE:\n{plan.voice_seed.strip()}\n"
        "The sample is OFF-PAGE: continue its voice — sentence length, register, "
        "verbal habit — but never reuse its sentences, phrases, or facts in the "
        "narration.\n"
    ) if plan.voice_seed.strip() else ""
    return f"""{mode}
LOCKED STORY ID: {plan.story_id}
TITLE: {plan.title}
{voice_block}
{('SPOKEN OBLIGATIONS (each one is a hard release gate):' + chr(10) + obligations)
 if obligations else ''}
LENGTH: the plan estimates about {target_words} words. That is a shape, not a law. Write
what this account needs: every rung its own stretch of the night, the worst one slowest,
and stop when the remainder has been said. Never pad to reach a number; never summarise
a rung to stay under one. A draft that gives each rung a single paragraph is a summary of
a frightening night, not the night.
{dwell_block}THE EXAMPLE LINES IN THIS BRIEF ARE EXAMPLES. Never reuse their wording. Write the same
kind of sentence in this narrator's own words.
NARRATOR: {plan.narrator_profile}
SETTING/GEOGRAPHY: {plan.setting}
SPOKEN SETUP REQUIREMENT (must be established on the page before danger):
{plan.setup_requirement}
The SETTING/GEOGRAPHY and CONTINUITY LEDGER below are private continuity constraints:
never contradict them, but do not recite unit numbers, exits, or props that do not
affect the threat, a choice, the escape, or the ending.
{('ESCALATION LADDER (write it in THIS order; each rung is its own stretch of the night, '
   'and the narrator reacts to every rung before the next arrives):' + chr(10)
   + chr(10).join(f'  {i+1}. {r}' for i, r in enumerate(plan.escalation_ladder)) + chr(10))
  if getattr(plan, 'escalation_ladder', None) else ''}{(
  'WHAT STAYS (the page must deliver all four, in the narrator\'s plain words):' + chr(10)
  + (f'  NO WAY OUT, said plainly before the worst of it: {plan.no_way_out}' + chr(10) if getattr(plan, 'no_way_out', '') else '')
  + (f'  THE THREAT\'S MIND, reasoned out by the narrator during the night: {plan.threat_mind}' + chr(10) if getattr(plan, 'threat_mind', '') else '')
  + (f'  THE ALREADY LINE, learned after, one sentence, no build-up: {plan.already_line}' + chr(10) if getattr(plan, 'already_line', '') else '')
  + (f'  THE REMAINDER, the last thing said: {plan.remainder}' + chr(10) if getattr(plan, 'remainder', '') else '')
  + 'THE REPORT BEAT: after the first sign that cannot be explained away, the narrator either reports it and gets the half-answer (sounds like someone checking the house is occupied; install a camera; call 911 if he comes back) or says plainly why no report was possible. Days of silence with a working phone are not believed.' + chr(10)
  + 'THE BODY: at the worst rung the narrator goes still and says so in their own plain words - what they were holding, where their eyes went, what their hands did - and the denial fails out loud: the ordinary explanation is offered and then taken apart by the next thing heard. Do not reuse any phrasing from this brief.' + chr(10)
  ) if any(getattr(plan, k, '') for k in ('no_way_out', 'threat_mind', 'already_line', 'remainder')) else ''}THREAT: {plan.threat}
THREAT TYPE: {plan.threat_type}{f'''
WHAT MAKES THIS ONE NOT THE STOCK VERSION: {plan.distinguishing_turn}
This is the story's reason to exist. It must be legible on the page as something that
HAPPENS — a thing the threat does, wants, or knows — not as narrator commentary about
how unusual it was. If a viewer could watch this story and describe it in the same words
as the stock version of this premise, the story has failed even if every other beat is
clean.''' if plan.distinguishing_turn.strip() else ''}
REQUIRED PRACTICAL RESPONSE/ESCAPE: {plan.escape_action}
ENDING SHAPE: {plan.ending_shape}
EVIDENCE ALLOWANCE: {plan.evidence_allowance}{'''
"none" means NOTHING confirms the encounter afterwards: no second witness account, no
relief-shift corroboration, no official report or record, no recovered trace, no camera.
A PROMISE of follow-up is also confirmation ("they said someone would look into it",
"dispatch flagged it for review") — corroboration-by-authority, same defect (5th
occurrence of this class, this variant live 2026-07-20). The narrator's word stands
alone — that unconfirmed loneliness IS the dread. Adding even one validating detail in
the aftermath is a release-blocking defect.''' if plan.evidence_allowance == "none" else ''}
VOICE RULES: {plan.voice_rules}
CONTINUITY LEDGER: {json.dumps(plan.continuity_ledger, ensure_ascii=False)}
COLD-OPEN PROMISE TO PAY OFF: {cold_open}
If a cold-open promise is assigned above, pay off that MOMENT inside the narration;
never restate the cold-open sentence verbatim or near-verbatim in the story.
CHANNEL QUALITY STRATEGY ({strategy.strategy_id}):
{strategy.writer_rules}
{('REPAIR BRIEF: ' + repair) if repair else ''}
{('ORIGINAL NARRATION:\n' + original) if original else ''}

Return plain text in exactly this robust format (do not use JSON or markdown fences):
TITLE: one short title
HOOK: one optional alternate hook line
NARRATION:
the complete narration with natural paragraph breaks

The narration must be
natural spoken English in the narrator's first person, with paragraph breaks. Start in
an ordinary concrete situation; escalate through readable physical geography; make the
protagonist notice, choose, act, and adapt. Dialogue must sound incidental, not cinematic.
End within two beats of the strongest action or image.

PRIVATE FIVE-BEAT COMPLETION CONTRACT (do not print beat labels):
1. ordinary setup; 2. confirmed threat; 3. decision plus practical action;
4. COMPLETED locked escape exactly compatible with REQUIRED PRACTICAL RESPONSE/ESCAPE;
5. COMPLETED ending exactly compatible with ENDING SHAPE.
Before output, silently point to one exact sentence for every beat in that causal order.
Give every beat its OWN sentence: never complete two beats inside one sentence. The
decision (beat 3) and the completed escape (beat 4) especially need separate sentences —
a mechanical auditor must be able to quote each beat independently, and a merged
"grabbed the keys and was already out the door" sentence makes the story unauditable
and unreleasable no matter how good it reads.
Intent to escape is not escape completion. An ending that leaves the narrator inside the
active danger is not a completed ending unless the locked ending explicitly requires it.
Every verb and final location/state in the locked escape and ending must occur explicitly:
"leaves the building" means outside the building, not a lobby or stairwell; "gets inside
safely and calls" requires both safety and the call, not later evidence standing in for it.
Named places, times, orderings, PROP STATES, and WHO-IS-WITH-WHOM in escape_action and
the ledger are COORDINATES, not suggestions: "turns around at the wash" means AT the
wash — not before it, not past it; "calls after he leaves" means after, not while he is
still in the room; a propped door STAYS propped until someone on the page moves it; a
narrator who works "alongside her mother" is not alone two paragraphs later without an
on-page reason. Drifting one landmark, prop state, or companion breaks three beats at
once and blocks release.
When the locked escape has multiple clauses ("wedge the door AND trigger the alarm",
"lock the gate AND drive to a neighbor"), EVERY clause happens on the page, in order —
summarizing, merging, or dropping a clause fails the release audit.
{'''The locked escape ends with the threat withdrawing on its own: render the withdrawal
as menace (it chose to leave; it was not driven off), and the narrator's decision must
still be a real decision under pressure, not passive waiting.
''' if plan.escape_mechanism == "threat_withdraws_uncontested" else ''}Do not "preserve" a plan that keeps the threat outside by admitting the threat inside.
THE LAST SENTENCE IS THE STRONGEST IMAGE. Once the locked ending state is reached, STOP.
Never follow the ending with an explanatory, reflective, or theorizing sentence — no
lesson, no "I still wonder", no summary of what it probably was. Trailing explanation
after the ending is a release-blocking defect, not a style choice.
A flat, factual safety-report sentence ("We called the police from the neighbor's
kitchen.") does NOT count as trailing explanation and may stand inside the final two
beats; it must name the declared recipient in plain words (police/911, or the parent,
boss, named neighbour, or witness the plan declared). The STOP rule bans reflection,
interpretation, and lessons — never the locked safety response.
{'''CLOSING MOVE: the changed-ritual coda ("I still ...", "Now I always ...", "Ever
since, I ...") is RESERVED for the first story in the lineup — you are not writing the
first story, so do NOT close on a ritual or habit change. Close on a concrete image,
an unanswered detail, or a flat report instead — and do not OPEN your final sentence
with "I still" in ANY sense: "I still don't know what it was" is an unanswered detail,
but it shares the first story's closing rhythm and reads as one author (state the
unknown without that opener: "Nobody ever told me what it was"). Two same-rhythm codas
in one compilation block release; each writer only sees its own story, so the slot is
assigned here.
OPENING MOVE: the job-context intro ("I work the overnight desk at...", "I have been
driving this route for six years...") is likewise RESERVED for the first story. Open
THIS story inside a specific moment instead — mid-task, mid-sensation, or on the one
detail of that night that was already wrong — and let the job and tenure surface
within the first paragraph rather than announce themselves in sentence one. Two
stories opening on the same establish-my-job formula read as one author.
''' if not plan.story_id.endswith("_1") else ''}Do not print beat labels, a checklist, self-review, or compliance JSON.

HUMAN-RESPONSE PLAUSIBILITY (a release property, not a style choice): once the narrator
reaches safety from an active human threat, they use readily available help (police,
security, a trusted person) unless the story states a concrete reason not to. Never let a
character refuse an easy identity or safety check merely to preserve mystery, leave a
known person trapped with the threat without urgent help, re-enter the danger without
necessity, or take an action that contradicts a safety decision they just stated unless
the story shows a concrete forcing reason.

TEXTURE BUDGETS (deterministic gates read the finished prose — exceeding one costs a
rewrite): at most TWO one-word beat sentences ("Quiet." "Nothing."); at most ONE
"the way you..." comparison; at most ONE "it was no X, it was Y / not just X but Y"
reversal; at most TWO physical fear reactions, never stock ("heart pounded", "blood ran
cold", "stomach dropped", "little did I know" are banned outright — name the feeling
plainly in this narrator's register instead). A verbal habit must not repeat across the
compilation's stories. When sound precedes sight (as it should), do NOT render it with
the literal "I heard it before I saw it" scaffold — that exact construction is rationed
to one narrator per compilation and yours may not be the one; let the sound arrive
inside this narrator's own syntax (a wrong noise in a known rhythm, a sound out of
place for the hour) instead of announcing the ordering.

Forbidden: visual/SFX directions, host intro, CTA, recap, analysis, neat explanation,
"I told myself" or equivalent self-reassurance, arbitrary exact numbers, stacked proof,
camera/static clichés, footprints that vanish, decorative gore, trailer prose, and an
announced bare claim that the narrator never returned (a permanently changed routine
must be shown as one concrete ongoing behavior — parks somewhere else, double-checks
one lock — never announced as a declaration). Preserve the locked threat,
escape, evidence budget, ending shape, and all causal/spatial facts. Use no more than
{strategy.numeric_anchor_limit} unique exact numeric values total: clock times, ages,
durations, floors, unit numbers, counts, ordinals, and every passcode digit all count.
Prefer approximate, non-numeric phrasing unless the value changes a decision."""


def _plan_repair_prompt(
    plan: CompilationPlan,
    failed_ids: list[str],
    issues: list[PlanIssue],
    strategy: NamedChannelStrategy,
) -> str:
    payload = [
        item.model_dump(mode="json") for item in plan.stories
        if item.story_id in failed_ids
    ]
    objections = [
        {
            "story_id": item.story_id, "category": item.category,
            "severity": item.severity, "problem": item.problem,
            "plan_fix": item.plan_fix, "evidence_quote": item.evidence_quote,
        }
        for item in issues
    ]
    keep = [item.story_id for item in plan.stories if item.story_id not in failed_ids]
    # The repairer never saw the cold open (the payload is stories only), so a
    # cold_open objection came back as the identical plan. Show it, and make
    # the replacement a stated requirement at the top.
    cold_open_block = ""
    if any(item.category == "cold_open" for item in issues):
        cold_open_block = (
            "\nTHIS REPAIR MUST ALSO RETURN A NEW COLD OPEN. An objection below is category\n"
            "cold_open: the current cold open gives away the last rung. Return a top-level key\n"
            "\"cold_open\" (<=28 spoken words) that names the place, the fear or the object that\n"
            "changed — never the last rung's action. Returning the stories without it is the\n"
            "identical plan, and it will be rejected.\n"
            f"CURRENT COLD OPEN: {plan.cold_open}\n"
        )
    return f"""Repair ONLY the blocked stories in this locked plan. Do not redesign the
compilation; the other stories are already approved and are not yours to touch.

A skeptical domain auditor blocked these stories. Every objection is grounded in an
exact quote from the story's own plan text. Apply the plan_fix, or a better fix that
resolves the same objection.

{cold_open_block}
BLOCKED STORIES TO REPAIR: {failed_ids}
STORIES THAT MUST NOT CHANGE (do not return them): {keep}

OBJECTIONS:
{json.dumps(objections, ensure_ascii=False, indent=1)}

CURRENT PLAN FOR THE BLOCKED STORIES:
{json.dumps(payload, ensure_ascii=False, indent=1)}

CHANNEL QUALITY STRATEGY ({strategy.strategy_id}):
{strategy.planner_rules or strategy.writer_rules}

Return exactly one compact JSON object: {{"stories": [ ... ]}} containing one full
replacement story object per blocked story, with the SAME story_id, in the same order.
No markdown, no commentary, no prose outside the JSON — compact output, because a
truncated object throws the repair away unread.

EVERY story object needs ALL of these keys: story_id, title, narrator_profile,
setting, setup_requirement, threat, threat_type, escape_action, ending_shape,
evidence_allowance, voice_rules, voice_seed, threat_mechanism,
progression_mechanism, escape_mechanism, aftermath_mechanism, threat_identity,
topic_promise, distinguishing_turn, narrator_age_band, narrator_age_years,
safety_obligation, safety_omission_reason, continuity_ledger, escalation_ladder,
already_line, no_way_out, threat_mind, remainder.

WHERE EACH KIND OF OBJECTION IS FIXED. Three repair rounds on one plan each fixed
the escape and left the same knowledge_path hole standing, because the fix lived in
fields nobody told you to touch:
- knowledge_path: in the LADDER or the setup_requirement — plant the moment the fact
  could be taken (the card says get-well; the bag sat on a car seat; the form was read
  over a shoulder), one rung or one setup clause, never an explanation aloud.
- human_behavior about the narrator's response: in the LADDER rung where the sign
  happens — the call, the lock, the retreat go INTO that rung — and in escape_action.
- human_behavior about the threat stopping: in escape_action — the cause (lights,
  a shouted '911 is on the line', a siren, a dog) and the wait, in minutes.
- prop_staging: in setup_requirement or the props ledger line — one clause.
- ANY NEW FACT A REPAIR INTRODUCES (a dead line, a missing key, a dog that barks) must be planted
  in a rung or in setup_requirement in the same repair. Live: a repair declared 'the line still
  dead in her hand' at the climax while rung one had her calling the hospital on that phone.
- a missing already_line / no_way_out / threat_mind / remainder: write the field, AND plant
  what it needs in the ladder (the already_line must be set up by an early rung the
  listener passed over; no_way_out must be true of the house/night as planned).
Rungs you do not need to change stay word-for-word.
- cold_open: return an extra top-level key "cold_open" (<=28 spoken words). It must still
  SELL THE FEAR: a habit the night changed for good ('I never leave a window unlatched
  anymore'), an hour or a year, or the sign that someone came — without the last rung's
  action. 'That week I learned the mailbox was unlocked' is exposition, not a cold open.

HARD CONSTRAINTS the validator enforces before anyone reads your fix:
- continuity_ledger: exactly 5 entries, in this order and with these exact prefixes:
  "hook_timeline:", "people_objects:", "locations_exits:", "props_threat_position:",
  "response_escape:". **EACH ENTRY MUST BE 24 WORDS OR FEWER, including the prefix.**
  This is the single most common way a repair is thrown away unjudged — count the
  words. Cut adjectives, not facts.
- every other scalar stays under 35 words (voice_seed is exempt: it is a 2-3 sentence
  voice sample); setup_requirement is 3-35 words.
- topic_promise must repeat the compilation's exact subject wording AND name the site.
- distinguishing_turn: 4-25 words, distinct per story, and it must not simply restate
  that story's own threat field.

Keep each story's typed mechanisms (threat_mechanism, progression_mechanism,
escape_mechanism, aftermath_mechanism, threat_identity) unless the objection is
specifically about the mechanism — the repaired story must still differ from every
other story on every axis, so do not adopt another story's mechanism to fix this one. Change the least that
resolves the objection: keep the narrator, the setting, and the beats that were not
challenged."""


def _story_compliance_prompt(
    plan: NarrativeStoryPlan,
    story: StoryDraft,
    strategy: NamedChannelStrategy,
    contract_retry: str = "",
) -> str:
    return f"""Perform a narrow mechanical compliance audit of ONE horror story.
Do not score prose quality, rewrite text, infer missing action, or reward style.
{contract_retry}

Return exactly one JSON object with: story_id, plan_fingerprint, narration_sha256,
beats, plan_facts_status, plan_facts_quote, plan_facts_explanation,
evidence_budget_status, evidence_quote, evidence_explanation.

Echo these server values exactly:
story_id: {story.story_id}
plan_fingerprint: {_story_plan_fingerprint(plan)}
narration_sha256: {_narration_sha256(story)}

beats must contain exactly five objects in this order: ordinary_setup,
threat_confirmation, decision_action, completed_escape, completed_ending. Each object
has beat_id, locked_requirement, status (complete|partial|missing|contradicted), evidence_quote,
anchor_quote, explanation. complete/partial/contradicted require one exact unique quote
copied verbatim from the narration. missing requires one exact unique insertion anchor.
partial also requires an insertion anchor. Escape and ending are complete only when the
action occurs on the page, not when the narrator intends or begins it. Keep evidence in
narrative order.
Echo these locked_requirement values exactly:
ordinary_setup={json.dumps(plan.setup_requirement)};
threat_confirmation={json.dumps(plan.threat)}; decision_action and completed_escape=
{json.dumps(plan.escape_action)}; completed_ending={json.dumps(plan.ending_shape)}.
ordinary_setup is judged ONLY against that spoken setup_requirement. The plan's setting
and continuity_ledger are private continuity constraints, not exposition obligations:
never mark ordinary_setup partial or missing because a private unit number, exit,
window, or prop is unspoken; they matter only to plan_facts_status when narration
actively contradicts them.
Decompose every verb and final location/state. If the requirement says "leaves the
building," a lobby, stairwell, locked room, intention, or policy change is partial. If it
says "gets inside safely and calls," later physical evidence cannot substitute for either
action. If a locked boundary is crossed, later escape does not erase the contradiction.
Keep every explanation under 24 words. Emit the top-level keys in the order requested
and always include all three evidence_budget fields, even when status is unclear.

plan_facts_status is preserved|contradicted|not_demonstrated. Private ledger facts need
not all be spoken; only mark contradicted when narration conflicts with locked geography,
threat position, people/objects, response, or causal order, and then copy the exact quote.
In particular, admitting a threat across a locked boundary that the escape plan says to
hold is contradicted, even if the narrator later escapes another way.
evidence_budget_status is preserved|violated|unclear and concerns only aftermath proof,
not live safety actions, phones, doors, clothing, keys, or objects used during escape.
For violated, copy one exact quote. No markdown and no approval field.

CHANNEL STANDARD ({strategy.strategy_id}):
{strategy.critic_rules}

LOCKED PLAN:
{plan.model_dump_json(indent=2)}

NARRATION:
{story.narration}
"""


def _parse_story_output(text: str, plan: NarrativeStoryPlan) -> StoryOutput:
    """Accept compact JSON, a paragraph array, or plain narration.

    Long prose with dialogue is needlessly fragile when forced through one JSON
    string. This adapter keeps plan fields authoritative and only salvages narration.
    """
    raw = (text or "").strip()
    payload = None
    try:
        payload = json.loads(raw)
    except Exception:
        pass
    if isinstance(payload, dict):
        try:
            return StoryOutput.model_validate(payload)
        except Exception:
            narration = payload.get("narration") or payload.get("story") or payload.get("content")
            if isinstance(narration, list):
                narration = "\n\n".join(str(item).strip() for item in narration if str(item).strip())
            if isinstance(narration, str) and narration.strip():
                hooks = payload.get("hook_candidates") or []
                if isinstance(hooks, str):
                    hooks = [hooks]
                return StoryOutput(
                    title=str(payload.get("title") or plan.title),
                    hook_candidates=[str(item) for item in hooks[:3]] or [narration.split(".", 1)[0]],
                    narration=narration.strip(),
                )
    if isinstance(payload, list) and all(isinstance(item, str) for item in payload):
        narration = "\n\n".join(item.strip() for item in payload if item.strip())
        return StoryOutput(
            title=plan.title, hook_candidates=[narration.split(".", 1)[0]], narration=narration
        )
    marker = re.search(r"(?:^|\n)NARRATION:\s*\n?([\s\S]+)$", raw, re.I)
    if marker:
        narration = marker.group(1).strip()
        title_match = re.search(r"(?:^|\n)TITLE:\s*(.+)", raw, re.I)
        hook_match = re.search(r"(?:^|\n)HOOK:\s*(.+)", raw, re.I)
        return StoryOutput(
            title=title_match.group(1).strip() if title_match else plan.title,
            hook_candidates=[hook_match.group(1).strip()] if hook_match else [
                narration.split(".", 1)[0]
            ],
            narration=narration,
        )
    narration = raw
    fenced = re.search(r"```(?:text|markdown)?\s*([\s\S]+?)\s*```", narration, re.I)
    if fenced:
        narration = fenced.group(1).strip()
    if not narration:
        raise ValueError(f"Writer returned no narration for {plan.story_id}")
    return StoryOutput(
        title=plan.title, hook_candidates=[narration.split(".", 1)[0]], narration=narration
    )


def _repair_patch_prompt(plan: NarrativeStoryPlan, original: str,
                         issues: list[StoryIssue], gate_messages: list[str],
                         target_words: int, strategy: NamedChannelStrategy) -> str:
    issue_payload = [issue.model_dump() for issue in issues]
    current_words = len(_words(original))
    # These numbers mirror _apply_story_patch exactly; a candidate that ignores
    # them is rejected locally without a second creative brief.
    edit_budget = max(30, math.floor(current_words * 0.20))
    shrink_limit = math.floor(current_words * 0.10)
    return f"""Surgically repair only the listed defects in this locked story.
STORY ID: {plan.story_id}
CURRENT LENGTH: {current_words} words
REQUIRED LENGTH ENVELOPE: {math.floor(target_words * 0.9)}-{math.ceil(target_words * 1.1)} words
EDIT BUDGET: each candidate may change at most {edit_budget} words in total across all
its edits (counting the larger of each find/replace), may grow the story by at most 180
words, and may shrink it by at most {shrink_limit} words.
LOCKED THREAT: {plan.threat}
LOCKED ESCAPE: {plan.escape_action}
LOCKED ENDING SHAPE: {plan.ending_shape}
FORENSIC ISSUES:
{json.dumps(issue_payload, ensure_ascii=False)}
DETERMINISTIC GATE MESSAGES:
{json.dumps(gate_messages, ensure_ascii=False)}
CHANNEL QUALITY STRATEGY ({strategy.strategy_id}):
{strategy.writer_rules}

Return exactly one compact JSON object with key candidates. candidates is an array of
EXACTLY TWO independently proposed objects. Each has candidate_id (candidate_1 or
candidate_2) and edits (1-8 objects with find and replace). Every candidate must be
applied directly to ORIGINAL, never to the other candidate. find MUST be a verbatim,
unique substring from ORIGINAL and no find ranges may overlap. replace is the smallest
edited replacement. Keep every find at 120 words or fewer; use separate non-overlapping
edits for separate defects instead of swallowing adjacent clean paragraphs. Do not
rewrite clean paragraphs, change names, invent proof, or
alter the locked plan. The two candidates must solve the issue differently. No markdown.
When FORENSIC ISSUES are present without deterministic gate messages, every find must
contain (or be contained by) an exact evidence_quote/anchor_quote supplied above.

ORIGINAL:
{original}"""


def validate_forensic_issues(
    score: NarrativeScorecard, stories: list[StoryDraft]
) -> list[str]:
    """Validate that every actionable issue is grounded in one named story."""
    story_map = {story.story_id: story.narration for story in stories}
    errors: list[str] = []
    for index, issue in enumerate(score.story_issues):
        if issue.severity == "minor":
            continue
        prefix = issue.issue_id or f"issue_{index + 1}"
        narration = story_map.get(issue.story_id)
        if narration is None:
            errors.append(f"{prefix}: unknown story_id {issue.story_id}")
            continue
        quote = issue.anchor_quote if issue.issue_kind == "omission" else issue.evidence_quote
        if not quote:
            errors.append(f"{prefix}: missing exact forensic quote")
            continue
        own_count = narration.count(quote)
        other_story = next(
            (sid for sid, text in story_map.items() if sid != issue.story_id and quote in text),
            None,
        )
        if own_count == 0:
            suffix = f"; quote belongs to different story {other_story}" if other_story else ""
            errors.append(f"{prefix}: quote not found in named story{suffix}")
        elif own_count != 1:
            errors.append(f"{prefix}: quote must be unique in named story")
    if score.critical_issues and not any(
        issue.severity == "critical" for issue in score.story_issues
    ):
        errors.append("Compilation critical issue lacks a structured critical story issue")
    return errors


def _apply_story_patch(
    story: StoryDraft,
    patch: StoryPatchOutput,
    *,
    allowed_anchors: list[str] | None = None,
) -> StoryDraft:
    """Apply a candidate atomically against one immutable baseline."""
    baseline = story.narration
    story_word_count = max(1, len(_words(baseline)))
    spans: list[tuple[int, int, str]] = []
    changed_words = 0
    delta_words = 0
    for edit in patch.edits:
        find = edit.find
        replacement = edit.replace
        if not find or baseline.count(find) != 1:
            raise ValueError("Patch is not atomic: every find must be exact and unique in baseline")
        if not replacement:
            raise ValueError("Destructive empty replacement is forbidden")
        start = baseline.index(find)
        end = start + len(find)
        find_words = len(_words(find))
        replace_words = len(_words(replacement))
        if find_words > 120:
            raise ValueError("Patch find region is too large for a surgical edit budget")
        if any(not (end <= old_start or start >= old_end) for old_start, old_end, _ in spans):
            raise ValueError("Patch edits overlap in the immutable baseline")
        if any(edit.find in prior_replacement for _, _, prior_replacement in spans):
            raise ValueError("Patch candidates may not cascade from generated replacement text")
        if allowed_anchors and not any(
            anchor and (anchor in find or find in anchor) for anchor in allowed_anchors
        ):
            raise ValueError("Patch find does not overlap an approved forensic anchor")
        changed_words += max(find_words, replace_words)
        delta_words += replace_words - find_words
        spans.append((start, end, replacement))
    if changed_words > max(30, math.floor(story_word_count * 0.20)):
        raise ValueError("Patch exceeds the story edit budget")
    if abs(delta_words) > 180 or delta_words < -math.floor(story_word_count * 0.10):
        raise ValueError("Patch is destructive or exceeds the word-delta budget")

    narration = baseline
    for start, end, replacement in sorted(spans, reverse=True):
        narration = narration[:start] + replacement + narration[end:]
    return story.model_copy(update={"narration": narration})


def materialize_patch_candidates(
    story: StoryDraft,
    candidate_set: StoryPatchCandidateSet,
    *,
    allowed_anchors: list[str] | None = None,
) -> dict[str, StoryDraft]:
    return {
        candidate.candidate_id: _apply_story_patch(
            story, candidate, allowed_anchors=allowed_anchors
        )
        for candidate in candidate_set.candidates
    }


def resolve_blind_patch_selection(
    selected_candidate_id: str,
    baseline: StoryDraft,
    candidates: dict[str, StoryDraft],
) -> StoryDraft:
    """Fail closed: baseline wins ties, unknown labels, and missing candidates."""
    if selected_candidate_id.lower() in {"tie", "baseline", "original", "none", ""}:
        return baseline
    return candidates.get(selected_candidate_id, baseline)


def _critic_prompt(
    plan: CompilationPlan,
    stories: list[StoryDraft],
    gate: GateReport,
    strategy: NamedChannelStrategy,
    contract_retry: str = "",
) -> str:
    material = "\n\n".join(
        f"### {story.story_id}: {story.title}\n{story.narration}" for story in stories
    )
    return f"""Audit this horror compilation as a severe story editor, not a fan.
Score ONLY spoken narrative quality. Do not score visuals, SFX, prosody, stock-footage
suitability, formatting, or production readiness.

RUBRIC: continuity_believability /25; distinct_authentic_voices /20;
dread_escalation /20; plausible_response /10; structural_variety /10;
originality /10; ending_discipline /5.
TIMESTAMP THE FIRST SIGN. Count the words before the first wrongness (the first ladder
rung reaching the page). More than 300 is a MAJOR pacing issue: the most-watched accounts
land it by ~220 words; three minutes of routine loses the viewer before the first sign.
Quote the sentence where the first sign lands and state the word count.
EVERY LADDER RUNG ON THE PAGE. For each escalation_ladder rung in the locked plan, the
page must contain the event (not a summary of it). A missing rung is a MAJOR omission —
especially a rung that plants the knowledge path (the fact read aloud, the bag left in
the car): without it the threat knows things by magic. Name the missing rung.
COUNT THE DENIAL BEATS. The denial-that-fails ('I figured it was the wind, until...') is
the genre's move and it is allowed TWICE in one account. Count every instance, in any
phrasing — a harmless reading offered for a sign and then taken apart. Three or more is a
MAJOR style issue: quote each one so the repair can cut the extras, and say which two to
keep (the earliest). Five of them flattens the ladder into one repeated move.
AFTERMATH FACTS MUST BE KNOWABLE. What the police or a relative reports afterwards has to
be something a person could actually find: prints in raked dirt, pry marks, a company with
no driver on that route, a man's own admission. A deputy cannot tell from a crease that a
note was 'refolded from the outside'. An unknowable aftermath fact is a major continuity
issue: the listener's re-read of the night rests on it.
IF THE COMPILATION HAS ONE STORY, there is no lineup to compare. Score
distinct_authentic_voices on that one voice alone: is it a specific person with a
trade, a cadence and a way of reasoning, held for the whole account without slipping
into a generic narrator? Score structural_variety on the account's internal shape: does
the pace change between the routine, the signs, the worst stretch and the after, or is
every paragraph the same size and speed? Never cap either dimension for 'lack of
comparative material' — a single account that earns 20 and 10 must receive them.

CHANNEL STANDARD ({strategy.strategy_id}):
{strategy.critic_rules}
{contract_retry}

Use the locked plan to catch geography, timing, knowledge, object/count, threat-position,
and cause/effect errors. A critical issue is a contradiction or physically impossible
action, not merely weak prose. story_issues must identify the exact story and give a
minimal actionable repair; do not request a whole-compilation rewrite. Scores must be
earned: polished grammar is not authenticity, action is not automatically dread, and
unexplained evidence is often cliché rather than mystery.

EMOTION NAMING IS NOT A DEFECT: a person recounting a night often names a feeling plainly in their
own register ("honestly it just pissed me off", "I was scared, plain and simple"). Do
not penalize that; engineered bodily show-don't-tell (pounding heart, cold blood, spine
chills) repeated in every story is the machine's fingerprint, and THAT is the defect.
Do not penalize a single unexploited concrete detail as a structural flaw; in this genre
an observation that never pays off is an authenticity feature, not a plot hole.

A narrator whose register turns LITERARY — elegiac similes, poetic cadence ("the way
something leaves a room it was never in any hurry to enter"), nineteenth-century
rhythm — breaks the ordinary-person frame even when every fact is clean. File it
as a style issue against that story; a forum post is not a short story.

VOICE DEFECTS (score under distinct_authentic_voices): a voice defect exists when two
or more stories share a sentence-level habit — the same opening rhythm, the same filler
phrase, the same paragraph-closing fragment pattern, or the same rhetorical device
(negation triads, "the way you..." comparisons, one-word beat sentences). Report it as
a style issue filed against ONE story (the weaker offender), with evidence_quote copied
exactly from that story; in the problem field, quote verbatim the matching habit from
the other story and name its story_id. If the habit spans all three stories, file it
against the story whose voice is least distinct. As a lineup test: a mid-story paragraph
with names removed should be attributable to its narrator; if any two are
interchangeable, voice differentiation fails.

Evidence allowance governs AFTER-THE-FACT corroboration added to prove the encounter
(later footage, official confirmation, recovered traces, witnesses, recurrence). It does
not forbid ordinary objects observed during danger, an intruder's key or clothes, a live
safety action, a phone, a door/window latch, or details needed for escape. Never cite
those live details as violations of evidence_allowance.

Severity calibration is strict: critical = a story-breaking contradiction or impossible
action; major = a clear local continuity/cause-effect contradiction that materially
breaks belief; minor = clarity, wording, or a non-breaking ambiguity. A consistent
under-confirmed anomaly is the premise of horror, not a continuity defect merely because
its mechanism is unexplained. Do not label an editorial preference as major.

Obvious human-safety failures are at least major, never minor: a character who refuses
an easy identity/safety check (a callback, a name check, a peephole) only to preserve mystery;
a narrator who fails or delays urgent help after trapping or escaping an active
human threat without a concrete stated reason; a narrator who chooses to re-enter the
danger without necessity; or an action that contradicts a safety decision the character
just stated with no forcing reason on the page.
Also major: days of silence after a sign that cannot be explained away (prints under the
window, prints circling the house) with a working phone and no stated reason. The genre's
own narrators report it and get a half-answer; that beat, or the reason it was impossible,
must be on the page.

The plan's setting and continuity_ledger are private continuity constraints. Only each
story's setup_requirement must be spoken on the page before danger. Never raise an
omission because private setting or ledger facts are unspoken; raise a contradiction only
when the narration actively conflicts with them.

For EACH story, explicitly verify that the locked escape_action occurs on the page and
that the locked ending_shape is actually completed. A story that stops mid-confrontation,
before the promised escape/response or ending, is incomplete and must receive a critical
or major issue with an instruction to append only the missing beats. Do not confuse a
sentence-level cliffhanger with a finished story.
Decompose every verb and terminal location/state in escape_action and ending_shape. A
story in a lobby has not "left the building"; a policy about future calls does not replace
leaving tonight; later evidence does not replace "gets inside safely and calls." Mark the
omission major even when the prose has a polished final paragraph. Likewise, if the plan
keeps a threat outside, admitting it is a contradiction even if another escape later works.

Return exactly one JSON object with these keys: continuity_believability (integer),
distinct_authentic_voices (integer), dread_escalation (integer), plausible_response
(integer), structural_variety (integer), originality (integer), ending_discipline
(integer), critical_issues (array of strings), story_issues (array), editorial_summary
(string). Every story_issues item has story_id, severity (critical|major|minor), problem,
and repair_instruction, issue_kind (contradiction|omission|style), evidence_quote,
anchor_quote, confidence (0-1), viewer_impact, and issue_id. Every major/critical
contradiction or style issue must copy one exact unique evidence_quote from its named
story. Every major/critical omission must copy one exact unique anchor_quote identifying
where the missing beat belongs. If you cannot ground it exactly, lower it to minor. A
free-form critical_issues item is invalid unless backed by a structured critical issue.
No markdown or commentary.

LOCKED PLAN:
{plan.model_dump_json(indent=2)}

DETERMINISTIC FINDINGS:
{gate.model_dump_json(indent=2)}

SCRIPT:
{material}
"""


def _split_beats(story: StoryDraft) -> list[tuple[str, str]]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", story.narration) if part.strip()]
    groups: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        size = len(_words(sentence))
        if current and count + size > 48:
            groups.append(" ".join(current))
            current, count = [], 0
        current.append(sentence)
        count += size
        if count >= 30:
            groups.append(" ".join(current))
            current, count = [], 0
    if current:
        groups.append(" ".join(current))
    if not groups and story.narration.strip():
        groups = [story.narration.strip()]
    return [(f"{story.story_id}_beat_{index:02d}", text) for index, text in enumerate(groups, 1)]


def _annotation_prompt(
    story: StoryDraft,
    beats: list[tuple[str, str]],
    strategy: NamedChannelStrategy,
) -> str:
    payload = [{"beat_id": beat_id, "voiceover_reference": text} for beat_id, text in beats]
    return f"""Add production metadata to these locked horror narration beats.
Return exactly one JSON object with story_id={story.story_id} and beats (array), with no
markdown or commentary. Every beats item has beat_id, visual_prompt, sfx (string or
null), pace (slow|normal|fast), pause_after_ms (integer), and emphasis (array). Return
exactly one annotation per beat_id, in
the same order. Do NOT return, quote, rewrite, shorten, or add voiceover. For each beat:
visual_prompt is a concrete, plausible stock-footage/amateur-photo query with no visible
text; sfx is null unless a diegetic sound is clearly earned; pace is slow/normal/fast;
pause_after_ms is usually 0-250 with only rare 400-900 dramatic silences; emphasis may
contain only exact words present in that beat.
CHANNEL METADATA RULES: {strategy.annotation_rules}

BEATS:
{json.dumps(payload, ensure_ascii=False)}"""


def _blind_selector_prompt(
    plan: NarrativeStoryPlan,
    options: list[tuple[str, StoryDraft]],
    issues: list[StoryIssue],
    strategy: NamedChannelStrategy,
) -> str:
    payload = [
        {"label": label, "title": draft.title, "narration": draft.narration}
        for label, draft in options
    ]
    return f"""Select the best version of one locked horror story. The options are blind:
you are not told which is the original. Prefer the existing text on a tie. A changed
version wins only if it resolves the exact target issues without weakening voice, dread,
ending discipline, physical continuity, or the locked plan.

LOCKED PLAN: {plan.model_dump_json(indent=2)}
TARGET ISSUES: {json.dumps([item.model_dump() for item in issues], ensure_ascii=False)}
CHANNEL STANDARD ({strategy.strategy_id}): {strategy.critic_rules}
OPTIONS: {json.dumps(payload, ensure_ascii=False)}

Return exactly one JSON object with selected_label, confidence, preserves_locked_plan,
resolves_target_issues, introduced_issues (array), voice_regression, dread_regression,
ending_regression, and rationale. No markdown."""


def _final_review_prompt(
    plan: CompilationPlan,
    stories: list[StoryDraft],
    strategy: NamedChannelStrategy,
    contract_retry: str = "",
) -> str:
    material = "\n\n".join(
        f"### {story.story_id}: {story.title}\n{story.narration}" for story in stories
    )
    return f"""Perform a final read-only compilation audit. You may reject; you may not
rewrite prose. Check shared author voice across stories, repeated ending mechanisms,
manufactured specificity, clichÃ© proof, causal/spatial continuity, promised escape,
and whether the strongest ending is followed by an unnecessary explanation.
For every story, compare every verb and terminal location/state in escape_action and
ending_shape to exact on-page action. Lobby is not "outside the building"; intention,
policy, or aftermath evidence is not completion. Reject polished but incomplete endings.
Obvious human-safety failures are at least major: refusing an easy identity/safety
verification only to preserve mystery, failing or delaying urgent help after trapping or
escaping an active human threat without a concrete stated reason, or a narrator who
chooses to re-enter the danger without necessity.
Days of silence after a sign that cannot be explained away, with a working phone and no
stated reason, are the same failure. The repair is a report beat (the call, the
half-answer) or one plain sentence on why none was possible — not a rewrite.
TIMESTAMP THE FIRST SIGN. Count the words before the first wrongness (the first ladder
rung reaching the page). More than 300 is a MAJOR pacing issue: the most-watched accounts
land it by ~220 words; three minutes of routine loses the viewer before the first sign.
Quote the sentence where the first sign lands and state the word count.
EVERY LADDER RUNG ON THE PAGE. For each escalation_ladder rung in the locked plan, the
page must contain the event (not a summary of it). A missing rung is a MAJOR omission —
especially a rung that plants the knowledge path (the fact read aloud, the bag left in
the car): without it the threat knows things by magic. Name the missing rung.
COUNT THE DENIAL BEATS. The denial-that-fails ('I figured it was the wind, until...') is
the genre's move and it is allowed TWICE in one account. Count every instance, in any
phrasing — a harmless reading offered for a sign and then taken apart. Three or more is a
MAJOR style issue: quote each one so the repair can cut the extras, and say which two to
keep (the earliest). Five of them flattens the ladder into one repeated move.
Lexical sanity: flag invented objects, garments, or nonsense bigrams that a TTS voice
would read aloud verbatim (e.g. "gate pants") — the narration is spoken, not skimmed.
{contract_retry}

CHANNEL STANDARD ({strategy.strategy_id}):
{strategy.critic_rules}

Return exactly one JSON object with approved (boolean), issues (array), and summary.
Also return reviewed_story_ids containing every story_id in locked-plan order.
Every issue uses the StoryIssue schema and every major/critical issue must include the
same exact forensic quote contract as the scoring audit. Minor taste notes may be
ungrounded but do not force rejection. approved must be false if any major/critical
issue remains. No revised narration, markdown, or extra fields.

Use this exact shape and exact key names:
{{"approved": true, "reviewed_story_ids":
{json.dumps([item.story_id for item in plan.stories])},
"issues": [], "summary": "one concise audit"}}
If issues is non-empty, every item has exactly: story_id, severity, problem,
repair_instruction, issue_kind, evidence_quote, anchor_quote, confidence,
viewer_impact, issue_id. Do not substitute keys such as quote, excerpt, finding,
description, fix, verdict, or reason.

LOCKED PLAN:
{plan.model_dump_json(indent=2)}

SCRIPT:
{material}"""


_CHALLENGE_AXES: tuple[tuple[str, str], ...] = (
    ("physical_possibility", (
        "Every action is physically executable in the stated space. If a body fills a "
        "gap shoulder to shoulder, nothing rides past its shoulder through that gap. "
        "Count the exits a narrator lists against the exits they name."
    )),
    ("timeline_consistency", (
        "Stated durations, tenses, and elapsed time agree. 'This morning' cannot be "
        "followed by an ending that reports an established habit change nobody has "
        "asked about yet; 'five weeks' cannot also be 'a hundred times'."
    )),
    ("semantic_repetition", (
        "Two stories must not share one beat sheet under different scenery. Compare "
        "threat behaviour, escalation, escape, and aftermath as EVENTS, not wording: "
        "'silent watcher blocks route -> flee to a lit occupied place -> locked in -> "
        "same route, one thing changed' told twice is a fail even with new nouns."
    )),
    ("topic_alignment", (
        "Every story delivers the subject the compilation title promises. A title that "
        "says newspapers and a story that delivers packages is a fail."
    )),
    ("safety_response", (
        "After escaping an active human threat, the response is what a real person "
        "does. A near-abduction of a child with no police or adult report, and no "
        "stated reason for the silence, is a fail."
    )),
    ("plan_fidelity", (
        "The narration does not contradict the locked plan's era, timeline, narrator "
        "age, or ending stop point, and it speaks the facts the plan said it would."
    )),
    ("forbidden_ending", (
        "The story does not close by disclaiming curiosity ('I never went back to find "
        "out who he was') or with explanation after the locked ending state."
    )),
    ("self_reassurance", (
        "EMPTY self-reassurance is the fail: 'I told myself it was nothing / fine / my "
        "imagination' and its paraphrases — waving a sign away with no alternative. The "
        "denial-that-fails with a SPECIFIC alternative is the genre itself, read in its "
        "most-watched accounts: 'I told myself it was just a small company delivery', "
        "'I figured it was another camper who had gone to sleep', 'a branch, maybe, except "
        "there was no wind' — an ordinary reading offered, then taken apart by the next thing "
        "seen or heard. That is the narrator reasoning out loud and it PASSES. Fail only the "
        "empty form, or a specific form used three or more times in one account."
    )),
)


def _release_challenge_prompt(
    plan: CompilationPlan,
    stories: list[StoryDraft],
    strategy: NamedChannelStrategy,
    contract_retry: str = "",
) -> str:
    material = "\n\n".join(
        f"### {story.story_id}: {story.title}\n{story.narration}" for story in stories
    )
    axes = "\n".join(f"- {name}: {rule}" for name, rule in _CHALLENGE_AXES)
    return f"""You are the adversarial release challenger. Another editor has already
APPROVED this compilation for publication. Your job is not to agree with them. Assume
the approval is wrong and find the specific reason. If you cannot find one, say so
plainly — but look first, because a compilation reaches you only after it has already
passed every other gate, which is exactly when a shared blind spot ships.

Return a verdict for EVERY axis below. Judge events and physics, not prose quality.

{axes}
{contract_retry}

CHANNEL STANDARD ({strategy.strategy_id}):
{strategy.critic_rules}

Return exactly one JSON object: {{"verdicts": [...], "summary": "one line"}}. Every
verdicts item has axis (exactly one of the axis names above), verdict ("pass" or
"fail"), story_id (the offending story, or "" for a compilation-level finding),
evidence_quote, and explanation. Emit exactly one verdict per axis.

A "fail" verdict MUST copy one exact, unique, verbatim quote from the offending
story's narration into evidence_quote — copied character for character, not
paraphrased, summarized, or reconstructed. A fail you cannot quote is a fail you
cannot prove, and it will be discarded. For semantic_repetition and topic_alignment,
quote the single clearest offending sentence from the story you name. A "pass"
verdict needs no quote. No markdown, no commentary, no extra fields.

COMPILATION TOPIC: {plan.topic}

LOCKED PLAN:
{plan.model_dump_json(indent=2)}

SCRIPT:
{material}"""


def _annotation_covers(annotation: StoryAnnotation, beats: list[tuple[str, str]]) -> bool:
    expected = [beat_id for beat_id, _ in beats]
    actual = [beat.beat_id for beat in annotation.beats]
    return actual == expected and all(beat.visual_prompt.strip() for beat in annotation.beats)


def _assemble(plan: CompilationPlan, stories: list[StoryDraft],
              annotations: list[StoryAnnotation]) -> ScriptDraft:
    annotation_map = {item.story_id: item for item in annotations}
    segments: list[ScriptSegment] = []
    all_scene_voiceover: list[str] = []
    for index, story in enumerate(stories, 1):
        beats = _split_beats(story)
        by_id = {item.beat_id: item for item in annotation_map[story.story_id].beats}
        scenes: list[ScriptScene] = []
        for beat_id, voiceover in beats:
            item = by_id[beat_id]
            scene = ScriptScene(
                voiceover=voiceover,
                visual_prompt=item.visual_prompt,
                sfx=item.sfx,
                duration_s=round(len(_words(voiceover)) / 2.5, 2),
                pace=item.pace,
                pause_after_ms=item.pause_after_ms,
                emphasis=[word for word in item.emphasis if word.lower() in voiceover.lower()],
            )
            scenes.append(scene)
            all_scene_voiceover.append(voiceover)
        segments.append(ScriptSegment(
            index=index,
            heading=story.title,
            content=story.narration,
            estimated_duration_seconds=round(len(_words(story.narration)) / 2.5),
            scenes=scenes,
        ))

    source_voiceover = " ".join(story.narration for story in stories)
    scene_voiceover = " ".join(all_scene_voiceover)
    if " ".join(source_voiceover.split()) != " ".join(scene_voiceover.split()):
        raise ValueError("Production annotation changed punctuation, case, or locked voiceover")
    source_words = [word for story in stories for word in _words(story.narration)]
    assembled_hook = (
        "" if stories and stories[0].narration.strip().startswith(plan.cold_open.strip())
        else plan.cold_open
    )
    total_words = len(_words(assembled_hook)) + len(source_words)
    hook_scenes = ([ScriptScene(
        voiceover=assembled_hook,
        visual_prompt=(
            f"nighttime {plan.stories[0].setting}, practical available light, "
            "amateur documentary photo"
            if plan.stories else f"nighttime setting for {plan.topic}, amateur documentary photo"
        ),
        duration_s=round(len(_words(assembled_hook)) / 2.5, 2),
        pace="slow",
        pause_after_ms=500,
    )] if assembled_hook else [])
    return ScriptDraft(
        variant_id="unit_first",
        brief_title=plan.topic,
        hook=assembled_hook,
        hook_scenes=hook_scenes,
        segments=segments,
        outro="",
        raw_content="\n\n".join(story.narration for story in stories),
        estimated_duration_seconds=round(total_words / 2.5),
        word_count=total_words,
    )


def locked_voiceover_sha256(stories: list[StoryDraft]) -> str:
    canonical = "\n\n".join(story.narration for story in stories)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Scorecard dimensions paired with the strategy floor that can block release.
_RELEASE_DIMENSION_FLOORS = (
    ("continuity_believability", "continuity_min"),
    ("distinct_authentic_voices", "voice_min"),
    ("dread_escalation", "dread_min"),
    ("plausible_response", "plausible_response_min"),
    ("structural_variety", "structural_variety_min"),
    ("originality", "originality_min"),
    ("ending_discipline", "ending_min"),
)


def _salvage_cold_open(plan: CompilationPlan) -> CompilationPlan:
    """Deterministically trim an over-long cold open to its first sentence.

    The planner occasionally returns a two-sentence cold open a few words over
    the 28-word cap; rejecting the whole plan for that (observed live: preflight
    failed twice and the run died) throws away good story premises a local trim
    can save. Only a clean first-sentence cut is used — anything else still
    fails preflight normally."""
    if len(_words(plan.cold_open)) <= 28:
        return plan
    first = re.split(r"(?<=[.!?])\s+", plan.cold_open.strip())[0].strip()
    if first and len(_words(first)) <= 28:
        return plan.model_copy(update={"cold_open": first})
    # A single sentence over the cap used to fall through and fail preflight,
    # throwing away a plan whose six-rung ladder the auditor never saw (live
    # 2026-08-22, run 8 attempt 2). The cold open is a hook line, not the
    # premise: cut it at the last clause boundary inside 28 words. If there is
    # no boundary, cut at 28 — a truncated hook costs nothing the writer cannot
    # rebuild from the ladder, while a rejected plan costs the whole attempt.
    # Work on the ORIGINAL text, not on _words(): that tokeniser strips
    # punctuation, so rebuilding from it lost every comma in the kept half.
    source = (first or plan.cold_open).strip()
    spans = [m.span() for m in re.finditer(r"\S+", source)]
    head = source[: spans[27][1]] if len(spans) > 28 else source
    # Keep the full 28 words. An earlier version also backed up to the last
    # clause boundary, which on "my home address, not until his truck..."
    # found the comma after "address" and returned half a sentence. Twenty-
    # eight words with the tail removed reads fine; twelve words does not.
    if not head.endswith((".", "!", "?")):
        # Live: '... I check any lock twice before I.' — the 28th word was a
        # pronoun. Drop trailing function words before closing the sentence.
        _dangling = {"i", "a", "an", "the", "and", "or", "but", "before", "after", "to", "of",
                     "in", "on", "at", "for", "with", "that", "which", "who", "when", "while",
                     "until", "if", "as", "than", "so", "my", "his", "her", "their", "our", "its"}
        toks = head.rstrip(",;— -").split()
        while len(toks) > 8 and toks[-1].strip(",;:'\"").lower() in _dangling:
            toks.pop()
        head = " ".join(toks).rstrip(",;— -") + "."
    return plan.model_copy(update={"cold_open": head})


def _llm_identity_of(llm) -> tuple:
    """Identify the thing behind a client, not the variable pointing at it.

    Real clients compare on resolved (provider, model): the CapabilityBus can map
    two differently-named preferences onto one provider, so "anthropic" and
    "deepseek" variables are not evidence of two providers. Anything without that
    shape (test fakes) falls back to object identity.
    """
    provider = getattr(llm, "_provider", None) or getattr(llm, "provider", None)
    model = getattr(llm, "_model", None) or getattr(llm, "model", None)
    if provider:
        return ("client", str(provider), str(model or ""))
    return ("object", id(llm))


def _plan_material_digest(plan: CompilationPlan) -> str:
    """Identity of a plan's full content, not just its concept.

    Used to tell "the planner ignored the feedback and resent the same object"
    apart from "the planner fixed the defect and kept the concept" — the second is
    exactly what a replan is supposed to look like.
    """
    payload = json.dumps(
        {
            "cold_open": plan.cold_open,
            "stories": [item.model_dump(mode="json") for item in plan.stories],
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _plan_freshness_errors(
    candidate: CompilationPlan,
    forbidden_fingerprints: set[str],
    spent_concepts: list[CompilationPlan],
) -> list[str]:
    """Enforce 'fresh concept' instead of asking a model for one politely.

    The outer retry used to put "plan a DIFFERENT concept" in the prompt and then
    accept whatever came back, including the same three beats with new street
    names. Freshness is checked against typed mechanisms before a plan can reach a
    writer call.

    Scope matters: this compares against concepts a PREVIOUS OUTER ATTEMPT actually
    generated. A candidate rejected inside this run's own planner loop was never
    spent on anything, so it must not burn its concept — otherwise the first
    rejection makes every repair of that rejection unacceptable, and a fixable
    plan can never be fixed. Intra-loop repeats are caught by _plan_repeat_errors.
    """
    if plan_concept_fingerprint(candidate) in forbidden_fingerprints:
        return [
            "this exact concept (the same typed threat/progression/escape/aftermath "
            "mechanisms) has already been generated for this channel; produce "
            "materially different mechanisms, not different wording"
        ]
    for prior in spent_concepts:
        if plans_are_materially_equivalent(candidate, prior):
            shared = shared_story_concepts(candidate, prior)
            return [
                f"{shared} of {len(candidate.stories)} stories reuse a concept that has "
                "already been generated for this channel; rewording a spent beat sheet "
                "is not a fresh concept"
            ]
    return []


_MIN_DISTINGUISHING_TURN_WORDS = 4
_MAX_DISTINGUISHING_TURN_WORDS = 25
# Above this share of its own threat/title tokens, the "turn" is a paraphrase of
# the premise rather than the thing that bends it away from the genre default.
_DISTINGUISHING_TURN_ECHO_RATIO = 0.8


def _premise_freshness_errors(plan: CompilationPlan) -> list[str]:
    """Make "what makes this one different" a field, not a hope.

    Every other freshness check in this file compares TYPED mechanisms, which is
    why three stock human-threat premises with different mechanism labels pass
    everything and still read as genre defaults to the critic. This one asks each
    story to say, in its own clause, what the default would have done instead —
    and refuses a clause that merely restates the threat.
    """
    errors: list[str] = []
    seen: dict[str, str] = {}
    for item in plan.stories:
        turn = (item.distinguishing_turn or "").strip()
        if not turn:
            errors.append(
                f"{item.story_id} must declare distinguishing_turn: one clause naming what "
                "makes this premise unlike the stock version of itself. A premise no one can "
                "distinguish from its genre default scores originality below the release "
                "floor, and originality cannot be repaired after the prose exists"
            )
            continue
        words = _words(turn)
        if len(words) < _MIN_DISTINGUISHING_TURN_WORDS:
            errors.append(
                f"{item.story_id} distinguishing_turn {turn!r} is too short to name a "
                f"mechanism; use at least {_MIN_DISTINGUISHING_TURN_WORDS} words"
            )
            continue
        if len(words) > _MAX_DISTINGUISHING_TURN_WORDS:
            errors.append(
                f"{item.story_id} distinguishing_turn must stay at or under "
                f"{_MAX_DISTINGUISHING_TURN_WORDS} words; it is one clause, not a synopsis"
            )
            continue
        normalized = _normal(turn)
        if normalized in seen:
            errors.append(
                f"{seen[normalized]} and {item.story_id} claim the same distinguishing_turn; "
                "one departure from the genre default shared by two stories is not a "
                "departure, it is this compilation's own template"
            )
        else:
            seen[normalized] = item.story_id
        turn_tokens = set(words)
        premise_tokens = set(_words(f"{item.threat} {item.title}"))
        if turn_tokens and premise_tokens:
            echo = len(turn_tokens & premise_tokens) / len(turn_tokens)
            if echo >= _DISTINGUISHING_TURN_ECHO_RATIO:
                errors.append(
                    f"{item.story_id} distinguishing_turn {turn!r} restates its own threat "
                    "instead of distinguishing it; name what the stock version of this "
                    "premise would have done and what this one does instead"
                )
    return errors


def _plan_repeat_errors(candidate: CompilationPlan, rejected_digests: set[str]) -> list[str]:
    """Catch a planner that resends a rejected plan verbatim.

    Any material change (a fixed narrator, a moved exit, a new mechanism) clears
    this and is re-validated on its merits; only a byte-for-byte resend is a
    refusal to engage with the feedback.
    """
    if _plan_material_digest(candidate) in rejected_digests:
        return [
            "this is the identical plan that was just rejected, unchanged; apply the "
            "rejection feedback and alter the plan materially rather than resending it"
        ]
    return []


_PRONOUN_SWAP = {
    "he": "she", "him": "her", "his": "her",
    "she": "he", "her": "him", "hers": "his",
}


def _salvage_narrator_pronouns(plan: CompilationPlan) -> CompilationPlan:
    """Make escape_action agree with the narrator the plan already described.

    The planner keeps writing "He drives … I've hauled" into narrator_profile
    and then "She backs" into escape_action. plan_audit catches it and proposes
    the obvious fix — "change 'She' to 'He'" — but only after a paid audit call
    has been spent and one of two attempts is gone.

    Nothing creative is at stake: the narrator's gender is settled by
    narrator_profile and voice_seed, and escape_action is that same person
    acting. Rewriting the pronoun is the fix the auditor would have asked for.

    Applied ONLY when escape_action is unambiguously one gender, so a sentence
    that also names the threat ("She reverses while he walks toward the cab")
    is left for a human or the auditor to read. Same precision rule as
    narrator_pronoun_conflicts, which stays as the backstop for what this
    cannot safely touch.
    """
    def _one(text: str) -> str | None:
        low = f" {(text or '').lower()} "
        male = re.search(r"\b(he|him|his)\b", low) is not None
        female = re.search(r"\b(she|her|hers)\b", low) is not None
        if male and not female:
            return "male"
        if female and not male:
            return "female"
        return None

    changed = False
    stories = []
    for item in plan.stories:
        who = _one(f"{item.narrator_profile} {item.voice_seed}")
        act = _one(item.escape_action)
        # ENGLISH HAS TWO PRONOUNS THAT DO NOT MAP ONE-TO-ONE. "her" is both an
        # object ("follows her") and a possessive ("her hands"), so it becomes
        # "him" or "his" depending on grammar this cannot see; "his" has the
        # mirror problem. A first pass turned "Her hands shake" into "Him hands
        # shake". Deciding by heuristic would just move the error somewhere
        # less visible, so a text containing either form is left for the
        # auditor — narrator_pronoun_conflicts still reports it, and a reported
        # slip costs one audit call, while a corrupted one ships.
        ambiguous = re.search(r"\bher\b", item.escape_action, re.I) if who == "male" \
            else re.search(r"\bhis\b", item.escape_action, re.I)
        if who and act and who != act and not ambiguous:
            fixed = re.sub(
                r"\b(he|him|his|she|her|hers)\b",
                lambda m: _match_case(m.group(0), _PRONOUN_SWAP[m.group(0).lower()]),
                item.escape_action, flags=re.I)
            stories.append(item.model_copy(update={"escape_action": fixed}))
            changed = True
            logger.info("narrator pronoun realigned in escape_action",
                        story_id=item.story_id, narrator=who)
            continue
        stories.append(item)
    return plan.model_copy(update={"stories": stories}) if changed else plan


def _match_case(original: str, replacement: str) -> str:
    """Keep 'She' capitalised as 'He', not 'he', when a sentence starts on it."""
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement.capitalize()
    return replacement


def _salvage_voice_seeds(plan: CompilationPlan) -> CompilationPlan:
    """Blank any voice_seed that would poison the narration gates.

    A seed with an exact number / banned phrase / evidence framing used to
    hard-reject the whole plan; live 2026-07-18 that killed a run in plan stage
    after the planner's full-plan retry introduced a fresh violation elsewhere
    (whack-a-mole). The seed is optional by design — dropping a poisoned seed
    costs one story its voice sample (it falls back to voice_rules) and saves
    the other fourteen locked fields of a plan the auditor already liked."""
    changed = False
    stories = []
    for item in plan.stories:
        seed = (item.voice_seed or "").strip()
        poisoned = bool(seed) and (
            _BANNED_RE.search(seed) is not None
            or _CTA_RE.search(seed) is not None
            or bool(_numeric_anchors(seed))
            or any(p.search(seed) for p in _EVIDENCE_PATTERNS.values())
        )
        if poisoned:
            stories.append(item.model_copy(update={"voice_seed": ""}))
            changed = True
        else:
            stories.append(item)
    return plan.model_copy(update={"stories": stories}) if changed else plan


def _failed_attempt_brief(result: NarrativePipelineResult) -> str:
    """Tell the next planner attempt exactly what failed and what not to reuse."""
    threats = "; ".join(item.threat for item in result.plan.stories)
    mechanisms = "; ".join(
        f"{item.story_id}={'/'.join(story_mechanism_signature(item))}"
        for item in result.plan.stories
    )
    reasons = [failure.message for failure in result.gate_report.failures[:3]]
    reasons += [
        issue.problem[:160] for issue in result.scorecard.story_issues
        if issue.severity in {"critical", "major"}
    ][:3]
    return (
        "FAILED PREVIOUS ATTEMPT — plan a DIFFERENT concept; do not reuse these "
        f"premises or threats: {threats}. Spent mechanisms: {mechanisms}. "
        "Why it failed: "
        + (" | ".join(reasons) if reasons else "did not reach content lock")
    )


class NarrativeUnitPipeline:
    """Coordinate one bounded plan/write/audit/repair/annotation run."""

    def __init__(
        self,
        planner_llm,
        writer_llm,
        critic_llm,
        annotation_llm,
        quality_strategy: NamedChannelStrategy | None = None,
        compliance_llm=None,
        compliance_escalation_llm=None,
        plan_audit_llm=None,
        plan_audit_escalation_llm=None,
        release_challenger_llm=None,
        critic_fallback_llm=None,
        annotation_fallback_llm=None,
        plan_repair_llm=None,
        patch_llm=None,
        judge_mode: str = "default",
        model_roles: dict[str, str] | None = None,
    ) -> None:
        self.planner_llm = planner_llm
        self.writer_llm = writer_llm
        # Cost routing on the GENERATOR side only: every plan repair is re-run
        # through preflight + the semantic plan audit, and every surgical patch
        # through the trial gate + blind selector + monotonic re-score — the
        # CHECKERS hold the quality floor, so these two producers may run on a
        # cheaper model without lowering it. Defaults preserve old behaviour.
        self.plan_repair_llm = plan_repair_llm or planner_llm
        self.patch_llm = patch_llm or writer_llm
        self.critic_llm = critic_llm
        self.annotation_llm = annotation_llm
        # Compliance is mandatory. Production supplies Flash explicitly; direct
        # callers default to their critic rather than silently bypassing the gate.
        self.compliance_llm = compliance_llm or critic_llm
        self.compliance_escalation_llm = compliance_escalation_llm
        # Escalation only means something if it reaches somewhere else. Both of
        # these are checked for identity against the client they escalate from,
        # because a "second opinion" from the same client on the same balance is
        # one opinion billed twice.
        # Same provider/model as the critic in practice; a separate client only so
        # the stage is honestly labelled in provider logs. Falls back to the critic
        # so every existing caller keeps working unchanged.
        self.plan_audit_llm = plan_audit_llm or critic_llm
        self.plan_audit_escalation_llm = plan_audit_escalation_llm
        self.release_challenger_llm = release_challenger_llm
        # An independent scorer/final-editor path. Without one, a dead critic
        # account aborts the run before the writer rather than after it.
        self.critic_fallback_llm = critic_fallback_llm
        # Annotation is not a release judge (a lock does not depend on it), so it
        # never gates the writer — but without a live path a locked compilation
        # stalls at editorially_ready and never becomes a video.
        self.annotation_fallback_llm = annotation_fallback_llm
        # Descriptive only — the caller's account of how it wired this run, so an
        # artifact says which models judged it instead of leaving it to be
        # inferred from timestamps. Never used to make a gate decision: those
        # read resolved client identity, which cannot be misdescribed.
        self.judge_mode = judge_mode
        self.model_roles = dict(model_roles or {})
        self._unhealthy_domains: set[tuple] = set()
        self._run_notional_cost_usd: float = 0.0
        # Who ACTUALLY judged this run, primary or fallback. The challenger is
        # measured against these, not against the wiring's intentions.
        self._judge_identities_used: set[tuple] = set()
        self._run_call_counts: dict[str, int] = {}
        self._run_cost_usd: float = 0.0
        self._last_compliance_errors: dict[str, list[str]] = {}
        self.quality_strategy = quality_strategy or NamedChannelStrategy(
            strategy_id="system_default",
            writer_rules=(
                "Use distinct ordinary first-person voices, coherent physical action, "
                "restrained uncertainty, and different ending mechanisms."
            ),
            critic_rules=(
                "Demand exact continuity, authentic voice separation, earned dread, and "
                "disciplined endings without proof cosplay."
            ),
            annotation_rules="Do not alter or repeat voiceover text.",
        )

    async def run(
        self,
        brief: TopicBrief,
        *,
        channel_brand: dict | None = None,
        recent_avoid: str = "",
        annotate: bool = True,
        forbidden_plan_fingerprints: set[str] | None = None,
        forbidden_plans: list[CompilationPlan] | None = None,
        attempt_index: int = 1,
        inherit_health_context: bool = False,
    ) -> NarrativePipelineResult:
        strategy = self.quality_strategy
        self._run_call_counts = {
            "planner": 0,
            "planner_schema_retry": 0,
            "plan_repair": 0,
            "plan_repair_schema_retry": 0,
            "story_writer": 0,
            "story_writer_recovery": 0,
            "story_compliance": 0,
            "story_compliance_escalation": 0,
            "critic_score": 0,
            "critic_score_escalation": 0,
            "repair_writer": 0,
            "repair_rewrite": 0,
            "repair_salvage": 0,
            "plan_audit": 0,
            "plan_audit_escalation": 0,
            "plan_audit_contract_retry": 0,
            "blind_selector": 0,
            "final_editor": 0,
            "final_editor_escalation": 0,
            "release_challenger": 0,
            "annotation": 0,
            "annotation_escalation": 0,
        }
        self._run_cost_usd = 0.0
        self._run_notional_cost_usd = 0.0
        if not inherit_health_context:
            # Provider health outlives one attempt: a 402 does not heal because
            # we started a fresh concept. run_with_retry owns the context and
            # passes inherit=True, so attempt 2 does not re-discover a dead
            # account at the price of another bounded round of primary calls.
            self._begin_health_context()
        # Judge identities ARE per compilation: they answer 'who approved THIS
        # release', which the next attempt must decide afresh.
        self._judge_identities_used = set()
        self._last_compliance_errors = {}
        # Refuse before the expensive call, not after it.
        self._preflight_quality_path(strategy)
        # A COUNT IN THE TITLE IS A PROMISE TO THE VIEWER; anything else is the
        # material's decision. "3 True Encounters" must contain three. A title
        # that names no number used to be silently forced to three anyway,
        # which is structure standing in for judgement: a premise deep enough
        # to carry a whole video was cut into thirds, and a thin one was padded
        # out to fill a slot it did not deserve.
        #
        # The corpus gives no cover for the old default either. Raw numbers say
        # compilations beat single stories 4.7x, but that is channel size:
        # @mrnightmare is huge and makes almost only compilations, @DarkSomnium
        # makes only singles. In @Unit522 — the one channel doing both in
        # volume — singles are AHEAD (35.8k vs 22.6k median). Story count is a
        # channel's identity, not a performance rule.
        match = re.match(r"^\s*(\d+)\b", brief.title)
        # An explicit operator override wins over both. Every trope verdict is
        # per STORY, and at roughly one-in-two per story a three-story plan has
        # to win the same bet three times — sixteen runs produced no clean
        # plan. One long account needs one fresh premise. The corpus supports
        # it: in @Unit522, the one channel doing both formats in volume, single
        # stories out-perform compilations.
        _count_override = os.environ.get(
            "OMNICAST_NARRATIVE_STORY_COUNT", "").strip()
        story_count = (
            max(1, min(5, int(_count_override))) if _count_override.isdigit()
            else max(1, min(5, int(match.group(1)))) if match
            else _story_count_for(brief))
        target_words = spoken_word_floor(brief.target_duration_min)
        # ONE STORY IS NOT A COMPILATION MINUS TWO. With story_count forced to
        # 1 the whole 30-minute budget (4,500 words, ±10% enforced on the
        # writer) landed on a single premise, so a seven-rung ladder had to be
        # padded to 4,050+ words. Competitor single-story videos run long, but
        # they run long because the account has that much in it. Give one
        # story the room of the genre's longest compilation stories (~2,500,
        # the 2.1M-view "Deep Woods" entry) and let the band breathe.
        # The number from the brief's duration is a STARTING ESTIMATE handed to
        # the planner; the planner returns its own, and that one is kept (see
        # the model_copy below). Operator rule: never force a word count.

        forbidden = set(forbidden_plan_fingerprints or ())
        spent_concepts = list(forbidden_plans or [])
        forbidden.update(plan_concept_fingerprint(item) for item in spent_concepts)
        plan: CompilationPlan | None = None
        plan_audit: PlanAuditResult | None = None
        plan_errors: list[str] = []
        rejected_plans: list[CompilationPlan] = []
        rejection_reasons: list[list[str]] = []
        rejections: list[PlanRejection] = []
        rejected_digests: set[str] = set()

        def _reject(
            stage: str,
            errors: list[str],
            *,
            planner_attempt: int,
            started: float,
            candidate: CompilationPlan | None = None,
            audit: PlanAuditResult | None = None,
            raw_evidence: str = "",
        ) -> None:
            """Record one rejected plan WITH the reasons that plan died of.

            The 13:34 audit kept five plans and one trailing blocker list; four
            could not be matched to anything and the schema failure left no trace.
            """
            rejections.append(PlanRejection(
                attempt=attempt_index,
                planner_attempt=planner_attempt,
                stage=stage,
                errors=list(errors),
                plan=candidate,
                plan_fingerprint=(
                    plan_concept_fingerprint(candidate) if candidate else ""
                ),
                material_digest=(
                    _plan_material_digest(candidate) if candidate else ""
                ),
                audit=audit,
                call_counts=dict(self._run_call_counts),
                cost_usd=round(self._run_cost_usd, 6),
                latency_s=round(time.monotonic() - started, 3),
                raw_evidence=_redact(raw_evidence),
            ))
            if candidate is not None:
                rejected_plans.append(candidate)
                rejection_reasons.append(list(errors))
                rejected_digests.add(_plan_material_digest(candidate))

        # AN APPROVED PLAN IS THE PLANNER'S FIRST CANDIDATE. The operator reads
        # plans from plan_only.py and approves one; a full run used to re-plan
        # from the topic and write a different story. The loaded plan takes
        # attempt 1 and gets exactly the preflight, audit and repair a planned
        # candidate gets (run 14: all three loaded plans were blocked on prop
        # staging a single repair call fixes, and a bypass path aborted instead).
        approved_path = os.environ.get("OMNICAST_NARRATIVE_PLAN_FILE", "").strip()
        approved_plan = None
        approved_audit = None
        if approved_path:
            approved_index = int(os.environ.get("OMNICAST_NARRATIVE_PLAN_INDEX", "0") or 0)
            approved_plan = load_approved_plan(approved_path, approved_index)
            approved_audit = (
                None if os.environ.get("OMNICAST_NARRATIVE_PLAN_FILE_REAUDIT", "").strip().lower()
                in {"1", "true", "yes", "on"}
                else load_approved_audit(approved_path, approved_index))
            logger.info("narrative.approved_plan_loaded", path=approved_path,
                        index=approved_index, topic=approved_plan.topic)

        for planner_attempt in range(1, strategy.max_plan_attempts + 1):
            attempt_started = time.monotonic()
            retry = (
                "\nPREVIOUS PLAN WAS REJECTED BEFORE DRAFTING:\n- "
                + "\n- ".join(plan_errors)
                if plan_errors else ""
            )
            base_prompt = _plan_prompt(
                brief, story_count, target_words, channel_brand, recent_avoid,
                strategy, forbidden,
            )
            candidate_plan = None
            schema_error = ""
            # A schema slip is not a bad concept. The live planner omitted one
            # story's voice_rules and burned a whole concept for it; one
            # contract-only retry naming the exact missing field is cheaper than a
            # replan and does not invent creative content to paper over it.
            # Live 2026-07-20 06:38 (and 2026-07-19 21:19, 2026-07-20 03:50): the
            # retry only listed REQUIRED FIELDS, so a continuity_ledger entry over
            # 24 words was answered with "return the SAME plan" — the planner
            # resent the identical over-long entry and burned both tries
            # (planner=4/planner_schema_retry=4, zero writer calls). Length and
            # format violations need naming too; plan_repair already learned this.
            use_approved = approved_plan is not None and planner_attempt == 1
            if use_approved:
                candidate_plan = approved_plan
            for schema_try in (() if use_approved else range(2)):
                if schema_try:
                    self._record_call("planner_schema_retry")
                else:
                    self._record_call("planner")
                contract = (
                    "\n\nCONTRACT RETRY. Your previous plan was rejected by schema "
                    "validation before it was read:\n"
                    + _redact(schema_error, 600)
                    + "\nReturn the SAME plan with every required field present on every "
                    "story. Do not redesign the concept; fix only what the validator "
                    "named. Every story needs all of: story_id, title, narrator_profile, "
                    "setting, setup_requirement, threat, threat_type, escape_action, "
                    "ending_shape, evidence_allowance, voice_rules, voice_seed, "
                    "threat_mechanism, progression_mechanism, escape_mechanism, "
                    "aftermath_mechanism, threat_identity, topic_promise, "
                    "distinguishing_turn, "
                    "narrator_age_band, narrator_age_years, safety_obligation, "
                    "safety_omission_reason, continuity_ledger."
                    "\nIf the validator named a LENGTH or FORMAT violation rather than a "
                    "missing field, the fields are already all present — re-sending the "
                    "same wording will fail again. Fix exactly what it named: a "
                    "continuity_ledger entry over 24 words must be shortened to 24 words "
                    "or fewer (including its prefix) without dropping the fact it "
                    "carries; each entry must keep its exact required prefix, stay "
                    "unique, and keep at least three fact words after the prefix. Cut "
                    "adjectives, not facts."
                    if schema_error else ""
                )
                try:
                    response, plan_obj = await self.planner_llm.complete_structured(
                        system=(
                            "You are a continuity-focused commissioning editor for "
                            "restrained first-person horror recollection. Return "
                            "valid JSON only."
                        ),
                        messages=[{
                            "role": "user",
                            "content": base_prompt + retry + contract,
                        }],
                        output_schema=CompilationPlan,
                        max_tokens=3200,
                        temperature=0.3,
                    )
                    self._record_cost(response)
                    _parsed = CompilationPlan.model_validate(plan_obj)
                    # THE PLANNER'S ESTIMATE IS KEPT. This used to overwrite it with
                    # the brief's duration arithmetic, which the writer then had to
                    # hit inside a band. Length is the account's; the planner, who
                    # knows the ladder, estimates it; only a sanity clamp applies.
                    _est = int(getattr(_parsed, "target_word_count", 0) or 0)
                    _kept = min(6000, max(GENRE_FLOOR_TOTAL_WORDS, _est)) if _est else target_words
                    candidate_plan = _parsed.model_copy(
                        update={"topic": brief.title, "target_word_count": _kept}
                    )
                    target_words = _kept
                    candidate_plan = _salvage_cold_open(candidate_plan)
                    candidate_plan = _salvage_voice_seeds(candidate_plan)
                    candidate_plan = _salvage_narrator_pronouns(candidate_plan)
                    # A one-story plan cannot carry evidence (one story must
                    # stay uncorroborated). Forcing the enum to "none" keeps
                    # every other locked field; rejecting the plan threw away a
                    # six-rung premise for a one-word field (live 2026-08-22).
                    if story_count == 1 and candidate_plan.stories and \
                            candidate_plan.stories[0].evidence_allowance != "none":
                        candidate_plan = candidate_plan.model_copy(update={"stories": [
                            candidate_plan.stories[0].model_copy(
                                update={"evidence_allowance": "none"})]})
                        logger.info("evidence_allowance forced to none for a one-story plan")
                    break
                except Exception as exc:
                    schema_error = f"schema or provider error: {_redact(exc, 600)}"
                    candidate_plan = None
                    # SAY WHY, EVERY TIME. When the retry succeeds this error is
                    # overwritten and nothing survives, so the call counters have
                    # read planner=4 / planner_schema_retry=4 for weeks — every
                    # first attempt failing, planner quota spent twice per plan —
                    # with no record of what the validator objected to. A failure
                    # that leaves no trace cannot be fixed, and quota is now the
                    # binding constraint on this channel.
                    logger.warning(
                        "planner plan rejected before it was read",
                        attempt=schema_try, story_count=story_count,
                        error=_redact(exc, 400))
            if candidate_plan is None:
                plan_errors = [schema_error]
                _reject(
                    "schema", plan_errors, planner_attempt=planner_attempt,
                    started=attempt_started, raw_evidence=schema_error,
                )
                continue

            preflight = validate_plan_preflight(candidate_plan, story_count, strategy)
            freshness = (
                _plan_freshness_errors(candidate_plan, forbidden, spent_concepts)
                + _plan_repeat_errors(candidate_plan, rejected_digests)
            )
            plan_errors = preflight + freshness
            if plan_errors:
                _reject(
                    "preflight" if preflight else "freshness",
                    plan_errors, planner_attempt=planner_attempt,
                    started=attempt_started, candidate=candidate_plan,
                )
                # A LOADED PLAN THAT FAILS A GATE IS REPAIRED, NOT REPLANNED. The
                # gates tighten between the save and the write (Codex's review of
                # the run-15 plan became a coincidence pattern the plan now trips);
                # a replan would throw the approved premise away over one escape
                # sentence. The gate errors are handed to the repair call as
                # blockers; the repaired plan re-runs every gate and the real audit.
                if use_approved and preflight and not freshness:
                    gate_audit = PlanAuditResult(
                        status="blocked", blockers=list(preflight),
                        issues=_gate_errors_as_issues(preflight),
                        summary="loaded plan failed a deterministic gate",
                        verdict_source="none")
                    repaired, repaired_audit = await self._repair_plan(
                        candidate_plan, gate_audit, story_count, strategy,
                        forbidden, spent_concepts, rejected_digests,
                        attempt_index=attempt_index, planner_attempt=planner_attempt,
                        reject=_reject,
                    )
                    if repaired is not None and repaired_audit is not None:
                        plan, plan_audit = repaired, repaired_audit
                        break
                continue

            # Semantic plausibility audit BEFORE any paid drafting: a bad premise
            # cannot be fixed by good prose. Blocking objections are fed back to
            # the planner; unlike the previous rule, the final attempt does NOT
            # proceed on a plan the auditor blocked. An over-zealous auditor now
            # costs a replan and, at worst, an aborted attempt the outer loop can
            # retry with a fresh concept — a premise an informed viewer rejects
            # costs a whole shot video.
            # AN APPROVED PLAN IS WRITTEN AS APPROVED. Live 22:03: a plan that
            # plan_only had audited valid was re-audited at write time by a
            # non-deterministic judge, repaired into a new escape, and the
            # writer was scored against the mutated plan (two majors, 83/100).
            # The saved valid audit is trusted; preflight already ran above.
            if use_approved and approved_audit is not None:
                plan_audit = approved_audit.model_copy(update={
                    "summary": (approved_audit.summary or "") + " (saved audit, trusted at write time)"})
            else:
                plan_audit = await self._audit_plan(candidate_plan, strategy)
            if plan_audit.status in {"infra_failed", "contract_failed"}:
                _reject(
                    "audit",
                    plan_audit.provider_errors + plan_audit.contract_errors,
                    planner_attempt=planner_attempt, started=attempt_started,
                    candidate=candidate_plan, audit=plan_audit,
                )
                raise PlanAuditUnavailable(
                    "The plan plausibility auditor never returned a usable verdict ("
                    + "; ".join(
                        plan_audit.provider_errors + plan_audit.contract_errors
                    )[:400]
                    + "). An unanswered or ungroundable audit is not a clean audit; "
                    "refusing to draft stories against an unaudited premise.",
                    plan_audit,
                )
            if plan_audit.status == "blocked":
                # Recorded before the health gate below, so an abort still carries
                # the premise that was rejected and why.
                _reject(
                    "audit", list(plan_audit.blockers),
                    planner_attempt=planner_attempt, started=attempt_started,
                    candidate=candidate_plan, audit=plan_audit,
                )
            # The audit answered, so provider health is now KNOWN — act on it here,
            # before repairing, replanning or writing. Live 2026-07-17 14:02 was
            # stopped by hand after ~9.5 minutes and 11 Opus calls with zero writer
            # calls: the gate lived after the planner loop, so a plan that kept
            # getting blocked kept being repaired and re-planned against a provider
            # the very first audit had already proved dead.
            self._assert_post_writer_path_healthy(
                plan_audit, rejections=rejections, plan=candidate_plan
            )
            if plan_audit.status == "blocked":
                # A local defect deserves a local fix. Six full planner calls and
                # fifteen audits burned 9.6 minutes on 2026-07-17 without writing a
                # word, largely re-rolling whole compilations because one story's
                # cart geometry was wrong. Targeted repair keeps the clean stories
                # byte-identical and re-runs every gate; it cannot skip freshness or
                # mechanism diversity, and a premise-wide objection still abandons
                # the concept.
                repaired, repaired_audit = await self._repair_plan(
                    candidate_plan, plan_audit, story_count, strategy,
                    forbidden, spent_concepts, rejected_digests,
                    attempt_index=attempt_index, planner_attempt=planner_attempt,
                    reject=_reject,
                )
                if repaired is not None and repaired_audit is not None:
                    plan, plan_audit = repaired, repaired_audit
                    break
                plan_errors = list(plan_audit.blockers)
                continue
            plan = candidate_plan
            break

        if plan is None:
            # A premise that was judged and rejected is a different outcome from a
            # planner that never produced one: only the first says anything about
            # the concept. Both carry their rejection history.
            judged = [item for item in rejections if item.stage != "schema"]
            if judged:
                raise PlanNotPlausible(
                    f"No plausible, fresh plan after {strategy.max_plan_attempts} "
                    "attempts: " + "; ".join(plan_errors)[:600],
                    plan_audit if plan_audit is not None and plan_audit.status == "blocked"
                    else PlanAuditResult(
                        status="blocked",
                        blockers=plan_errors or ["plan rejected before the audit ran"],
                    ),
                    rejected_plans,
                    rejection_reasons,
                    rejections,
                )
            raise PlannerUnavailable(
                f"Planner failed {strategy.max_plan_attempts} times without returning a "
                "parseable plan: " + "; ".join(plan_errors)[:600],
                rejections,
            )
        assert plan_audit is not None
        # The audit answered — but it is also this run's only pre-writer evidence
        # about whether the judges of the prose are alive. Escalation may have
        # supplied the verdict; it cannot supply their health.
        self._assert_post_writer_path_healthy(plan_audit)

        # PLAN-ONLY DIAGNOSTIC MODE. Nine live runs reached this line without a
        # releasable compilation, and the last four died on the QUALITY of the
        # premise rather than on any plumbing. Judging that costs one planner
        # call and one audit; judging it by running the whole pipeline costs
        # twenty-five minutes and most of a quota window, which is why only
        # nine premises have been seen at all.
        #
        # Reads an env var rather than a parameter so the production call path
        # is byte-identical when it is unset, and raises rather than returning
        # a half-built result so nothing downstream can mistake this for a run.
        if os.environ.get("OMNICAST_NARRATIVE_PLAN_ONLY", "").strip().lower() in {
                "1", "true", "yes", "on"}:
            raise PlanOnlyComplete(plan, plan_audit)

        per_story = round(target_words / story_count)

        async def write_one(item: NarrativeStoryPlan) -> StoryDraft:
            self._record_call("story_writer")
            response = await self.writer_llm.complete(
                system=(
                    "You write restrained, plausible first-person horror recollections and "
                    "obey the locked plan."
                ),
                messages=[{"role": "user", "content": _story_prompt(
                    item, per_story, (
                        plan.cold_open if item.story_id == "story_1"
                        else "Not assigned to this story. Do not quote the compilation cold open."
                    ), strategy, topic=plan.topic,
                )}],
                max_tokens=_writer_max_tokens(getattr(item, 'target_words', 0) or per_story),
                temperature=0.75,
            )
            self._record_cost(response)
            output = _parse_story_output(response.content, item)
            return StoryDraft(story_id=item.story_id, **output.model_dump())

        # A DRAFT ON DISK IS JUDGED, NOT REWRITTEN. Eight live builds of one
        # approved plan produced eight rewrites at 83-89, each felled by a
        # different judge's coin flip. With a draft file set, the writer call
        # is skipped for story_1 and every judge still runs.
        _draft_path = os.environ.get("OMNICAST_NARRATIVE_DRAFT_FILE", "").strip()
        if _draft_path and len(plan.stories) == 1:
            _loaded = load_draft_file(_draft_path, plan.stories[0])
            logger.info("narrative.draft_loaded", path=_draft_path,
                        words=len(_words(_loaded.narration)))
            stories = [_loaded]
        else:
            stories = list(await asyncio.gather(*(write_one(item) for item in plan.stories)))
        gate = gate_compilation(plan, stories, strategy)
        # Local deterministic recovery runs before any semantic audit so bad-length
        # or banned-phrase prose is not needlessly audited. Clean first drafts are
        # never rewritten and no recovery call happens on the happy path.
        recovery_ids = _story_recovery_ids(plan, gate)
        if recovery_ids:
            stories = await self._recover_stories(
                plan, stories, gate, recovery_ids, per_story, strategy
            )
            gate = gate_compilation(plan, stories, strategy)
        compliance_reviews, compliance_valid = await self._audit_stories(
            plan, stories, strategy
        )
        if not compliance_valid:
            stories, gate, compliance_reviews, compliance_valid = (
                await self._rescue_unauditable_stories(
                    plan, stories, gate, compliance_reviews, per_story, strategy
                )
            )
        if compliance_valid:
            score, critic_valid, _ = await self._score_validated(
                plan, stories, gate, strategy, compliance_reviews=compliance_reviews
            )
            score = self._with_compliance_issues(score, compliance_reviews)
        else:
            score = self._zero_score(
                "Per-story compliance failed its structured-output contract twice."
            )
            critic_valid = True

        repair_waves = 0
        patch_decisions: list[PatchDecision] = []
        expected_ids = {item.story_id for item in plan.stories}
        while critic_valid and compliance_valid and repair_waves < 3:
            failing_ids = {
                sid for failure in gate.failures for sid in failure.story_ids
                if sid in expected_ids
            }
            failing_ids.update(
                issue.story_id for issue in score.story_issues
                if issue.story_id in expected_ids
                and issue.severity in {"critical", "major"}
            )
            if not failing_ids:
                failing_ids = _near_miss_minor_ids(
                    score, gate, strategy, expected_ids, repair_waves
                )
            if not failing_ids:
                break
            # The second wave is a cheap salvage for an already strong, objectively
            # clean compilation. It cannot rescue a weak draft or start a debate loop.
            if repair_waves == 1 and (
                not gate.passed
                or score.total_score < strategy.approval_score
                or score.critical_issues
                or len(failing_ids) > 3
            ):
                break
            # The third wave is a FINISHING wave, gated harder still: only a
            # compilation already inside release range whose remaining blockers
            # are few and quoted may buy it. Live 2026-07-20 (courier 1726):
            # 84 total, originality 8, every floor passed, TWO quoted majors on
            # one story — the wave budget ran out and a release-range candidate
            # was discarded; regenerating from scratch costs roughly six times
            # what one more bounded wave does.
            if repair_waves == 2 and not _finishing_wave_allowed(
                score, gate, strategy, failing_ids
            ):
                break
            candidate_list, decisions = await self._repair_wave(
                plan, stories, score, gate, failing_ids, per_story, strategy
            )
            repair_waves += 1
            patch_decisions.extend(decisions)
            if not self._stories_changed(stories, candidate_list):
                break
            candidate_gate = gate_compilation(plan, candidate_list, strategy)
            changed_ids = {
                before.story_id for before, after in zip(stories, candidate_list, strict=True)
                if before.narration != after.narration
            }
            candidate_reviews, candidate_compliance_valid = await self._audit_stories(
                plan, candidate_list, strategy,
                only_ids=changed_ids, prior=compliance_reviews,
            )
            if not candidate_compliance_valid:
                break
            candidate_score, candidate_valid, _ = await self._score_validated(
                plan, candidate_list, candidate_gate, strategy,
                compliance_reviews=candidate_reviews,
            )
            candidate_score = self._with_compliance_issues(
                candidate_score, candidate_reviews
            )
            if not candidate_valid or not self._repair_is_monotonic(
                score, gate, candidate_score, candidate_gate, strategy
            ):
                # All-or-nothing acceptance let one bad patch drag a correct
                # one down with it (live: a geography fix the blind selector
                # explicitly praised was thrown away because a sibling patch
                # regressed). One bounded second chance: keep ONLY the patch
                # for the story carrying the heaviest blocker and re-judge.
                salvage = await self._salvage_single_patch(
                    plan, stories, candidate_list, changed_ids, score, gate,
                    strategy, compliance_reviews,
                )
                if salvage is None:
                    break
                stories, gate, score, compliance_reviews = salvage
                critic_valid = True
                compliance_valid = True
                continue
            stories, gate, score, critic_valid = (
                candidate_list, candidate_gate, candidate_score, candidate_valid
            )
            compliance_reviews = candidate_reviews
            compliance_valid = candidate_compliance_valid

        final_review: FinalCompilationReview | None = None
        final_approved = False
        score = await self._originality_tiebreak(plan, stories, gate, score, strategy)
        preliminary = content_can_lock(
            score, gate, strategy,
            critic_contract_valid=critic_valid,
            story_compliance_valid=(
                compliance_valid and self._compliance_set_approved(plan, compliance_reviews)
            ),
            final_editor_approved=True,
        )
        if preliminary:
            final_review, final_approved = await self._final_review(
                plan, stories, strategy
            )

        # A final editor may expose one grounded issue missed by the scorecard. It may
        # consume one of the two bounded repair waves, but never trigger an open loop.
        final_blockers = [
            item for item in (final_review.issues if final_review else [])
            if item.severity in {"critical", "major"}
        ]
        if preliminary and not final_approved and repair_waves < 2 and final_blockers:
            final_score = score.model_copy(update={"story_issues": final_blockers})
            final_ids = {item.story_id for item in final_blockers if item.story_id in expected_ids}
            candidate_list, decisions = await self._repair_wave(
                plan, stories, final_score, gate, final_ids, per_story, strategy
            )
            repair_waves += 1
            patch_decisions.extend(decisions)
            if self._stories_changed(stories, candidate_list):
                candidate_gate = gate_compilation(plan, candidate_list, strategy)
                changed_ids = {
                    before.story_id
                    for before, after in zip(stories, candidate_list, strict=True)
                    if before.narration != after.narration
                }
                candidate_reviews, candidate_compliance_valid = await self._audit_stories(
                    plan, candidate_list, strategy,
                    only_ids=changed_ids, prior=compliance_reviews,
                )
                if not candidate_compliance_valid:
                    candidate_reviews = compliance_reviews
                    candidate_valid = False
                    candidate_score = score
                else:
                    candidate_score, candidate_valid, _ = await self._score_validated(
                        plan, candidate_list, candidate_gate, strategy,
                        compliance_reviews=candidate_reviews,
                    )
                    candidate_score = self._with_compliance_issues(
                        candidate_score, candidate_reviews
                    )
                # The monotonic baseline must carry the final-editor blockers this
                # wave was commissioned to fix: resolving them is progress even when
                # the fresh critic returns an identical total score.
                if candidate_compliance_valid and candidate_valid and self._repair_is_monotonic(
                    final_score, gate, candidate_score, candidate_gate, strategy
                ):
                    stories, gate, score, critic_valid = (
                        candidate_list, candidate_gate, candidate_score, candidate_valid
                    )
                    compliance_reviews = candidate_reviews
                    compliance_valid = candidate_compliance_valid
                    final_review, final_approved = await self._final_review(
                        plan, stories, strategy
                    )

        # The adversarial challenger is the last gate and only sees would-be
        # releases. Its findings join the scorecard so the artifact records why a
        # compilation every other judge approved did not ship; a failed challenge
        # is not repaired here — the outer loop regenerates a fresh concept, which
        # is both bounded and the honest response to "your premise convinced two
        # judges and still does not survive contact with a skeptic".
        would_lock = content_can_lock(
            score, gate, strategy,
            critic_contract_valid=critic_valid,
            story_compliance_valid=(
                compliance_valid and self._compliance_set_approved(plan, compliance_reviews)
            ),
            final_editor_approved=final_approved,
        )
        challenge: ReleaseChallengeResult | None = (
            None if strategy.release_challenger_required
            else ReleaseChallengeResult(status="not_required")
        )
        if would_lock:
            challenge, challenge_passed, challenge_issues = await self._release_challenge(
                plan, stories, strategy
            )
            # A LOCAL challenger fail earns one repair and one re-challenge.
            # Live 23:26: 87/100, every judge approved, and the skeptic found
            # she walked out the front door still holding a corded wall-phone
            # receiver - a one-sentence physical slip that abandoned a 20-minute
            # build. Premise-level axes (topic, plan fidelity, ending, safety)
            # still abandon: those are the concept, not the sentence.
            _local_axes = {"physical_possibility", "timeline_consistency", "semantic_repetition", "self_reassurance"}
            _local_fail = (
                challenge is not None and challenge.status == "failed" and challenge_issues
                and all(
                    any(f"/{axis}]" in (i.problem or "") for axis in _local_axes)
                    and i.story_id in expected_ids and (i.evidence_quote or "").strip()
                    for i in challenge_issues)
            )
            if _local_fail and repair_waves < 3:
                challenge_score = score.model_copy(update={"story_issues": list(challenge_issues)})
                challenge_ids = {i.story_id for i in challenge_issues}
                candidate_list, decisions = await self._repair_wave(
                    plan, stories, challenge_score, gate, challenge_ids, per_story, strategy
                )
                repair_waves += 1
                patch_decisions.extend(decisions)
                if self._stories_changed(stories, candidate_list):
                    candidate_gate = gate_compilation(plan, candidate_list, strategy)
                    changed_ids = {
                        b.story_id for b, a in zip(stories, candidate_list, strict=True)
                        if b.narration != a.narration
                    }
                    candidate_reviews, candidate_compliance_valid = await self._audit_stories(
                        plan, candidate_list, strategy, only_ids=changed_ids, prior=compliance_reviews,
                    )
                    if candidate_compliance_valid:
                        candidate_score, candidate_valid, _ = await self._score_validated(
                            plan, candidate_list, candidate_gate, strategy,
                            compliance_reviews=candidate_reviews,
                        )
                        candidate_score = self._with_compliance_issues(candidate_score, candidate_reviews)
                        if candidate_valid and self._repair_is_monotonic(
                                challenge_score, gate, candidate_score, candidate_gate, strategy):
                            c_final_review, c_final_approved = await self._final_review(
                                plan, candidate_list, strategy)
                            if c_final_approved and content_can_lock(
                                    candidate_score, candidate_gate, strategy,
                                    critic_contract_valid=candidate_valid,
                                    story_compliance_valid=self._compliance_set_approved(plan, candidate_reviews),
                                    final_editor_approved=c_final_approved):
                                stories, gate, score, critic_valid = (
                                    candidate_list, candidate_gate, candidate_score, candidate_valid)
                                compliance_reviews, compliance_valid = candidate_reviews, candidate_compliance_valid
                                final_review, final_approved = c_final_review, c_final_approved
                                challenge, challenge_passed, challenge_issues = await self._release_challenge(
                                    plan, stories, strategy)
            if challenge_issues:
                score = score.model_copy(update={
                    "story_issues": [*score.story_issues, *challenge_issues],
                })

        locked = content_can_lock(
            score, gate, strategy,
            critic_contract_valid=critic_valid,
            story_compliance_valid=(
                compliance_valid and self._compliance_set_approved(plan, compliance_reviews)
            ),
            final_editor_approved=final_approved,
            plan_audit_valid=plan_audit.status == "valid",
            release_challenge_passed=(
                challenge is not None and challenge.status in {"passed", "not_required"}
            ),
        )
        annotations: list[StoryAnnotation] = []
        production_ready = False
        draft: ScriptDraft | None = None
        if locked and annotate and self.annotation_llm is not None:
            async def annotate_one(story: StoryDraft) -> StoryAnnotation:
                beats = _split_beats(story)
                annotator = self._route(
                    self.annotation_llm, self.annotation_fallback_llm
                )
                self._record_call(
                    "annotation" if annotator is self.annotation_llm
                    else "annotation_escalation"
                )
                response, annotation_obj = await annotator.complete_structured(
                    system=(
                        "You are a production annotator. Narration is immutable. Return valid "
                        "JSON metadata only, keyed by the supplied beat IDs."
                    ),
                    messages=[{
                        "role": "user",
                        "content": _annotation_prompt(story, beats, strategy),
                    }],
                    output_schema=StoryAnnotation,
                    max_tokens=3200,
                    temperature=0.25,
                )
                self._record_cost(response)
                return StoryAnnotation.model_validate(annotation_obj)

            annotation_results = await asyncio.gather(
                *(annotate_one(story) for story in stories), return_exceptions=True
            )
            annotations = [
                item for item in annotation_results if isinstance(item, StoryAnnotation)
            ]
            coverage = len(annotations) == len(stories) and all(
                annotation.story_id == story.story_id
                and _annotation_covers(annotation, _split_beats(story))
                for story, annotation in zip(stories, annotations, strict=True)
            )
            if coverage:
                draft = _assemble(plan, stories, annotations)
                production_ready = True

        compliance_approved = (
            compliance_valid and self._compliance_set_approved(plan, compliance_reviews)
        )
        objective_valid = (
            gate.passed and critic_valid and compliance_approved
            and not score.critical_issues
            and not any(
                item.severity in {"critical", "major"} for item in score.story_issues
            )
        )
        release_tier = (
            "production_test_ready" if production_ready
            else "editorially_ready" if locked
            else "content_valid" if objective_valid
            else "needs_edit"
        )

        return NarrativePipelineResult(
            plan=plan,
            stories=stories,
            gate_report=gate,
            scorecard=score,
            plan_audit=plan_audit,
            judge_identities=sorted(self._judge_identities_used),
            judge_mode=self.judge_mode,
            model_roles=dict(self.model_roles),
            plan_audit_warnings=[
                _format_plan_issue(item) for item in plan_audit.issues
            ],
            release_challenge=challenge,
            attempt_summaries=[],
            aggregate_call_counts=dict(self._run_call_counts),
            aggregate_cost_usd=self._run_cost_usd,
            aggregate_notional_cost_usd=round(self._run_notional_cost_usd, 6),
            content_locked=locked,
            annotations=annotations,
            production_ready=production_ready,
            repair_waves=repair_waves,
            draft=draft,
            critic_contract_valid=critic_valid,
            story_compliance_valid=compliance_valid,
            story_compliance_reviews=list(compliance_reviews.values()),
            story_compliance_errors=dict(self._last_compliance_errors),
            final_editor_approved=final_approved,
            locked_voiceover_sha256=(locked_voiceover_sha256(stories) if locked else ""),
            patch_decisions=patch_decisions,
            final_review=final_review,
            release_tier=release_tier,
            quality_strategy=strategy,
            call_counts=dict(self._run_call_counts),
        )

    async def run_with_retry(
        self,
        brief: TopicBrief,
        *,
        channel_brand: dict | None = None,
        recent_avoid: str = "",
        annotate: bool = True,
        max_attempts: int = 2,
    ) -> NarrativePipelineResult:
        """Autonomous outer loop: a compilation that fails its content gates is
        regenerated with a FRESH plan that is told exactly why the previous
        concept failed — instead of parking at needs_edit for a human editor.

        Content lock is the stop condition: annotation-only shortfalls are not
        a reason to throw away locked prose. Bounded by max_attempts; when every
        attempt fails, the best one (production_ready, content_locked, score,
        fewest hard failures) is returned so the caller still gets the strongest
        needs_edit candidate on the audit trail.
        """
        best: NarrativePipelineResult | None = None
        avoid = recent_avoid
        last_error: Exception | None = None
        # One health context for the whole retry loop.
        self._begin_health_context()
        summaries: list[AttemptSummary] = []
        spent_concepts: list[CompilationPlan] = []
        rejected_plans: list[CompilationPlan] = []
        rejections: list[PlanRejection] = []
        aggregate_calls: dict[str, int] = {}
        aggregate_cost = 0.0
        aggregate_notional = 0.0
        aggregate_latency = 0.0

        def _absorb(summary: AttemptSummary) -> None:
            nonlocal aggregate_cost, aggregate_notional, aggregate_latency
            summaries.append(summary)
            for stage, count in summary.call_counts.items():
                aggregate_calls[stage] = aggregate_calls.get(stage, 0) + count
            aggregate_cost += summary.cost_usd
            aggregate_notional += summary.notional_cost_usd
            aggregate_latency += summary.latency_s

        for attempt in range(1, max(1, max_attempts) + 1):
            started = time.monotonic()
            try:
                result = (await self.run(
                    brief, channel_brand=channel_brand,
                    recent_avoid=avoid, annotate=annotate,
                    forbidden_plans=spent_concepts, attempt_index=attempt,
                    inherit_health_context=True,
                )).model_copy(update={"attempt": attempt})
            except PlanOnlyComplete:
                # Not an abort: the plan passed and the caller asked to stop
                # here. Run 11 (2026-08-22) had BOTH plans accepted — the first
                # in twenty-one runs — and this handler filed them as "aborted",
                # retried, and the driver printed REJECTED; neither plan was
                # saved. The whole point of plan-only is the plan; let it out.
                raise
            except Exception as exc:
                # An aborted attempt (planner preflight, provider outage) must not
                # kill the loop — the next attempt is a fresh roll. What it must
                # not do either is vanish from the bill: the counters below are the
                # instance's own record of what this dead attempt already spent.
                last_error = exc
                outcome = (
                    "plan_blocked" if isinstance(exc, PlanNotPlausible)
                    else "plan_audit_unavailable" if isinstance(exc, PlanAuditUnavailable)
                    else "quality_path_unhealthy" if isinstance(exc, QualityPathUnhealthy)
                    else "quality_path_unavailable" if isinstance(exc, QualityPathUnavailable)
                    else "aborted"
                )
                attempt_rejections = list(getattr(exc, "rejections", []) or [])
                _absorb(AttemptSummary(
                    attempt=attempt,
                    outcome=outcome,
                    reason=str(exc)[:600],
                    call_counts=dict(self._run_call_counts),
                    cost_usd=self._run_cost_usd,
                    notional_cost_usd=round(self._run_notional_cost_usd, 6),
                    latency_s=round(time.monotonic() - started, 3),
                    blocking_issues=list(getattr(getattr(exc, "audit", None), "blockers", [])),
                    plan_rejections=attempt_rejections,
                    plan_audit=getattr(exc, "audit", None),
                ))
                rejections.extend(attempt_rejections)
                for rejected in getattr(exc, "rejected_plans", []) or []:
                    spent_concepts.append(rejected)
                    rejected_plans.append(rejected)
                if isinstance(exc, (QualityPathUnavailable, QualityPathUnhealthy)):
                    # Neither is bad luck a fresh concept can fix: one is a
                    # misconfiguration, the other a dead provider account. Retrying
                    # would re-plan and re-audit against the same dead path. Break
                    # rather than re-raise, so the run still leaves through the
                    # evidence-carrying exit — an unhealthy path aborts AFTER the
                    # planner and audit have already been paid for, and that bill is
                    # exactly what this run needs to report.
                    break
                avoid = (f"{avoid}\n" if avoid else "") + (
                    "FAILED PREVIOUS ATTEMPT — the run aborted before producing "
                    f"a compilation: {str(exc)[:300]}"
                )
                continue

            _absorb(AttemptSummary(
                attempt=attempt,
                outcome="content_locked" if result.content_locked else "needs_edit",
                reason=result.scorecard.editorial_summary[:300],
                call_counts=dict(result.call_counts),
                cost_usd=result.aggregate_cost_usd,
                notional_cost_usd=result.aggregate_notional_cost_usd,
                latency_s=round(time.monotonic() - started, 3),
                plan_fingerprint=plan_concept_fingerprint(result.plan),
                plan=result.plan,
                total_score=result.scorecard.total_score,
                gate_failures=[item.message for item in result.gate_report.failures],
                blocking_issues=[
                    f"[{item.severity}] {item.story_id}: {item.problem[:160]}"
                    for item in result.scorecard.story_issues
                    if item.severity in {"critical", "major"}
                ],
            ))
            spent_concepts.append(result.plan)
            if result.content_locked:
                return result.model_copy(update={
                    "attempts_executed": attempt,
                    "attempt_summaries": summaries,
                    "aggregate_call_counts": aggregate_calls,
                    "aggregate_cost_usd": round(aggregate_cost, 6),
                    "aggregate_notional_cost_usd": round(aggregate_notional, 6),
                    "aggregate_latency_s": round(aggregate_latency, 3),
                })
            if best is None or self._attempt_rank(result) > self._attempt_rank(best):
                best = result
            avoid = (f"{avoid}\n" if avoid else "") + _failed_attempt_brief(result)

        if best is None:
            # No candidate survived. This is the case that spends the most and
            # delivers the least, so it is the last place the bill should vanish:
            # the evidence travels on the exception instead of on a result that
            # does not exist. No score and no script are invented to carry it.
            evidence = NarrativeRunEvidence(
                attempts_executed=len(summaries),
                attempt_summaries=summaries,
                aggregate_call_counts=aggregate_calls,
                aggregate_cost_usd=round(aggregate_cost, 6),
                aggregate_notional_cost_usd=round(aggregate_notional, 6),
                aggregate_latency_s=round(aggregate_latency, 3),
            )
            reason = str(last_error)[:400] if last_error is not None else (
                "narrative retry loop produced no result"
            )
            raise NarrativeRunExhausted(
                f"All {len(summaries)} narrative attempt(s) failed without producing a "
                f"releasable compilation: {reason}",
                evidence,
                rejected_plans,
                rejections,
            ) from last_error
        # The winner keeps its own per-run call_counts; the aggregate carries every
        # attempt, so nothing reads as if the attempts before it were free.
        return best.model_copy(update={
            "attempts_executed": len(summaries),
            "attempt_summaries": summaries,
            "aggregate_call_counts": aggregate_calls,
            "aggregate_cost_usd": round(aggregate_cost, 6),
            "aggregate_notional_cost_usd": round(aggregate_notional, 6),
            "aggregate_latency_s": round(aggregate_latency, 3),
        })

    @staticmethod
    def _attempt_rank(result: NarrativePipelineResult) -> tuple:
        return (
            result.production_ready,
            result.content_locked,
            result.scorecard.total_score,
            -len(result.gate_report.failures),
        )

    async def _audit_plan(
        self, plan: CompilationPlan, strategy: NamedChannelStrategy,
        reaudit: str = "",
    ) -> PlanAuditResult:
        """Audit the locked plan before prose exists, and never guess the verdict.

        This used to swallow every exception and return [] — an empty blocker list
        that is indistinguishable from a clean plan. A provider outage, a 402, and
        a premise an ex-cop would laugh at all produced the same "proceed". The
        audit now retries the primary auditor, escalates to a genuinely different
        provider when one is configured, and reports infra_failed when neither
        answers.

        It is also the run's live probe of the critic path, and that is a SEPARATE
        output from the verdict. Escalation may rescue the verdict; it must never
        rescue the health signal, so primary failures are reported even on a
        successful escalated verdict (see _assert_post_writer_path_healthy).
        """
        errors: list[str] = []
        primary_errors: list[str] = []
        contract_errors: list[str] = []
        attempts = 0
        # Only an actual primary failure marks the path unhealthy; "no primary
        # configured" is a different fact and is not evidence of an outage.
        primary_healthy = True
        for llm, escalated in (
            (self.plan_audit_llm, False),
            (self.plan_audit_escalation_llm, True),
        ):
            if llm is None:
                continue
            if not escalated and self._health_domain(llm) in self._unhealthy_domains:
                # Already proved dead this run. Re-dialling it at every audit is how
                # the 14:02 run spent 10 primary calls on an account that answered
                # none of them.
                errors.append(
                    f"primary: skipped, {self._health_domain(llm)[1]} already failed "
                    "this run"
                )
                primary_healthy = False
                primary_errors.append(errors[-1])
                continue
            if escalated and not self._is_independent_of(llm, self.plan_audit_llm):
                errors.append(
                    "plan audit escalation is the same provider/model as the primary "
                    "auditor; a second opinion from the same client is not a second opinion"
                )
                continue
            for _attempt in range(2):
                attempts += 1
                # A contract retry is not a creative attempt and must not read as
                # one in the ledger: it is the same plan, re-asked for grounding.
                self._record_call(
                    "plan_audit_contract_retry" if contract_errors
                    else ("plan_audit_escalation" if escalated else "plan_audit")
                )
                retry = (
                    "\nCONTRACT RETRY. Your previous response was rejected before it "
                    "was read:\n- " + "\n- ".join(contract_errors)
                    + "\nEvery major/critical must copy one exact, unique substring of "
                    "the plan field it challenges into evidence_quote, and must name a "
                    "real story_id. If you cannot quote it, it is a minor."
                    if contract_errors else ""
                )
                try:
                    response, review_obj = await llm.complete_structured(
                        system=(
                            "You are a skeptical plausibility auditor for first-person "
                            "first-person stories. Return valid JSON only."
                        ),
                        messages=[{
                            "role": "user",
                            "content": _plan_audit_prompt(plan, strategy) + reaudit + retry,
                        }],
                        output_schema=PlanPlausibilityReview,
                        max_tokens=2400,
                        temperature=0.2,
                    )
                    self._record_cost(response)
                    review = PlanPlausibilityReview.model_validate(review_obj)
                except Exception as exc:
                    message = f"{'escalation' if escalated else 'primary'}: {_redact(exc, 300)}"
                    errors.append(message)
                    if not escalated:
                        primary_healthy = False
                        primary_errors.append(message)
                        # Mark the account dead HERE, the moment it is known, not
                        # after the caller inspects the verdict. Live 2026-07-17
                        # 14:32 was stopped after ~31 minutes with zero writer
                        # calls: the mark happened downstream of the audit, so a
                        # re-audit inside targeted repair could still queue behind
                        # the same dead provider. One failure is enough evidence;
                        # everything after it in this run routes around it.
                        self._unhealthy_domains.add(self._health_domain(llm))
                    continue
                # Calibrate first: an objection the auditor admits is site-specific
                # is a minor, and minors are not held to the blocking-grounding
                # contract — so a demoted claim cannot fail the contract either.
                review = calibrate_plan_issues(review)
                contract_errors = validate_plan_audit_issues(review, plan)
                if contract_errors:
                    continue
                return evaluate_plan_audit(
                    review, plan, attempts=attempts, escalated=escalated,
                    primary_healthy=primary_healthy,
                    primary_provider_errors=primary_errors,
                    verdict_source="escalation" if escalated else "primary",
                )
        if contract_errors:
            # The auditor answered and could not ground its own objections. That is
            # not a clean plan and not an outage; it is an auditor whose verdict
            # cannot be acted on, so it fails closed as its own status.
            return PlanAuditResult(
                status="contract_failed",
                attempts=attempts,
                contract_errors=contract_errors,
                provider_errors=errors,
                primary_healthy=primary_healthy,
                primary_provider_errors=primary_errors,
                verdict_source="none",
            )
        return PlanAuditResult(
            status="infra_failed", attempts=attempts, provider_errors=errors or [
                "no plan auditor is configured"
            ],
            primary_healthy=primary_healthy,
            primary_provider_errors=primary_errors,
            verdict_source="none",
        )

    async def _repair_plan(
        self,
        plan: CompilationPlan,
        audit: PlanAuditResult,
        story_count: int,
        strategy: NamedChannelStrategy,
        forbidden: set[str],
        spent_concepts: list[CompilationPlan],
        rejected_digests: set[str],
        *,
        attempt_index: int,
        planner_attempt: int,
        reject,
    ) -> tuple[CompilationPlan | None, PlanAuditResult | None]:
        """Fix the stories the audit blocked, byte-preserving the ones it did not.

        The 13:34 run spent 9.6 minutes and never wrote a word, mostly re-rolling
        entire compilations because one story's cart geometry or one shed latch was
        wrong. Two of three stories were usually fine and were thrown away with the
        third. This applies the auditor's own plan_fix to the failed stories only,
        then re-runs EVERY gate — preflight, freshness, mechanism diversity and a
        full fresh audit — so a repair cannot buy its way past a rule the planner
        would have had to satisfy.

        Bounded and monotonic: a premise-wide objection is not repairable and
        abandons the concept, a repair that returns the wrong stories or regresses
        the blocker count is rejected, and repairs are capped so time cannot grow
        without limit.
        """
        blocking = [
            item for item in audit.issues if item.severity in {"critical", "major"}
        ]
        failed_ids = [item.story_id for item in blocking]
        if not blocking or any(not sid for sid in failed_ids):
            return None, None  # compilation-level objection: not a local fix
        ordered_failed = [
            item.story_id for item in plan.stories if item.story_id in set(failed_ids)
        ]
        # "Every story objected to" means the premise is the defect — when there
        # are several stories. With ONE story, any objection at all satisfied
        # this test, so single-story plans could never be repaired: the best
        # plan this channel had produced (seven rungs, a dog, a bulb unscrewed
        # and set upright, a private nickname) was discarded for a fix the
        # auditor itself spelled out in one sentence — "have him test the knob
        # while she is already moving away". A local objection with a concrete
        # FIX is local regardless of how many stories exist. Only a plan with
        # two or more stories can have "all of them" mean "the concept".
        if len(plan.stories) > 1 and len(ordered_failed) >= len(plan.stories):
            return None, None  # every story objected to: the premise itself is the defect

        current_plan = plan
        current_audit = audit
        # ONE OBJECTION PER CATEGORY PER STORY. Across five live passes the
        # auditor re-raised prop_staging on the same screen with a new
        # complaint each round ('not specific enough', 'frame condition that
        # could be further bent') and human_behavior on the same shout
        # ('bluff?', 'dispatched yet?', 'on the line is ambiguous'). A repair
        # that changed the story is the answer to that category; a re-audit
        # that moves the goalposts on it is demoted to a note.
        raised_keys: dict = {}
        for _i in audit.issues:
            if _i.severity in {"critical", "major"} and _i.category != "gate":
                raised_keys.setdefault((_i.story_id, _i.category), set()).add(_issue_sig(_i))
        clean_ids = [
            item.story_id for item in plan.stories if item.story_id not in set(failed_ids)
        ]
        clean_before = {
            item.story_id: item.model_dump(mode="json")
            for item in plan.stories if item.story_id in clean_ids
        }
        for _repair in range(strategy.max_plan_repairs):
            started = time.monotonic()
            targets = [
                item.story_id for item in current_plan.stories
                if item.story_id in {
                    issue.story_id for issue in current_audit.issues
                    if issue.severity in {"critical", "major"}
                }
            ]
            base_prompt = _plan_repair_prompt(
                current_plan, targets,
                [
                    item for item in current_audit.issues
                    if item.severity in {"critical", "major"}
                ],
                strategy,
            )
            # ONE schema/JSON contract retry, outside the creative repair budget and
            # counted apart from it. Live 2026-07-17 16:03: all three repairs died
            # here — twice on continuity_ledger entries over 24 words, once on a
            # truncated JSON object — so the proposed fixes were never judged at
            # all. A malformed envelope is not a rejected idea, and burning the
            # concept for one is how a good repair gets thrown away unread.
            repair = None
            schema_error = ""
            for schema_try in range(2):
                self._record_call(
                    "plan_repair_schema_retry" if schema_try else "plan_repair"
                )
                contract = (
                    "\n\nCONTRACT RETRY. Your previous reply was rejected by the "
                    "validator before anyone read your fix:\n"
                    + _redact(schema_error, 600)
                    + "\nReturn THE SAME repaired stories again — same story_ids, same "
                    "fixes, same intent. Do not redesign anything and do not rethink "
                    "the objection; only correct what the validator named. If a "
                    "continuity_ledger entry is too long, shorten that entry's wording "
                    "to 24 words or fewer without dropping the fact it carries."
                    if schema_error else ""
                )
                try:
                    response, repair_obj = await self.plan_repair_llm.complete_structured(
                        system=(
                            "You are a continuity-focused commissioning editor repairing "
                            "specific blocked stories in a locked plan. Return valid "
                            "compact JSON only."
                        ),
                        messages=[{"role": "user", "content": base_prompt + contract}],
                        output_schema=PlanRepairOutput,
                        # Headroom: a repair truncated mid-object is a wasted call.
                        max_tokens=6000,
                        temperature=0.3,
                    )
                    self._record_cost(response)
                    repair = PlanRepairOutput.model_validate(repair_obj)
                    break
                except Exception as exc:
                    schema_error = f"plan repair schema/provider error: {_redact(exc, 600)}"
                    repair = None
            if repair is None:
                reject(
                    "repair", [schema_error],
                    planner_attempt=planner_attempt, started=started,
                    raw_evidence=schema_error,
                )
                return None, None

            returned = [item.story_id for item in repair.stories]
            if returned != targets:
                reject(
                    "repair",
                    [
                        f"plan repair must return exactly the blocked stories {targets} "
                        f"in order; received {returned}"
                    ],
                    planner_attempt=planner_attempt, started=started,
                )
                return None, None

            replacements = {item.story_id: item for item in repair.stories}
            _update = {"stories": [
                replacements.get(item.story_id, item) for item in current_plan.stories
            ]}
            if (repair.cold_open or "").strip() and any(
                    i.category == "cold_open" for i in current_audit.issues):
                _update["cold_open"] = repair.cold_open.strip()
            candidate = current_plan.model_copy(update=_update)
            candidate = _salvage_cold_open(candidate)
            # A cold_open-only objection is an objection to ONE LINE. Live: asked
            # to replace the cold open, the repairer returned a different story
            # (a new narrator, a new house) and the drift check, which guards
            # only the clean stories, let it through.
            _round_blocking = [i for i in current_audit.issues if i.severity in {"critical", "major"}]
            if _round_blocking and all(i.category == "cold_open" for i in _round_blocking):
                rewritten = [
                    sid for sid in targets
                    if next(i for i in candidate.stories if i.story_id == sid).model_dump(mode="json")
                    != next(i for i in current_plan.stories if i.story_id == sid).model_dump(mode="json")
                ]
                if rewritten:
                    reject(
                        "repair",
                        [f"only the cold open was objected to, but the repair rewrote {rewritten}; "
                         "return the stories byte-identical and a new cold_open"],
                        planner_attempt=planner_attempt, started=started, candidate=candidate,
                    )
                    return None, None
            # The promise of a targeted repair: untouched stories are untouched.
            drifted = [
                sid for sid, before in clean_before.items()
                if next(
                    item for item in candidate.stories if item.story_id == sid
                ).model_dump(mode="json") != before
            ]
            if drifted:
                reject(
                    "repair",
                    [f"plan repair altered approved stories {drifted}"],
                    planner_attempt=planner_attempt, started=started,
                    candidate=candidate,
                )
                return None, None

            candidate = _salvage_voice_seeds(candidate)
            errors = validate_plan_preflight(candidate, story_count, strategy)
            errors += _plan_freshness_errors(candidate, forbidden, spent_concepts)
            errors += _plan_repeat_errors(candidate, rejected_digests)
            if errors:
                reject(
                    "repair", errors, planner_attempt=planner_attempt,
                    started=started, candidate=candidate,
                )
                return None, None

            repaired_audit = await self._audit_plan(
                candidate, strategy,
                reaudit=_reaudit_contract(current_plan, candidate, current_audit))
            if repaired_audit.status == "blocked":
                repaired_audit = _demote_goalpost_moves(
                    repaired_audit, raised_keys, _changed_fields(current_plan, candidate), candidate)
            for _i in repaired_audit.issues:
                if _i.severity in {"critical", "major"} and _i.category != "gate":
                    raised_keys.setdefault((_i.story_id, _i.category), set()).add(_issue_sig(_i))
            if repaired_audit.status == "valid":
                return candidate, repaired_audit
            if repaired_audit.status in {"infra_failed", "contract_failed"}:
                reject(
                    "repair",
                    repaired_audit.provider_errors + repaired_audit.contract_errors,
                    planner_attempt=planner_attempt, started=started,
                    candidate=candidate, audit=repaired_audit,
                )
                return None, None
            # PROGRESS IS THE OLD OBJECTIONS GONE, NOT A SMALLER COUNT. The loaded
            # run-15 plan had one gate blocker (a coincidental escape); the repair
            # fixed it and the re-audit raised two NEW objections (knowledge path,
            # staying at the counter). Two >= one read as regression and the
            # premise was thrown away with its best rung repaired. A round that
            # clears every objection it was given has earned another.
            # An objection is the SAME objection when it points at the same plan
            # text, not merely the same category: the auditor raises a fresh
            # human_behavior note on every repaired rung, and a category key read
            # three rounds of real progress as three rounds of no progress.
            _key = lambda i: (i.story_id, i.category,
                              " ".join((i.evidence_quote or i.problem or "").split()).lower()[:60])
            prev_keys = {_key(i) for i in current_audit.issues if i.severity in {"critical", "major"}}
            new_keys = {_key(i) for i in repaired_audit.issues if i.severity in {"critical", "major"}}
            cleared_all = bool(prev_keys) and not (prev_keys & new_keys)
            regressed = (
                len(repaired_audit.blockers) >= len(current_audit.blockers)
                and not cleared_all
            )
            reject(
                "repair", list(repaired_audit.blockers),
                planner_attempt=planner_attempt, started=started,
                candidate=candidate, audit=repaired_audit,
            )
            if regressed:
                # No progress: another round would just re-roll the same objection.
                return None, None
            current_plan, current_audit = candidate, repaired_audit
        return None, None

    async def _release_challenge(
        self,
        plan: CompilationPlan,
        stories: list[StoryDraft],
        strategy: NamedChannelStrategy,
    ) -> tuple[ReleaseChallengeResult, bool, list[StoryIssue]]:
        """One adversarial pass over a compilation every other gate already approved.

        Runs only for would-be releases: it is the last line, not a tax on drafts
        that are failing anyway. The 2026-07-17 build is why it exists — the critic
        filed an impossible escape as a style note, the final editor wrote "No
        human-safety failures" and "Ending mechanisms vary" about three stories with
        one beat sheet and a child who told no one. Both judges were the same
        provider reading with the same assumptions. This one is prompted to disagree
        and, where configured, runs on a different model family.

        Fail-closed everywhere: an unreachable challenger, a malformed contract, and
        an ungrounded veto all return passed=False. It can block a release; it can
        never wave one through on its own say-so.
        """
        if not strategy.release_challenger_required:
            return ReleaseChallengeResult(status="not_required"), True, []
        if self.release_challenger_llm is None:
            return ReleaseChallengeResult(
                status="not_configured",
                errors=["no release challenger is configured"],
            ), False, []

        # Rechecked here and not only at preflight: the resolved identity is what
        # matters, and a client can be swapped or re-resolved after construction.
        # Measured against the judges that ACTUALLY approved this compilation —
        # on a fallback path those are not the ones the wiring nominated, and a
        # Sonnet challenger reviewing a Sonnet fallback judge is one reader twice.
        challenger_identity = self._llm_identity(self.release_challenger_llm)
        independent = (
            self._is_independent_of(self.release_challenger_llm, self.critic_llm)
            and challenger_identity not in self._judge_identities_used
        )
        errors: list[str] = []
        for attempt in range(2):
            retry = (
                "\nCONTRACT RETRY. Your previous response was rejected before it was "
                "read:\n- " + "\n- ".join(errors)
                + "\nEvery fail verdict needs one exact, unique, verbatim quote from the "
                "named story. Copy it character for character or downgrade the verdict."
                if errors else ""
            )
            self._record_call("release_challenger")
            try:
                response, challenge_obj = await self.release_challenger_llm.complete_structured(
                    system=(
                        "You are an adversarial release challenger. Assume the approval "
                        "in front of you is wrong and find the reason. Return valid JSON "
                        "only; never rewrite narration."
                    ),
                    messages=[{"role": "user", "content": _release_challenge_prompt(
                        plan, stories, strategy, retry
                    )}],
                    output_schema=ReleaseChallenge,
                    max_tokens=2400,
                    temperature=0.15,
                )
                self._record_cost(response)
                challenge = ReleaseChallenge.model_validate(challenge_obj)
            except Exception as exc:
                errors = [f"schema/provider failure: {str(exc)[:300]}"]
                continue

            story_map = {story.story_id: story.narration for story in stories}
            verdicts = [
                item.model_copy(update={
                    "evidence_quote": (
                        _canonical_quote(story_map[item.story_id], item.evidence_quote)
                        or item.evidence_quote
                    ),
                })
                if item.story_id in story_map and item.evidence_quote else item
                for item in challenge.verdicts
            ]
            # Grounding is checked before coverage, and a grounded veto is returned
            # before coverage is checked at all. A proven defect is proven whether or
            # not the challenger also remembered to bless the other six axes; making
            # a real finding contingent on a formatting nicety is how a gate becomes
            # decorative. Coverage only gates the optimistic direction: a PASS must
            # have looked at everything it claims to have looked at.
            errors = []
            failures = [item for item in verdicts if item.verdict == "fail"]
            for item in failures:
                narration = story_map.get(item.story_id)
                if narration is None:
                    errors.append(
                        f"{item.axis}: a fail must name one of {sorted(story_map)}; "
                        f"received {item.story_id!r}"
                    )
                elif narration.count(item.evidence_quote or "\0") != 1:
                    errors.append(
                        f"{item.axis}: evidence_quote must be one exact unique quote "
                        f"from {item.story_id}"
                    )
            if errors:
                continue
            if not failures:
                covered = {item.axis for item in verdicts}
                missing = [name for name, _rule in _CHALLENGE_AXES if name not in covered]
                if missing:
                    errors = [
                        "a pass verdict is only worth the axes it actually examined; "
                        f"missing a verdict for: {', '.join(missing)}"
                    ]
                    continue

            issues = [StoryIssue(
                story_id=item.story_id,
                severity="major",
                problem=f"[release_challenger/{item.axis}] {item.explanation}",
                repair_instruction=(
                    f"Resolve the {item.axis} defect at the quoted text without "
                    "changing clean facts or the locked plan."
                ),
                issue_kind="contradiction",
                evidence_quote=item.evidence_quote,
                confidence=0.9,
                viewer_impact=(
                    "An independent adversarial reader rejected this compilation on "
                    f"{item.axis} after every other gate approved it."
                ),
                issue_id=f"challenge:{item.story_id}:{item.axis}",
            ) for item in failures]
            # A veto blocks whoever found it: a grounded quote is evidence, and
            # evidence does not become less true for coming from a correlated
            # judge. An approval is the opposite — it is only worth the
            # independence of the reader who gave it, so a challenger sharing the
            # critic's provider cannot convert "I found nothing" into a release.
            if failures:
                status = "failed"
            elif not independent:
                status = "not_independent"
                errors = [
                    "release challenger resolves to the same provider/model as the "
                    f"critic it must challenge ({self._llm_identity(self.critic_llm)!r}); "
                    "it found nothing, but a third opinion from the same provider is "
                    "the same blind spot, not an independent one"
                ]
            else:
                status = "passed"
            return ReleaseChallengeResult(
                status=status,
                verdicts=verdicts,
                summary=challenge.summary,
                attempts=attempt + 1,
                errors=errors if status == "not_independent" else [],
                challenger_is_independent=independent,
            ), status == "passed", issues

        return ReleaseChallengeResult(
            status="contract_failed",
            attempts=2,
            errors=errors,
            challenger_is_independent=independent,
        ), False, []

    # The unauditable-structure marker: beat evidence that cannot be quoted as
    # separate spans, i.e. the prose merged plan beats into one sentence.
    _UNAUDITABLE_MARKER = "ordered and non-overlapping"

    async def _rescue_unauditable_stories(
        self,
        plan: CompilationPlan,
        stories: list[StoryDraft],
        gate: GateReport,
        compliance_reviews: dict[str, StoryComplianceReview],
        per_story: int,
        strategy: NamedChannelStrategy,
    ) -> tuple[list[StoryDraft], GateReport, dict[str, StoryComplianceReview], bool]:
        """One bounded rewrite for stories whose compliance audit failed its
        contract because beat evidence could not be quoted separately.

        Live 2026-07-19 (self-storage 2119, 4th occurrence of the class):
        story_2 merged plan beats, the auditor failed 'strictly ordered and
        non-overlapping' twice, and a compilation with three written stories
        and near-clean gates died at 0/100 with no repair attempted. Merged
        beats ARE a prose defect (unauditable = unreleasable) — but a
        REWRITABLE one, the same routing length defects already get. Any
        other contract-failure class still fails closed unchanged."""
        failing = {
            sid: errs for sid, errs in self._last_compliance_errors.items()
            if errs and all(self._UNAUDITABLE_MARKER in e for e in errs)
        }
        if not failing or set(failing) != set(self._last_compliance_errors):
            return stories, gate, compliance_reviews, False
        plans_by_id = {item.story_id: item for item in plan.stories}
        originals = {item.story_id: item for item in stories}
        rewritten: dict[str, StoryDraft] = {}
        for story_id, errs in failing.items():
            if story_id not in plans_by_id or story_id not in originals:
                return stories, gate, compliance_reviews, False
            replacement = await self._rewrite_fallback(
                plan, plans_by_id[story_id], stories, gate, originals[story_id],
                [], [
                    "The compliance auditor could not ground this story twice: "
                    + "; ".join(errs)
                    + ". Give every plan beat its OWN sentence, in plan order — "
                    "especially the escape decision and the completed escape — so "
                    "each beat can be quoted as a separate, non-overlapping span.",
                ], per_story, strategy,
                "beat evidence could not be quoted separately (unauditable)",
            )
            if replacement is None:
                return stories, gate, compliance_reviews, False
            rewritten[story_id] = replacement
        candidate = [rewritten.get(item.story_id, item) for item in stories]
        candidate_gate = gate_compilation(plan, candidate, strategy)
        reviews, valid = await self._audit_stories(
            plan, candidate, strategy,
            only_ids=set(rewritten), prior=compliance_reviews,
        )
        if not valid:
            return stories, gate, compliance_reviews, False
        return candidate, candidate_gate, reviews, True

    async def _originality_tiebreak(
        self,
        plan: CompilationPlan,
        stories: list[StoryDraft],
        gate: GateReport,
        score: NarrativeScorecard,
        strategy: NamedChannelStrategy,
    ) -> NarrativeScorecard:
        """One calibrated second read when originality ALONE blocks the lock.

        External review 2026-07-20: a single holistic integer from one judge
        is the noisiest instrument in the scorecard, and the 6-vs-7 boundary
        is a release decision (measured drift: the same text read 84 then 81;
        originality oscillated 6↔7 across runs of one topic). When every
        other lock condition passes and the SOLE miss is the originality
        floor, the strongest available judge — the challenger-tier client,
        cross-provider when one is configured — takes one anti-anchored
        second read whose verdict REPLACES the first, in either direction.
        The floor itself never moves; this adds a judge, not a discount."""
        if self.release_challenger_llm is None:
            return score
        floor = strategy.originality_min
        if score.originality >= floor:
            return score
        would_lock = score.model_copy(
            update={"originality": int(math.ceil(floor))}
        )
        if not content_can_lock(would_lock, gate, strategy):
            return score
        self._record_call("originality_tiebreak")
        body = "\n\n".join(
            f"[{s.story_id}] {s.title}\n{s.narration}" for s in stories
        )
        try:
            response, obj = await self.release_challenger_llm.complete_structured(
                system=(
                    "You are a calibration judge scoring ONLY originality. "
                    "Return valid JSON only."
                ),
                messages=[{"role": "user", "content": (
                    "Score originality 0-10 for this three-story first-person "
                    "horror compilation.\nCALIBRATION: 6 = competently executed "
                    "but a viewer who watches nightly horror compilations has "
                    "seen every mechanism here this month (a stock premise worn "
                    "well); 7 = at least ONE story turns on a concrete mechanism "
                    "such a viewer has NOT seen recently; 9 = two or more such "
                    "stories. Judge ONLY what happens on the page — any claim of "
                    "freshness is a claim, not evidence. justification: one "
                    "sentence naming the mechanism that earned or failed the "
                    "seventh point.\n\n" + body
                )}],
                output_schema=OriginalityVerdict,
                max_tokens=400,
                temperature=0.0,
            )
            self._record_cost(response)
            verdict = OriginalityVerdict.model_validate(obj)
        except Exception:
            return score  # tiebreak is best-effort; the first read stands
        return score.model_copy(update={
            "originality": max(0, min(10, verdict.originality)),
        })

    async def hospital_pass(
        self,
        plan: CompilationPlan,
        stories: list[StoryDraft],
        strategy: NamedChannelStrategy | None = None,
        per_story: int | None = None,
    ) -> dict:
        """Offline near-miss rescue: re-judge and repair a SAVED candidate.

        External review 2026-07-20 (both reviewers): candidates rejected at
        the release door are serialized with every blocker quoted — then never
        read again; each new run regenerates from zero at roughly 3x the cost
        of finishing the saved one. This pass reconstructs the judged state
        from a stored plan + stories and runs the SAME wave machinery as a
        live run (same guards, same acceptance — the loop body deliberately
        mirrors run()), then reports whether the repaired compilation clears
        content_can_lock. It does NOT run the final editor or the release
        challenger and never flips production_ready: per the same review, no
        auto-release before a current-policy artifact passes independent
        audit — hospital output goes to a human."""
        strategy = strategy or self.quality_strategy
        per_story = per_story or max(
            1, plan.target_word_count // max(1, len(plan.stories))
        )
        self._run_call_counts = {}
        self._run_cost_usd = 0.0
        self._run_notional_cost_usd = 0.0
        self._last_compliance_errors = {}

        gate = gate_compilation(plan, stories, strategy)
        compliance_reviews, compliance_valid = await self._audit_stories(
            plan, stories, strategy
        )
        if not compliance_valid:
            stories, gate, compliance_reviews, compliance_valid = (
                await self._rescue_unauditable_stories(
                    plan, stories, gate, compliance_reviews, per_story, strategy
                )
            )
        if compliance_valid:
            score, critic_valid, _ = await self._score_validated(
                plan, stories, gate, strategy, compliance_reviews=compliance_reviews
            )
            score = self._with_compliance_issues(score, compliance_reviews)
        else:
            score = self._zero_score(
                "hospital: per-story compliance failed its contract twice"
            )
            critic_valid = True

        repair_waves = 0
        decisions: list[PatchDecision] = []
        expected_ids = {item.story_id for item in plan.stories}
        while critic_valid and compliance_valid and repair_waves < 3:
            failing_ids = {
                sid for failure in gate.failures for sid in failure.story_ids
                if sid in expected_ids
            }
            failing_ids.update(
                issue.story_id for issue in score.story_issues
                if issue.story_id in expected_ids
                and issue.severity in {"critical", "major"}
            )
            if not failing_ids:
                failing_ids = _near_miss_minor_ids(
                    score, gate, strategy, expected_ids, repair_waves
                )
            if not failing_ids:
                break
            if repair_waves == 1 and (
                not gate.passed
                or score.total_score < strategy.approval_score
                or score.critical_issues
                or len(failing_ids) > 3
            ):
                break
            if repair_waves == 2 and not _finishing_wave_allowed(
                score, gate, strategy, failing_ids
            ):
                break
            candidate_list, wave_decisions = await self._repair_wave(
                plan, stories, score, gate, failing_ids, per_story, strategy
            )
            repair_waves += 1
            decisions.extend(wave_decisions)
            if not self._stories_changed(stories, candidate_list):
                break
            candidate_gate = gate_compilation(plan, candidate_list, strategy)
            changed_ids = {
                before.story_id
                for before, after in zip(stories, candidate_list, strict=True)
                if before.narration != after.narration
            }
            candidate_reviews, candidate_compliance_valid = await self._audit_stories(
                plan, candidate_list, strategy,
                only_ids=changed_ids, prior=compliance_reviews,
            )
            if not candidate_compliance_valid:
                break
            candidate_score, candidate_valid, _ = await self._score_validated(
                plan, candidate_list, candidate_gate, strategy,
                compliance_reviews=candidate_reviews,
            )
            candidate_score = self._with_compliance_issues(
                candidate_score, candidate_reviews
            )
            if not candidate_valid or not self._repair_is_monotonic(
                score, gate, candidate_score, candidate_gate, strategy
            ):
                salvage = await self._salvage_single_patch(
                    plan, stories, candidate_list, changed_ids, score, gate,
                    strategy, compliance_reviews,
                )
                if salvage is None:
                    break
                stories, gate, score, compliance_reviews = salvage
                critic_valid = True
                compliance_valid = True
                continue
            stories, gate, score, critic_valid = (
                candidate_list, candidate_gate, candidate_score, candidate_valid
            )
            compliance_reviews = candidate_reviews
            compliance_valid = candidate_compliance_valid

        if compliance_valid and critic_valid:
            score = await self._originality_tiebreak(
                plan, stories, gate, score, strategy
            )
        lockable = bool(
            compliance_valid and critic_valid and content_can_lock(
                score, gate, strategy,
                critic_contract_valid=critic_valid,
                story_compliance_valid=(
                    compliance_valid
                    and self._compliance_set_approved(plan, compliance_reviews)
                ),
            )
        )
        return {
            "stories": stories,
            "gate": gate,
            "score": score,
            "compliance_reviews": compliance_reviews,
            "content_lockable": lockable,
            "repair_waves": repair_waves,
            "patch_decisions": decisions,
            "call_counts": dict(self._run_call_counts),
            "notional_cost_usd": self._run_notional_cost_usd,
        }

    async def _audit_stories(
        self,
        plan: CompilationPlan,
        stories: list[StoryDraft],
        strategy: NamedChannelStrategy,
        *,
        only_ids: set[str] | None = None,
        prior: dict[str, StoryComplianceReview] | None = None,
    ) -> tuple[dict[str, StoryComplianceReview], bool]:
        if self.compliance_llm is None:
            return {}, False
        plan_map = {item.story_id: item for item in plan.stories}
        review_map = dict(prior or {})
        targets = [
            story for story in stories
            if only_ids is None or story.story_id in only_ids
        ]

        async def audit_one(story: StoryDraft):
            errors: list[str] = []
            for _attempt in range(2):
                retry = (
                    "CONTRACT RETRY. Correct only these grounding errors:\n- "
                    + "\n- ".join(errors)
                    if errors else ""
                )
                auditor, stage = self._routed_judge(
                    self.compliance_llm, self.compliance_escalation_llm,
                    "story_compliance",
                )
                self._record_call(stage)
                try:
                    response, obj = await auditor.complete_structured(
                        system=(
                            "You are a literal plan-entailment auditor. Return valid JSON only; "
                            "never rewrite or score prose."
                        ),
                        messages=[{"role": "user", "content": _story_compliance_prompt(
                            plan_map[story.story_id], story, strategy, retry
                        )}],
                        output_schema=StoryComplianceReview,
                        max_tokens=1800,
                        temperature=0.0,
                    )
                    self._record_cost(response)
                    review = StoryComplianceReview.model_validate(obj)
                    review = _canonicalize_story_compliance(story, review)
                except Exception as exc:
                    errors = [f"schema or provider error: {str(exc)[:500]}"]
                    continue
                errors = validate_story_compliance(
                    plan_map[story.story_id], story, review
                )
                if not errors:
                    shell = self._zero_score("story compliance forensic shell").model_copy(
                        update={"story_issues": story_compliance_issues(review)}
                    )
                    errors = validate_forensic_issues(shell, [story])
                if not errors:
                    return story.story_id, review, []
            if self.compliance_escalation_llm is not None:
                self._record_call("story_compliance_escalation")
                retry = (
                    "ESCALATED CONTRACT CHECK. The fast auditor failed twice:\n- "
                    + "\n- ".join(errors)
                    + "\nReturn literal narration quotes; do not echo plan text as evidence."
                )
                try:
                    response, obj = await self.compliance_escalation_llm.complete_structured(
                        system=(
                            "You are the senior literal plan-entailment auditor. Return valid "
                            "JSON only; never rewrite or score prose."
                        ),
                        messages=[{"role": "user", "content": _story_compliance_prompt(
                            plan_map[story.story_id], story, strategy, retry
                        )}],
                        output_schema=StoryComplianceReview,
                        max_tokens=2000,
                        temperature=0.0,
                    )
                    self._record_cost(response)
                    review = _canonicalize_story_compliance(
                        story, StoryComplianceReview.model_validate(obj)
                    )
                    errors = validate_story_compliance(
                        plan_map[story.story_id], story, review
                    )
                    if not errors:
                        shell = self._zero_score(
                            "escalated story compliance forensic shell"
                        ).model_copy(update={
                            "story_issues": story_compliance_issues(review)
                        })
                        errors = validate_forensic_issues(shell, [story])
                    if not errors:
                        return story.story_id, review, []
                except Exception as exc:
                    errors = [f"escalation schema or provider error: {str(exc)[:500]}"]
            logger.warning("story_compliance.contract_failed", story_id=story.story_id, errors=[e[:300] for e in errors][:3])
            return story.story_id, None, errors

        results = await asyncio.gather(*(audit_one(story) for story in targets))
        all_valid = True
        for story_id, review, _errors in results:
            if review is None:
                review_map.pop(story_id, None)
                self._last_compliance_errors[story_id] = list(_errors)
                all_valid = False
            else:
                review_map[story_id] = review
                self._last_compliance_errors.pop(story_id, None)
        expected = {story.story_id for story in stories}
        all_valid = all_valid and set(review_map) == expected
        return review_map, all_valid

    def _compliance_set_approved(
        self,
        plan: CompilationPlan,
        reviews: dict[str, StoryComplianceReview],
    ) -> bool:
        if self.compliance_llm is None:
            return False
        expected = [item.story_id for item in plan.stories]
        return list(reviews) == expected and all(
            story_compliance_approved(reviews[story_id]) for story_id in expected
        )

    @staticmethod
    def _with_compliance_issues(
        score: NarrativeScorecard,
        reviews: dict[str, StoryComplianceReview],
    ) -> NarrativeScorecard:
        combined = list(score.story_issues)
        seen = {item.issue_id for item in combined if item.issue_id}
        for review in reviews.values():
            for issue in story_compliance_issues(review):
                if issue.issue_id and issue.issue_id in seen:
                    continue
                combined.append(issue)
                if issue.issue_id:
                    seen.add(issue.issue_id)
        return score.model_copy(update={"story_issues": combined})

    @staticmethod
    def _zero_score(summary: str) -> NarrativeScorecard:
        return NarrativeScorecard(
            continuity_believability=0, distinct_authentic_voices=0,
            dread_escalation=0, plausible_response=0, structural_variety=0,
            originality=0, ending_discipline=0, editorial_summary=summary,
        )

    async def _recover_stories(
        self,
        plan: CompilationPlan,
        stories: list[StoryDraft],
        gate: GateReport,
        failing_ids: set[str],
        per_story: int,
        strategy: NamedChannelStrategy,
    ) -> list[StoryDraft]:
        """One bounded full-story rewrite per locally failed first draft.

        Acceptance is deterministic: the story's attributable hard-gate failures
        must strictly decrease, or tie at zero while the word count moves strictly
        closer to the per-story target. Anything else keeps the original bytes.
        """
        plans_by_id = {item.story_id: item for item in plan.stories}
        originals = {item.story_id: item for item in stories}

        async def recover_one(story_id: str) -> StoryDraft:
            original = originals[story_id]
            messages = [
                failure.message for failure in gate.failures
                if story_id in failure.story_ids
                and failure.code not in _UNRECOVERABLE_GATE_CODES
            ]
            repair_brief = (
                "Rewrite the full story to fix ONLY these deterministic release "
                f"failures (the current draft has {len(_words(original.narration))} "
                "words):\n- " + "\n- ".join(messages)
                + "\nPreserve every clean fact, the locked plan, and the voice."
            )
            self._record_call("story_writer_recovery")
            try:
                response = await self.writer_llm.complete(
                    system=(
                        "You write restrained, plausible first-person horror "
                        "recollections and obey the locked plan."
                    ),
                    messages=[{"role": "user", "content": _story_prompt(
                        plans_by_id[story_id], per_story, (
                            plan.cold_open if story_id == "story_1"
                            else "Not assigned to this story. Do not quote the "
                            "compilation cold open."
                        ), strategy, repair=repair_brief,
                        original=original.narration, topic=plan.topic,
                    )}],
                    max_tokens=_writer_max_tokens(int(getattr(plans_by_id[story_id], 'target_words', 0) or per_story)),
                    temperature=0.7,
                )
                self._record_cost(response)
                output = _parse_story_output(response.content, plans_by_id[story_id])
                candidate = StoryDraft(story_id=story_id, **output.model_dump())
            except Exception:
                return original
            trial = [
                candidate if item.story_id == story_id else item for item in stories
            ]
            trial_gate = gate_compilation(plan, trial, strategy)
            before = _story_attributable_failures(gate, story_id)
            after = _story_attributable_failures(trial_gate, story_id)
            closer = abs(len(_words(candidate.narration)) - per_story) < abs(
                len(_words(original.narration)) - per_story
            )
            if after < before or (after == before == 0 and closer):
                return candidate
            return original

        recovered = await asyncio.gather(
            *(recover_one(story_id) for story_id in sorted(failing_ids))
        )
        merged = {item.story_id: item for item in stories}
        for item in recovered:
            merged[item.story_id] = item
        return [merged[item.story_id] for item in plan.stories]

    async def _rewrite_fallback(
        self,
        plan: CompilationPlan,
        plan_item: NarrativeStoryPlan,
        stories: list[StoryDraft],
        gate: GateReport,
        original: StoryDraft,
        issues: list[StoryIssue],
        gate_messages: list[str],
        per_story: int,
        strategy: NamedChannelStrategy,
        dead_end_reason: str,
    ) -> StoryDraft | None:
        """One bounded full-story rewrite after the surgical patch path dead-ends.

        Surgical patches structurally cannot fix a length shortfall (the delta
        exceeds the edit budget) or a contradiction whose span exceeds the find
        limit, so a dead-ended contract previously froze the story at baseline
        and the compilation could never lock. Acceptance here is deterministic
        only — no new hard-gate failures attributable to this story and no
        identical bytes; the semantic verdict stays with the wave's compliance
        re-audit, critic re-score, and monotonic gate.
        """
        story_id = original.story_id
        directives = [
            f"[{issue.severity}] {issue.problem} FIX: {issue.repair_instruction}"
            for issue in issues if issue.severity in {"critical", "major"}
        ]
        repair_brief = (
            "The surgical patch contract for this story dead-ended "
            f"({dead_end_reason[:200]}). Rewrite the FULL story instead; the "
            f"current draft has {len(_words(original.narration))} words. Fix "
            "every defect below while preserving every clean fact, the locked "
            "plan, and the voice:\n- " + "\n- ".join([*gate_messages, *directives])
        )
        self._record_call("repair_rewrite")
        try:
            response = await self.writer_llm.complete(
                system=(
                    "You write restrained, plausible first-person horror "
                    "recollections and obey the locked plan."
                ),
                messages=[{"role": "user", "content": _story_prompt(
                    plan_item, per_story, (
                        plan.cold_open if story_id == "story_1"
                        else "Not assigned to this story. Do not quote the "
                        "compilation cold open."
                    ), strategy, repair=repair_brief,
                    original=original.narration, topic=plan.topic,
                )}],
                max_tokens=_writer_max_tokens(int(getattr(plan_item, 'target_words', 0) or per_story)),
                temperature=0.7,
            )
            self._record_cost(response)
            output = _parse_story_output(response.content, plan_item)
            candidate = StoryDraft(story_id=story_id, **output.model_dump())
        except Exception:
            return None
        if candidate.narration == original.narration:
            return None
        trial = [
            candidate if item.story_id == story_id else item for item in stories
        ]
        trial_gate = gate_compilation(plan, trial, strategy)
        before_failures = _story_failure_count(gate, story_id)
        after_failures = _story_failure_count(trial_gate, story_id)
        # Same strictness as the patch filter: a rewrite of a gate-failing story
        # must actually clear failures; a clean story must stay clean.
        if before_failures and after_failures >= before_failures:
            return None
        if not before_failures and after_failures:
            return None
        return candidate

    async def _repair_wave(
        self,
        plan: CompilationPlan,
        stories: list[StoryDraft],
        score: NarrativeScorecard,
        gate: GateReport,
        failing_ids: set[str],
        per_story: int,
        strategy: NamedChannelStrategy,
    ) -> tuple[list[StoryDraft], list[PatchDecision]]:
        plans_by_id = {item.story_id: item for item in plan.stories}
        originals = {item.story_id: item for item in stories}

        async def repair_one(story_id: str) -> tuple[StoryDraft, PatchDecision]:
            issues = [item for item in score.story_issues if item.story_id == story_id]
            gate_messages = [
                failure.message for failure in gate.failures if story_id in failure.story_ids
            ]
            original = originals[story_id]
            # Length defects are structurally unpatchable — the needed word delta
            # exceeds any surgical edit budget — so they route straight to the
            # bounded rewrite (observed live 2026-07-17: a selected patch fixed
            # two majors but the story stayed at 635/750 words and the build died).
            if any(
                failure.code in {"story_length", "total_length"}
                and story_id in failure.story_ids
                for failure in gate.failures
            ):
                rewrite = await self._rewrite_fallback(
                    plan, plans_by_id[story_id], stories, gate, original,
                    issues, gate_messages, per_story, strategy,
                    "length defects are structurally unpatchable",
                )
                if rewrite is not None:
                    return rewrite, PatchDecision(
                        story_id=story_id, selected="full_rewrite",
                        reason=("length defect routed straight to a bounded full "
                                "rewrite; surgical patches cannot move the word count"),
                    )
                return original, PatchDecision(
                    story_id=story_id, selected="baseline",
                    reason="length rewrite did not survive the local hard gate",
                )
            anchors = [
                item.anchor_quote if item.issue_kind == "omission" else item.evidence_quote
                for item in issues if item.severity in {"critical", "major"}
            ]
            approved_anchors = (
                [item for item in anchors if item]
                if anchors and not gate_messages else None
            )
            base_prompt = _repair_patch_prompt(
                plans_by_id[story_id], original.narration, issues, gate_messages,
                per_story, strategy
            )
            # A schema-invalid or locally non-atomic pair gets exactly one
            # contract-only retry carrying the validator error under the identical
            # brief, anchors, and budgets. A second invalid pair fails closed.
            candidate_set: StoryPatchCandidateSet | None = None
            materialized: dict[str, StoryDraft] | None = None
            contract_error = ""
            for _attempt in range(2):
                prompt = base_prompt if not contract_error else (
                    base_prompt
                    + "\n\nCONTRACT RETRY. Your previous candidate pair was rejected "
                    "by the local validator before any edit was applied:\n- "
                    + contract_error
                    + "\nReturn a corrected pair for the identical brief, anchors, and "
                    "edit budgets above. Every find must be a verbatim, exact, unique "
                    "substring of ORIGINAL and every stated budget must hold."
                )
                self._record_call("repair_writer")
                try:
                    response, patch_obj = await self.patch_llm.complete_structured(
                        system=(
                            "You are a surgical continuity editor. Return compact JSON text edits only."
                        ),
                        messages=[{"role": "user", "content": prompt}],
                        output_schema=StoryPatchCandidateSet,
                        max_tokens=2800,
                        temperature=0.45,
                    )
                    self._record_cost(response)
                    candidate_set = StoryPatchCandidateSet.model_validate(patch_obj)
                except Exception as exc:
                    contract_error = f"repair schema/provider failure: {str(exc)[:300]}"
                    continue
                try:
                    materialized = materialize_patch_candidates(
                        original, candidate_set, allowed_anchors=approved_anchors
                    )
                    break
                except ValueError as exc:
                    contract_error = f"invalid atomic candidate pair: {str(exc)[:300]}"
            if materialized is None or candidate_set is None:
                rewrite = await self._rewrite_fallback(
                    plan, plans_by_id[story_id], stories, gate, original,
                    issues, gate_messages, per_story, strategy, contract_error,
                )
                if rewrite is not None:
                    return rewrite, PatchDecision(
                        story_id=story_id, selected="full_rewrite",
                        reason=("patch contract failed twice; bounded full rewrite "
                                f"passed the local hard gate: {contract_error[:120]}"),
                    )
                return original, PatchDecision(
                    story_id=story_id,
                    selected="baseline",
                    reason=("repair contract failed twice and the rewrite fallback "
                            f"did not survive the local hard gate: {contract_error[:120]}"),
                )
            # A candidate must CLEAR the story's deterministic failures, not just
            # avoid adding new ones — a cosmetic patch that leaves a banned-phrase
            # variant standing would ship the defect into a dead second wave.
            before_failures = _story_failure_count(gate, story_id)
            safe: dict[str, StoryDraft] = {}
            for candidate_id, draft in materialized.items():
                trial = [draft if item.story_id == story_id else item for item in stories]
                trial_gate = gate_compilation(plan, trial, strategy)
                after_failures = _story_failure_count(trial_gate, story_id)
                if (after_failures < before_failures if before_failures
                        else after_failures == 0):
                    safe[candidate_id] = draft
            if len(safe) != 2:
                rewrite = await self._rewrite_fallback(
                    plan, plans_by_id[story_id], stories, gate, original,
                    issues, gate_messages, per_story, strategy,
                    "patch candidates failed the deterministic hard gate",
                )
                if rewrite is not None:
                    return rewrite, PatchDecision(
                        story_id=story_id, selected="full_rewrite",
                        reason=("patch candidates failed the hard gate; bounded "
                                "full rewrite passed the local hard gate"),
                    )
                return original, PatchDecision(
                    story_id=story_id, selected="baseline",
                    reason=("candidate failed hard gate and the rewrite fallback "
                            "did not survive the local hard gate"),
                )

            sources: list[tuple[str, StoryDraft]] = [("baseline", original), *safe.items()]
            sources.sort(key=lambda item: hashlib.sha256(
                f"{story_id}:{item[0]}".encode("utf-8")
            ).hexdigest())
            label_map = {
                f"option_{index}": source for index, source in enumerate(sources, 1)
            }
            options = [(label, source[1]) for label, source in label_map.items()]
            self._record_call("blind_selector")
            try:
                response, selection_obj = await self._route(
                    self.critic_llm, self.critic_fallback_llm
                ).complete_structured(
                    system="You are a blind comparative story editor. Return valid JSON only.",
                    messages=[{"role": "user", "content": _blind_selector_prompt(
                        plans_by_id[story_id], options, issues, strategy
                    )}],
                    output_schema=BlindPatchSelection,
                    max_tokens=1200,
                    temperature=0.0,
                )
                self._record_cost(response)
                selection = BlindPatchSelection.model_validate(selection_obj)
            except Exception as exc:
                return original, PatchDecision(
                    story_id=story_id,
                    selected="baseline",
                    reason=f"selector schema/provider failure: {str(exc)[:180]}",
                )
            selected_source = label_map.get(selection.selected_label, ("baseline", original))[0]
            trustworthy = (
                selection.confidence >= strategy.selector_confidence_min
                and selection.preserves_locked_plan
                and selection.resolves_target_issues
                and not selection.introduced_issues
                and not selection.voice_regression
                and not selection.dread_regression
                and not selection.ending_regression
            )
            if not trustworthy:
                selected_source = "baseline"
            chosen = resolve_blind_patch_selection(selected_source, original, safe)
            # selected_source is already the literal candidate ID (or baseline);
            # remapping by pair position mislabels a reversed candidate order.
            return chosen, PatchDecision(
                story_id=story_id,
                selected=selected_source,
                selected_candidate_id=(selected_source if selected_source in safe else None),
                selector_confidence=selection.confidence,
                reason=(selection.rationale if trustworthy else "selector failed closed"),
            )

        repaired = await asyncio.gather(*(
            repair_one(story_id) for story_id in sorted(failing_ids)
        ))
        candidates = {item.story_id: item for item in stories}
        decisions: list[PatchDecision] = []
        for item, decision in repaired:
            candidates[item.story_id] = item
            decisions.append(decision)
        return [candidates[item.story_id] for item in plan.stories], decisions

    async def _score(
        self, plan: CompilationPlan, stories: list[StoryDraft], gate: GateReport,
        strategy: NamedChannelStrategy, contract_retry: str = "",
    ) -> NarrativeScorecard:
        judge, stage = self._routed_judge(
            self.critic_llm, self.critic_fallback_llm, "critic_score"
        )
        self._record_call(stage)
        response, score_obj = await judge.complete_structured(
            system=(
                "You are a skeptical senior horror editor. Return valid JSON only. "
                "Do not reward production metadata or assume a story is true."
            ),
            messages=[{
                "role": "user",
                "content": _critic_prompt(plan, stories, gate, strategy, contract_retry),
            }],
            output_schema=NarrativeScorecard,
            max_tokens=3200,
            temperature=0.2,
        )
        self._record_cost(response)
        return NarrativeScorecard.model_validate(score_obj)

    async def _score_validated(
        self, plan: CompilationPlan, stories: list[StoryDraft], gate: GateReport,
        strategy: NamedChannelStrategy,
        *,
        compliance_reviews: dict[str, StoryComplianceReview] | None = None,
    ) -> tuple[NarrativeScorecard, bool, list[str]]:
        errors: list[str] = []
        score = None
        for attempt in range(2):
            retry = (
                "FORENSIC CONTRACT RETRY. Fix only these schema-grounding errors:\n- "
                + "\n- ".join(errors)
                if errors else ""
            )
            try:
                score = await self._score(plan, stories, gate, strategy, retry)
            except Exception as exc:
                errors = [f"critic schema/provider failure: {str(exc)[:600]}"]
                continue
            score = score.model_copy(update={
                "story_issues": _demote_cross_night_contradictions(
                score.model_copy(update={"story_issues": _canonicalize_issue_quotes(score.story_issues, stories)}),
                stories).story_issues,
            })
            score = promote_miscalibrated_issues(score, strategy)
            errors = validate_forensic_issues(score, stories)
            if attempt == 0 and compliance_reviews:
                for issue in score.story_issues:
                    review = compliance_reviews.get(issue.story_id)
                    if (
                        issue.severity in {"critical", "major"}
                        # A severity we corrected locally is not the judge's claim to
                        # withdraw; asking it to would just relabel the defect minor.
                        and not issue.promoted_from
                        and issue.issue_kind in {"contradiction", "omission"}
                        and review is not None
                        and story_compliance_approved(review)
                    ):
                        errors.append(
                            f"{issue.issue_id or issue.story_id}: independent grounded audit "
                            "found every locked beat complete and plan facts preserved. Re-read "
                            "the exact issue quote/anchor. Withdraw the issue if that text already "
                            "shows the required action; retain it only after identifying the exact "
                            "unmet verb or terminal state."
                        )
            if attempt == 0:
                # A release-blocking dimension deduction with zero critical or
                # major issues is an ungrounded verdict nothing downstream can
                # repair (observed live 2026-07-17: continuity 22/min 23 with an
                # empty issue list starved the whole run at needs_edit). Every
                # other gate in this pipeline demands evidence; so does this one.
                has_blockers = bool(score.critical_issues) or any(
                    issue.severity in {"critical", "major"}
                    for issue in score.story_issues
                )
                if not has_blockers:
                    for dim_field, min_field in _RELEASE_DIMENSION_FLOORS:
                        # Originality is a HOLISTIC compilation property — "this
                        # is competent but familiar" cannot be grounded in a
                        # per-story issue quote the way a continuity deduction
                        # can. Demanding one forced the critic to inflate, to
                        # invent a fake major, or to hold an honest 6 and be
                        # branded contract-invalid — which switched OFF the
                        # whole repair machinery for everything else (live
                        # 2026-07-20: an 85/100 with three repairable
                        # compliance majors got zero repair calls; mall's 84
                        # died identically). The originality FLOOR still blocks
                        # release in content_can_lock; it just is not a
                        # contract violation to score it honestly.
                        if dim_field == "originality":
                            continue
                        value = getattr(score, dim_field)
                        floor = getattr(strategy, min_field)
                        if value < floor:
                            errors.append(
                                f"{dim_field}={value} is below the release floor {floor} "
                                "yet the scorecard reports zero critical or major issues. "
                                "A release-blocking deduction must be grounded: either add "
                                "the specific major issue(s) with exact quotes that justify "
                                "it, or score the dimension consistently with their absence."
                            )
            if not errors:
                return score, True, []
        if score is None:
            score = NarrativeScorecard(
                continuity_believability=0,
                distinct_authentic_voices=0,
                dread_escalation=0,
                plausible_response=0,
                structural_variety=0,
                originality=0,
                ending_discipline=0,
                editorial_summary="Critic failed its structured-output contract twice.",
            )
            logger.warning("critic.contract_failed",
                           errors=[e[:300] for e in errors][:4])
        return score, False, errors

    async def _final_review(
        self, plan: CompilationPlan, stories: list[StoryDraft],
        strategy: NamedChannelStrategy,
    ) -> tuple[FinalCompilationReview, bool]:
        errors: list[str] = []
        review: FinalCompilationReview | None = None
        for _attempt in range(2):
            retry = (
                "FINAL CONTRACT RETRY. Correct only these errors:\n- "
                + "\n- ".join(errors)
                if errors else ""
            )
            judge, stage = self._routed_judge(
                self.critic_llm, self.critic_fallback_llm, "final_editor"
            )
            self._record_call(stage)
            try:
                # Structured output like every other judge call: a raw-text
                # parse once grabbed a stray JSON array instead of the review
                # object and blocked an otherwise clean 100/100 compilation.
                response, review_obj = await judge.complete_structured(
                    system=(
                        "You are the final read-only senior editor. Return valid JSON only and "
                        "never rewrite narration."
                    ),
                    messages=[{
                        "role": "user",
                        "content": _final_review_prompt(plan, stories, strategy, retry),
                    }],
                    output_schema=FinalCompilationReview,
                    max_tokens=2200,
                    temperature=0.1,
                )
                self._record_cost(response)
                review = FinalCompilationReview.model_validate(review_obj)
                review = review.model_copy(update={
                    "issues": _demote_unfounded_editor_issues(
                        _canonicalize_issue_quotes(review.issues, stories), stories),
                })
            except Exception as exc:
                errors = [f"schema/provider failure: {str(exc)[:400]}"]
                continue
            shell_score = self._zero_score("final forensic shell").model_copy(
                update={"story_issues": review.issues}
            )
            errors = validate_forensic_issues(shell_score, stories)
            expected_ids = [item.story_id for item in plan.stories]
            if review.reviewed_story_ids != expected_ids:
                errors.append("reviewed_story_ids do not match locked-plan order")
            if not errors:
                blockers = any(
                    item.severity in {"critical", "major"} for item in review.issues
                )
                return review, review.approved and not blockers
        return FinalCompilationReview(
            approved=False,
            reviewed_story_ids=[item.story_id for item in plan.stories],
            issues=[],
            summary="Final editor contract failed twice: " + "; ".join(errors)[:400],
        ), False

    @property
    def max_plan_attempts(self) -> int:
        return self.quality_strategy.max_plan_attempts

    def _record_call(self, stage: str) -> None:
        self._run_call_counts[stage] = self._run_call_counts.get(stage, 0) + 1

    def _begin_health_context(self) -> None:
        """Start a fresh provider-health context. Owned by the top-level entry
        point (run_with_retry, or a bare run) — never by an inner attempt."""
        self._unhealthy_domains = set()

    def _record_cost(self, response) -> None:
        """Accumulate what the provider reported: marginal and notional, apart.

        Subscription CLI calls report cost_usd=0.0 and a notional figure. Both are
        true and they are not the same fact: the ledger must not inflate budgets
        with a bill nobody sends, and an operator still needs to see that 31
        minutes of Opus went somewhere.
        """
        try:
            self._run_cost_usd += float(getattr(response, "cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
        try:
            self._run_notional_cost_usd += float(
                getattr(response, "notional_cost_usd", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            pass

    @staticmethod
    def _llm_identity(llm) -> tuple:
        return _llm_identity_of(llm)

    def _is_independent_of(self, llm, *others) -> bool:
        if llm is None:
            return False
        identity = self._llm_identity(llm)
        return all(
            other is None or self._llm_identity(other) != identity for other in others
        )

    @staticmethod
    def _health_domain(llm) -> tuple:
        """What fails together.

        Deliberately coarser than _llm_identity: providers die by ACCOUNT, not by
        model name. deepseek-v4-pro and deepseek-v4-flash are two identities and
        ONE balance, ONE key, ONE outage — calling that pair a fallback for each
        other is calling a system resilient because it can fail twice. Identity
        answers "is this a second opinion"; health answers "is this the same thing
        that just went down".
        """
        provider = getattr(llm, "_provider", None) or getattr(llm, "provider", None)
        if provider:
            return ("provider", str(provider))
        return ("object", id(llm))

    def _route(self, primary, fallback):
        """Send a call to a configured fallback when the primary's account is dead."""
        if primary is not None and self._health_domain(primary) in self._unhealthy_domains:
            if (
                fallback is not None
                and self._health_domain(fallback) not in self._unhealthy_domains
            ):
                return fallback
        return primary

    def _routed_judge(self, primary, fallback, stage: str) -> tuple[object, str]:
        """Pick the live client for a judge stage, name the counter, and remember
        WHO actually judged.

        The identity matters later: the release challenger must be independent of
        the judges that really approved this compilation, which on a fallback path
        are not the ones the wiring nominated. A Sonnet challenger reviewing a
        Sonnet fallback judge is the same reader twice, however the variables were
        named.
        """
        routed = self._route(primary, fallback)
        if routed is not None:
            self._judge_identities_used.add(self._llm_identity(routed))
        return routed, (stage if routed is primary else f"{stage}_escalation")

    def _mandatory_post_writer_path(self) -> dict[str, tuple]:
        """Every judge that MUST answer after the writer is paid, and its fallback."""
        return {
            "critic_score": (self.critic_llm, self.critic_fallback_llm),
            "final_editor": (self.critic_llm, self.critic_fallback_llm),
            "story_compliance": (self.compliance_llm, self.compliance_escalation_llm),
        }

    def _assert_post_writer_path_healthy(
        self,
        audit: PlanAuditResult,
        *,
        rejections: list[PlanRejection] | None = None,
        plan: CompilationPlan | None = None,
    ) -> None:
        """Refuse to draft when the judges of the draft are already known-dead.

        The plan audit is the only pre-writer call that touches the critic's
        provider, which makes it the run's live health probe. On 2026-07-17 13:34
        all ten primary audits failed and Claude escalation answered every one, so
        the audit looked fine — had any plan passed, the run would have bought
        three Opus drafts and only then found the DeepSeek scorer, compliance
        auditor and final editor unreachable. That is the 08:36 failure again, paid
        for twice.
        """
        if audit.primary_healthy:
            return
        self._unhealthy_domains.add(self._health_domain(self.critic_llm))
        stranded: list[str] = []
        for stage, (primary, fallback) in self._mandatory_post_writer_path().items():
            if primary is None:
                stranded.append(f"{stage} (not configured)")
                continue
            if self._health_domain(primary) not in self._unhealthy_domains:
                continue
            if (
                fallback is not None
                and self._health_domain(fallback) not in self._unhealthy_domains
            ):
                continue  # a genuinely independent fallback can take this call
            stranded.append(
                f"{stage} (on failed {self._health_domain(primary)[1]}, no independent "
                "fallback configured)"
            )
        if stranded:
            raise QualityPathUnhealthy(
                "The plan auditor's primary provider failed every attempt this run ("
                + "; ".join(audit.primary_provider_errors)[:300]
                + f"), and it is the same provider account as: {', '.join(stranded)}. "
                "Escalation rescued the plan verdict, but it cannot rescue the judges "
                "that must score, compliance-check and final-review the prose. "
                "Refusing to buy drafts nothing healthy can release.",
                audit,
                rejections,
                plan,
            )

    def _preflight_quality_path(self, strategy: NamedChannelStrategy) -> None:
        """Fail before the writer when the gates that judge its output cannot run.

        Story drafting is the expensive call. Discovering after three full drafts
        that the channel requires an adversarial challenger nobody configured means
        paying for prose that can never be released. The live critic path is probed
        separately and for free by the plan audit, which is a real paid call to the
        critic provider that happens before any writer call — a 402 surfaces there.
        """
        missing: list[str] = []
        if self.compliance_llm is None:
            missing.append("compliance_llm")
        if strategy.release_challenger_required:
            if self.release_challenger_llm is None:
                missing.append("release_challenger")
            elif not self._is_independent_of(self.release_challenger_llm, self.critic_llm):
                # Knowable now, so it costs nothing to catch now. A challenger on
                # the critic's own provider can never approve a release, so drafting
                # against it would buy prose that is unreleasable by construction.
                missing.append(
                    "release_challenger that is provider-independent of critic_llm "
                    f"(both resolve to {self._llm_identity(self.critic_llm)!r})"
                )
        if missing:
            raise QualityPathUnavailable(
                f"channel strategy {strategy.strategy_id} requires a quality path that is "
                f"not configured: {'; '.join(missing)}. Refusing to draft stories that "
                "could never pass their own release gates."
            )

    async def _salvage_single_patch(
        self,
        plan: CompilationPlan,
        stories: list[StoryDraft],
        candidate_list: list[StoryDraft],
        changed_ids: set[str],
        score: NarrativeScorecard,
        gate: GateReport,
        strategy: NamedChannelStrategy,
        compliance_reviews: dict[str, StoryComplianceReview],
    ):
        """Bounded rescue when a multi-story repair wave is rejected whole.

        Stacks patches back one story at a time, heaviest blocker first
        (critical > continuity major > style major > gate failures), each round
        re-auditing that one story and re-scoring once against the last
        ACCEPTED state. Two rounds max: the original single-slot rescue saved
        one good patch and threw the other away (live 2026-07-20 courier 0719:
        a rejected wave held TWO clean patches; the discarded one's banned
        phrase stood and the build died at 82/84). A rejected round is skipped,
        not fatal — the next round tries on the previous accepted base.
        Returns (stories, gate, score, reviews) after ≥1 monotonic win, else
        None. Never runs for single-story waves — nothing to disentangle."""
        if len(changed_ids) < 2:
            return None
        self._record_call("repair_salvage")

        def _weight(sid: str) -> int:
            weight = 0
            for issue in score.story_issues:
                if issue.story_id != sid:
                    continue
                if issue.severity == "critical":
                    weight += 100
                elif issue.severity == "major":
                    weight += 40 if issue.issue_kind in ("contradiction", "omission") else 20
            weight += sum(10 for f in gate.failures if sid in f.story_ids)
            return weight

        ranked = sorted(changed_ids, key=lambda sid: (-_weight(sid), sid))[:2]
        patched = {item.story_id: item for item in candidate_list}
        accepted = list(stories)
        accepted_gate, accepted_score = gate, score
        accepted_reviews = compliance_reviews
        won = False
        for target in ranked:
            trial = [
                patched[item.story_id] if item.story_id == target else item
                for item in accepted
            ]
            if not self._stories_changed(accepted, trial):
                continue
            trial_gate = gate_compilation(plan, trial, strategy)
            trial_reviews, trial_valid = await self._audit_stories(
                plan, trial, strategy, only_ids={target}, prior=accepted_reviews,
            )
            if not trial_valid:
                continue
            trial_score, score_valid, _ = await self._score_validated(
                plan, trial, trial_gate, strategy, compliance_reviews=trial_reviews,
            )
            trial_score = self._with_compliance_issues(trial_score, trial_reviews)
            if not score_valid or not self._repair_is_monotonic(
                accepted_score, accepted_gate, trial_score, trial_gate, strategy
            ):
                continue
            accepted, accepted_gate, accepted_score = trial, trial_gate, trial_score
            accepted_reviews = trial_reviews
            won = True
        if not won:
            return None
        return accepted, accepted_gate, accepted_score, accepted_reviews

    @staticmethod
    def _stories_changed(before: list[StoryDraft], after: list[StoryDraft]) -> bool:
        return locked_voiceover_sha256(before) != locked_voiceover_sha256(after)

    @staticmethod
    def _repair_is_monotonic(
        current: NarrativeScorecard, current_gate: GateReport,
        candidate: NarrativeScorecard, candidate_gate: GateReport,
        strategy: NamedChannelStrategy,
    ) -> bool:
        """Priority-ordered repair acceptance.

        External review 2026-07-20 (two independent reviewers converged):
        comparing raw per-dimension scores between two independent judge
        passes is stricter than the instrument's precision — a patch that
        removed a banned phrase AND resolved its major was rolled back because
        originality read 8 on one pass and 7 on the next. And counting a
        higher total as "progress" let judge noise buy repair waves that never
        touched the blocker the wave was sent to fix. Rules, in order:

        1. Nothing NEW appears: gate failures, criticals, and majors may not
           increase (criticals counted in BOTH shapes — free-text and
           structured story issues).
        2. Real progress on what the wave was sent to fix: gate failures or
           critical+major blockers strictly decrease. Only when nothing was
           blocked at all (the near-miss minor wave) does a higher total count
           as progress instead.
        3. Dimension floors hold, with a one-point judge-noise band: a
           dimension at/above its floor may not dip below it, one already
           below may not sink further, and none may drop more than 1 point.
        4. The total may drift within the same band (>= current - 1)."""
        cur_gates = len(current_gate.failures)
        cand_gates = len(candidate_gate.failures)
        if cand_gates > cur_gates:
            return False

        def _criticals(score: NarrativeScorecard) -> int:
            return len(score.critical_issues) + sum(
                item.severity == "critical" for item in score.story_issues
            )

        def _majors(score: NarrativeScorecard) -> int:
            return sum(item.severity == "major" for item in score.story_issues)

        cur_crit, cand_crit = _criticals(current), _criticals(candidate)
        cur_major, cand_major = _majors(current), _majors(candidate)
        if cand_crit > cur_crit or cand_major > cur_major:
            return False

        if cur_gates + cur_crit + cur_major:
            progress = (
                cand_gates < cur_gates
                or (cand_crit + cand_major) < (cur_crit + cur_major)
            )
        else:
            progress = candidate.total_score > current.total_score
        if not progress:
            return False

        for dim_field, min_field in _RELEASE_DIMENSION_FLOORS:
            cur_value = getattr(current, dim_field)
            cand_value = getattr(candidate, dim_field)
            floor = getattr(strategy, min_field)
            if cand_value < cur_value - 1:
                return False
            if cur_value >= floor and cand_value < floor:
                return False
            if cur_value < floor and cand_value < cur_value:
                return False
        return candidate.total_score >= current.total_score - 1
