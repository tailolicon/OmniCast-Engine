"""First-person true-horror rubric (Mr. Nightmare / r/LetsNotMeet register).

Own dimension set (NOT the explainer's number-hook / CTA / insider-data value
system). Script quality is judged on CONTINUITY, VOICE, FEAR, VARIETY, ORIGINALITY
— the things that actually decide whether a "true scary story" lands. Production
(visuals, sfx) is scored separately and does NOT inflate the story score.

Weights keep the pipeline-wide 70 (voiceover) / 30 (production) split so the
approval + routing math in CriticAgent/steps.py is unchanged.
"""

# ── Script dimensions (sum = 70) ──────────────────────────────────────────────
VO_DIMS: dict[str, int] = {
    "continuity":         20,   # logical consistency — the #1 believability killer
    "authentic_voice":    18,   # raw first-person, distinct per narrator, not literary
    "fear_immersion":     12,   # actual dread / slow-burn / a threat that acts
    "structural_variety": 12,   # the stories differ in shape/threat/pacing/ending
    "originality":         8,   # free of AI-slop tells and banned motifs
}
# ── Production dimensions (sum = 30) — a SEPARATE score, never added to the story ──
PROD_DIMS: dict[str, int] = {
    "visual_concreteness": 25,
    "sfx_appropriateness":  5,
}

VO_PASS = 53    # 75% of 70
PROD_PASS = 23  # 75% of 30

# A deterministic machine flag caps THIS dimension (enforced in Python).
slop_cap_dims: dict[str, str] = {
    "anti_ai_cliche": "originality",       # motif/phrase tells → originality
    "retention_structure": "structural_variety",
    "niche_compliance": "originality",     # in-character CTA / meta-framing
}


def dimension_rubric() -> str:
    """The per-dimension scoring bands injected into the critic prompt. NO explainer
    concepts (no 'specific number + pain' hook, no CTA, no insider data, no
    SFX-required) — those are wrong for this genre and were the source of the
    conflicting-rubric bug."""
    return f"""═══ SCORE ON 5 STORY DIMENSIONS ({sum(VO_DIMS.values())}pts) + 2 PRODUCTION DIMENSIONS ({sum(PROD_DIMS.values())}pts) ═══
Return one CriticDimension per name below (use these EXACT names and max_score).

── STORY (voiceover group, {sum(VO_DIMS.values())}pts) ──
1. continuity (max {VO_DIMS['continuity']}) — LOGICAL CONSISTENCY. Build a table of the hook's promises,
   the timeline (dates/nights/seasons), places, jobs, named props. ANY contradiction
   (hook vs body, inconsistent timeline, a promised payoff that never lands, a prop
   introduced then dropped, a distance/number that changes) = a hole that shatters the
   "true story" illusion. List each in the `continuity_issues` field.
   {VO_DIMS['continuity']}: airtight. 10-15: one small slip. 0-9: a real contradiction (also hard-caps total ≤65).
2. authentic_voice (max {VO_DIMS['authentic_voice']}) — a REAL person talking, not a novelist. RAW,
   conversational, short sentences under stress; messy real memory; the THREE narrators
   sound like DIFFERENT people (age/region/speech). Deduct hard for polished lyrical
   prose, identical voices across stories, or metaphors a scared person wouldn't say.
3. fear_immersion (max {VO_DIMS['fear_immersion']}) — does it actually unsettle? Slow-burn dread, fear shown
   through the BODY, a threat with real stakes that ACTS. Deduct for a passive narrator
   who just waits, or a threat that only stands and stares.
4. structural_variety (max {VO_DIMS['structural_variety']}) — the stories must NOT be three variations of one
   template (isolated night job → old prop → recurring phenomenon → self-reassurance →
   still figure → coda). Different shape, threat type, pacing, and ending each. Fill
   `story_shapes` with each story's ending shape. ≥2 stories sharing the skeleton → ≤ half.
5. originality (max {VO_DIMS['originality']}) — free of AI-slop: no "I told myself" repetition, no
   "tall/standing perfectly still", no rule-of-three, no "night one/two/three", no
   in-character CTA, no reused names/props across stories.

── PRODUCTION (separate group, {sum(PROD_DIMS.values())}pts — does NOT count toward story quality) ──
6. visual_concreteness (max {PROD_DIMS['visual_concreteness']}) — each scene has a concrete, filmable real-world
   visual (a place/object), not an abstraction or a chart.
7. sfx_appropriateness (max {PROD_DIMS['sfx_appropriateness']}) — SILENCE IS CORRECT here. Award full marks if
   SFX is absent/minimal by design; never penalise the absence of sound effects.

DO NOT PENALISE the absence of: statistics, citations, charts, a proof source, a
mid-video hook number, or a call-to-action — all BANNED in this format."""


def json_template() -> str:
    """Required-JSON block for the narrative dimension set (names must match VO_DIMS/PROD_DIMS)."""
    vo = "".join(
        f'\n    {{"name": "{n}", "score": <0-{m}>, "max_score": {m}, "feedback": "<max 25 words>"}},'
        for n, m in VO_DIMS.items())
    prod = "".join(
        f'\n    {{"name": "{n}", "score": <0-{m}>, "max_score": {m}, "feedback": "<max 25 words>"}},'
        for n, m in PROD_DIMS.items())
    prod = prod.rstrip(",")
    return (
        "═══ REQUIRED JSON OUTPUT ═══\n"
        "{\n"
        f'  "total_score": <sum of all 7 dimension scores>,\n'
        f'  "voiceover_score": <sum of the 5 STORY dimensions, max {sum(VO_DIMS.values())}>,\n'
        f'  "production_score": <sum of the 2 PRODUCTION dimensions, max {sum(PROD_DIMS.values())}>,\n'
        '  "approved": false,\n'
        '  "continuity_issues": ["<each hook/timeline/prop contradiction, or empty>"],\n'
        '  "story_shapes": ["<ending shape of story 1>", "<story 2>", "<story 3>"],\n'
        '  "dimensions": [' + vo + prod + "\n  ],\n"
        '  "rejection_reasons": ["<story issues — sent to Writer>"],\n'
        '  "specific_fixes": ["<specific fix 1>", "<specific fix 2>"],\n'
        '  "visual_fixes": ["<specific visual fix>"]\n'
        "}"
    )
