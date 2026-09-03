"""Immutable, named quality strategies for narrative script generation.

Channel configuration stores only a stable ``script_profile`` identifier.  The
registry owns the bounded prompt contract and quality floors, preventing a
misspelled or permissive channel JSON value from silently weakening release gates.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


SYSTEM_EDITORIAL_FLOOR = 82
SYSTEM_CONTINUITY_FLOOR = 22
SYSTEM_DIMENSION_FLOOR_RATIO = 0.60
SYSTEM_MIN_HUMAN_THREAT_FRACTION = 2 / 3
SYSTEM_MAX_EVIDENCE_BEATS_PER_STORY = 1
SYSTEM_MIN_EVIDENCE_FREE_STORIES = 1
SYSTEM_MAX_NUMERIC_ANCHORS = 6
SYSTEM_MAX_PRECISE_CLOCK_TIMES = 4
SYSTEM_MAX_PLAN_ATTEMPTS = 3
SYSTEM_MAX_PLAN_REPAIRS = 2

MAX_PROFILE_PROMPT_CHARS = 5_000
RuleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]


class NarrativeQualityStrategy(BaseModel):
    """A frozen creative contract that may only equal or strengthen hard minima."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=3,
            max_length=64,
            pattern=r"^[a-z][a-z0-9_]*$",
        ),
    ]
    strategy: Literal["first_person_true_horror_compilation"]
    channel_promise: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=600),
    ]

    editorial_floor: int = Field(default=SYSTEM_EDITORIAL_FLOOR, ge=SYSTEM_EDITORIAL_FLOOR, le=100)
    continuity_floor: int = Field(
        default=SYSTEM_CONTINUITY_FLOOR,
        ge=SYSTEM_CONTINUITY_FLOOR,
        le=25,
    )
    dimension_floor_ratio: float = Field(
        default=SYSTEM_DIMENSION_FLOOR_RATIO,
        ge=SYSTEM_DIMENSION_FLOOR_RATIO,
        le=1.0,
    )
    minimum_human_threat_fraction: float = Field(
        default=SYSTEM_MIN_HUMAN_THREAT_FRACTION,
        ge=SYSTEM_MIN_HUMAN_THREAT_FRACTION,
        le=1.0,
    )
    maximum_evidence_beats_per_story: int = Field(
        default=SYSTEM_MAX_EVIDENCE_BEATS_PER_STORY,
        ge=0,
        le=SYSTEM_MAX_EVIDENCE_BEATS_PER_STORY,
    )
    minimum_evidence_free_stories: int = Field(
        default=SYSTEM_MIN_EVIDENCE_FREE_STORIES,
        ge=SYSTEM_MIN_EVIDENCE_FREE_STORIES,
        le=5,
    )
    maximum_numeric_anchors: int = Field(
        default=SYSTEM_MAX_NUMERIC_ANCHORS,
        ge=0,
        le=SYSTEM_MAX_NUMERIC_ANCHORS,
    )
    maximum_precise_clock_times: int = Field(
        default=SYSTEM_MAX_PRECISE_CLOCK_TIMES,
        ge=0,
        le=SYSTEM_MAX_PRECISE_CLOCK_TIMES,
    )
    maximum_plan_attempts: int = Field(default=SYSTEM_MAX_PLAN_ATTEMPTS, ge=2, le=4)
    # Bounded targeted repair of blocked stories, so one bad story does not
    # throw away two good ones. 0 disables repair and always re-plans.
    maximum_plan_repairs: int = Field(default=SYSTEM_MAX_PLAN_REPAIRS, ge=0, le=3)
    patch_candidate_count: Literal[2] = 2
    final_compilation_editor_required: Literal[True] = True

    # Layered release gates. These read typed plan data, so a channel that has not
    # opted in keeps the generic engine behaviour rather than inheriting another
    # channel's editorial policy. A profile may only turn a gate ON.
    require_distinct_mechanisms: bool = True
    topic_alignment_gate: bool = False
    safety_response_gate: bool = False
    plan_fact_fidelity_gate: bool = False
    forbidden_ending_gate: bool = False
    release_challenger_required: bool = False
    promote_impossibility_to_major: bool = True
    stylometric_texture_gate: bool = False
    # Measure the finished compilation against THIS channel's competitor corpus
    # (omnicast.analytics.skeleton.SKELETON_BOUNDS). Empty = not gated, because
    # borrowing another niche's numbers is worse than having none: retirement
    # explainers and first-person horror want opposite things on the same
    # metrics. Every other gate here is self-referential â€” this is the only one
    # that checks the script against scripts nobody on this team wrote.
    skeleton_bounds_channel: str = ""
    # Requires every story to name, at plan time, what makes its premise unlike
    # the genre default. Originality is scored holistically and cannot be
    # repaired downstream, so it is contracted before prose exists.
    premise_freshness_gate: bool = False

    # A pre-return checklist the PLANNER runs on its own draft, inside the same
    # call. Not another paid judge: the auditor already exists and is the reader
    # this is trying to survive. Profile-scoped, so a channel that has not opted in
    # keeps the generic planning contract.
    plan_self_audit_rules: tuple[RuleText, ...] = Field(default=(), max_length=10)
    planning_rules: tuple[RuleText, ...] = Field(min_length=1, max_length=10)
    voice_rules: tuple[RuleText, ...] = Field(min_length=1, max_length=10)
    dread_rules: tuple[RuleText, ...] = Field(min_length=1, max_length=10)
    ending_rules: tuple[RuleText, ...] = Field(min_length=1, max_length=10)
    avoid_tropes: tuple[RuleText, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _bound_total_prompt_text(self) -> "NarrativeQualityStrategy":
        values = (
            self.channel_promise,
            *self.plan_self_audit_rules,
            *self.planning_rules,
            *self.voice_rules,
            *self.dread_rules,
            *self.ending_rules,
            *self.avoid_tropes,
        )
        if sum(len(value) for value in values) > MAX_PROFILE_PROMPT_CHARS:
            raise ValueError(
                f"script profile prompt text exceeds {MAX_PROFILE_PROMPT_CHARS} characters"
            )
        return self


_TRUE_HORROR_STRICT_V1 = NarrativeQualityStrategy(
    profile_id="true_horror_strict_v1",
    strategy="first_person_true_horror_compilation",
    channel_promise=(
        "One person remembering what happened to them, in their own voice. Never "
        "claimed true, never winked at as invention. Fear from coherent danger "
        "and practical action."
    ),
    editorial_floor=84,
    # 23/25 sat inside the critic's own noise (six live scores: 23, 22, 22, 21,
    # 24, 22) and blocked an 89/100 account with no continuity issue filed.
    # Continuity has its own hard rule - no unresolved major contradiction -
    # so the score floor is the system minimum, not a coin flip above it.
    continuity_floor=22,
    dimension_floor_ratio=0.65,
    # Plan-stage budget, deliberately strict and deliberately visible here rather
    # than hidden in the coordinator. Live 2026-07-17 14:32 spent ~31 minutes and
    # never reached the writer: one plan, two local repairs and a fresh planner
    # loop all inside one outer attempt, each Sonnet call running 2-7 minutes.
    # A compilation that needs more than one targeted repair is not close; it is
    # cheaper and better to abandon the concept than to keep sanding it.
    # One initial plan + at most ONE targeted repair + one re-audit, then the
    # outer loop gets exactly one fresh concept.
    maximum_plan_attempts=2,
    # Two rounds: the first clears the objections it was given, the re-audit
    # may raise new ones on the repaired fields (run 15: escape fixed, then
    # knowledge path). One round threw the premise away at that point.
    # Three, each gated on the previous round clearing every objection it was
    # given (run 15: escape fixed, then response fixed, then one knowledge-path
    # line left). A re-roll of the same objection still abandons.
    maximum_plan_repairs=3,
    topic_alignment_gate=True,
    safety_response_gate=True,
    plan_fact_fidelity_gate=True,
    forbidden_ending_gate=True,
    release_challenger_required=True,
    stylometric_texture_gate=True,
    premise_freshness_gate=True,
    skeleton_bounds_channel="true_dread_files_us",
    planning_rules=(
        # ORDER MATTERS, and it is why plan_audit/trope kept firing. Designing
        # threat-first lands in this genre's stock catalogue, which is small and
        # well known â€” lone driver flagged down at night, figure at the window.
        # The 147-script competitor corpus does the reverse: every top story
        # opens on why THIS person was in THIS place ("way before I met my wife",
        # "burnt out from work", "I hated my dad growing up"), and the threat
        # arrives into a life already specified. A life cannot be stock.
        "Build each story from why THIS person was there, then the threat; keep "
        "life, geometry, threat and ending distinct across stories.",
        "Vary the FIRST sensory channel through which danger announces itself across "
        "the compilation â€” sound out of place, wrongness in plain sight, a noticed "
        "absence, changed air or temperature, or a broken pattern in routine data.",
        "Write each story's first-contact channel into its threat description. "
        "Sound-first in at most one story per compilation: three stories that all "
        "open danger through the ears are one sensory template worn three ways.",
        "Lock timeline, people and object counts, exits, props, threat position, "
        "response, and escape.",
        "Use human danger in at least two thirds of stories; keep any anomaly under-confirmed.",
        "Every story must concretely deliver the compilation topic's subject, not a "
        "neighbouring errand that merely rhymes with it.",
        "A minor facing a human threat contacts police or a responsible adult afterwards "
        "unless the plan states a concrete reason they cannot.",
    ),
    # Every rule below is a defect the auditor ALREADY caught on 2026-07-17 16:03,
    # after the plan was written and paid for. Moving the check into the planner's
    # own pass is free; letting the auditor find it costs a replan.
    plan_self_audit_rules=(
        "Trade reality: does the narrator's own job give them keys, tools, "
        "diagnostics, authority or an exit that dissolves this threat? If yes, the "
        "premise is broken â€” a locksmith is not trapped by a lock they just keyed.",
        "Egress: commercial and public buildings have code-required free interior "
        "exit hardware. A character is only trapped if the plan stages a concrete "
        "reason that specific exit is unusable.",
        "Staged mechanism: every door that closes, latches or opens has a physical "
        "cause named in the plan (closer, draft, slope, hand). Nothing moves because "
        "the story needs it to.",
        "Repeated threat: if a human threat recurs across nights or visits, each "
        "repeat forces a proportionate adaptation (report, partner, escort, daylight, "
        "refusal) or the plan states a concrete reason the person cannot adapt.",
        "Response immediacy: an in-progress threat gets emergency services; a cold "
        "aftermath gets a non-emergency line. Never a routine call while something "
        "is at the glass.",
        "Consistency: safety_obligation, escape_action, ending_shape and "
        "aftermath_mechanism must describe the same events. Do not promise a told "
        "adult and then end on told_no_one.",
        "Trade logic over haunted-house mechanics: the dread comes from what this "
        "occupation knows and cannot explain, not from doors that shut themselves.",
        "topic_promise must contain the compilation's exact subject wording AND the "
        "concrete site. It is an internal gate string, not prose.",
    ),
    voice_rules=(
        "Use plain spoken English with different sentence rhythm, vocabulary, and "
        "dialogue habits per narrator.",
        "Keep dialogue incidental and imperfect rather than cinematic or explanatory.",
        "When the narrator would, state feelings directly in that narrator's own "
        "register instead of engineering bodily show-don't-tell. At most two physical "
        "fear reactions per story, never from stock phrasing.",
        "Vary paragraph length hard â€” some one sentence, some six or seven; not every "
        "concrete detail must pay off, and up to one detail per story may simply be "
        "remembered and never explained. Real memory keeps useless things.",
        # Measured across 147 competitor scripts: median sentence 13 words, the
        # whole distribution 10-15. Our first build ran 24 and read as an essay.
        # The other two measured misses â€” no short-sentence bursts, no concrete
        # anchor in the opening â€” are NOT stated here: this profile was already at
        # 4,883 of its 5,000-character budget, and that budget is a discipline
        # against prompt bloat, not an obstacle to route around. Those two are
        # localized fixes a repair wave handles well, and the skeleton gate names
        # them precisely when they are breached. Sentence length is the one that
        # cannot be patched locally, so it is the one that earns the space.
        "Sentences a person says aloud: about 13 words. Two ideas means two sentences.",
    ),
    dread_rules=(
        "Begin with an ordinary routine, then escalate through readable sensory and "
        "spatial changes.",
        # Measured: the genre's first number lands 1% into the script â€” an age,
        # a year, an hour. Dropping this rule to fit the prompt budget produced
        # a 4,435-word draft containing no number at all.
        "Open on an age, a year, or an hour.",
        "The protagonist must notice, choose, act, and adapt under pressure.",
        "Preserve the narrator's strongest concrete response â€” flight, fight, or a "
        "deliberate choice under pressure; never passive waiting with no decision.",
        "The FIRST escalation milestone arrives through whichever sensory channel the "
        "plan's threat implies â€” a sound out of place, a wrongness in plain sight, an "
        "absence, changed air or temperature, or a broken pattern in routine data.",
        "React to the first wrong signal before understanding it. Sound-first is one "
        "option, not a requirement.",
        "Render a human threat only through what the narrator could observe at that "
        "distance and light â€” no interiority, no motive; leave one question about "
        "them permanently unanswered.",
        "Spend specificity on the narrator's own world â€” routine, layout, schedule; "
        "keep the threat at low resolution.",
        # REWRITTEN 2026-08-03 after two consecutive runs on two different
        # topics both died at plan_audit/human_behavior, both on story_1, both
        # with the same complaint: "a reasonable person would not wait". The
        # old wording told the planner to delay recognition through
        # "observation, checking, hesitation" â€” and the auditor's own contract
        # says "no one preserves mystery over safety". The planner was obeying
        # this rule and being punished for it. Neither side was wrong about
        # craft; the rule was wrong about WHERE the delay comes from. In a real
        # account nobody is slow â€” the situation simply has not declared itself
        # yet.
        "Delay recognition by keeping the SIGNAL ambiguous, never by slowing the "
        "narrator. Once a signal is unmistakable they act at once.",
    ),
    ending_rules=(
        "Complete the promised escape or response, then end within two beats of the "
        "strongest image or action.",
        "Vary ending mechanisms; avoid proof that neatly explains or validates the threat.",
    ),
    avoid_tropes=(
        "stock self-reassurance such as I told myself or I figured it was just",
        "camera static, vanished footprints, stacked police or witness confirmation",
        "arbitrary exact numbers used as fake authenticity",
        "trailer prose, decorative gore, omniscient knowledge, and host or channel framing",
        "a bare closing declaration that the narrator never returned; a permanently "
        "changed routine must be shown as one concrete ongoing behavior (parks somewhere "
        "else, double-checks one lock), never announced as a claim",
    ),
)


SCRIPT_PROFILE_REGISTRY = MappingProxyType(
    {_TRUE_HORROR_STRICT_V1.profile_id: _TRUE_HORROR_STRICT_V1}
)


def available_script_profiles() -> tuple[str, ...]:
    """Return stable profile IDs without exposing mutable registry state."""

    return tuple(sorted(SCRIPT_PROFILE_REGISTRY))


def resolve_script_profile(profile_id: str) -> NarrativeQualityStrategy:
    """Resolve a known profile as a fresh, deeply copied frozen value."""

    key = (profile_id or "").strip()
    try:
        template = SCRIPT_PROFILE_REGISTRY[key]
    except KeyError as exc:
        known = ", ".join(available_script_profiles()) or "none"
        raise ValueError(f"Unknown script_profile {profile_id!r}; available: {known}") from exc
    return template.model_copy(deep=True)


__all__ = [
    "NarrativeQualityStrategy",
    "SCRIPT_PROFILE_REGISTRY",
    "available_script_profiles",
    "resolve_script_profile",
]
