"""Senior-finance explainer rubric (The Retirement Desk register).

Value system for a YMYL retirement-finance channel aimed at 60-75 US viewers.
Judged on ACCURACY/TRUST first — every number sourced and dated — then CLARITY
for an audience that hates being patronized, then the retention craft the
competitor cohort validated (concrete-number hooks, news+deadline framing).

Evidence base: the 2026-07-26 competitor dossier
(docs/FLAGSHIP_CompetitorDossier_SeniorFinance.md) — 12 winner / 7 control
cohort. Key findings encoded here:
  * authority comes from the CITED SOURCE (SSA/IRS/FBI/Vanguard), never from a
    host persona — "I'm a retirement advisor" framing is the one winner pattern
    this channel is BANNED from copying (AI-expert persona ban, YMYL);
  * winners speak ~180 wpm in short plain sentences — no slowed "elderly" voice;
  * spoken source attribution ("according to the FBI's 2025 report") is a TRUST
    feature in this niche, not an AI-tell — the explainer rubric's
    read-citation-aloud flag does not apply here.

Weights keep the pipeline-wide 70 (voiceover) / 30 (production) split so the
approval + routing math in CriticAgent/steps.py is unchanged.
"""

from __future__ import annotations

import re

RUBRIC_ID = "finance_explainer_v1"

# ── Script dimensions (sum = 70) ──────────────────────────────────────────────
VO_DIMS: dict[str, int] = {
    "accuracy_trust":      16,  # sourced+dated numbers, no invented figures, consistent math
    "clarity_65plus":      12,  # plain English, one idea per sentence, jargon defined on first use
    "hook_quality":        10,  # concrete consequence + real number in the first 15 seconds
    "retention_structure": 10,  # open loops, chapters, promises paid off
    "actionability":        8,  # a step the viewer can take this week, stated as education
    "anti_ai_cliche":       6,  # no "delve/tapestry/in conclusion", no corporate filler
    "niche_compliance":     5,  # finance fatal rules (guarantees, predictions, persona)
    "pacing_compliance":    3,  # scene word caps + prosody discipline
}
# ── Production dimensions (sum = 30) ──────────────────────────────────────────
PROD_DIMS: dict[str, int] = {
    "visual_concreteness": 20,  # filmable, specific — documents, forms, real objects
    "data_visualization":  10,  # key numbers get a chart/on-screen source, never an AI-drawn graph
}

VO_PASS = 53    # 75% of 70
PROD_PASS = 23  # 75% of 30

# A deterministic machine flag caps THIS dimension (enforced in Python).
slop_cap_dims: dict[str, str] = {
    "expert_persona": "accuracy_trust",
    "guarantee_language": "niche_compliance",
    "personalized_advice": "niche_compliance",
    "anti_ai_cliche": "anti_ai_cliche",
}

# The persona ban is absolute for this channel: the narrator may EXPLAIN what
# official sources say, but may never claim to BE an advisor/CPA/planner or to
# have clients. (YMYL + synthetic-voice channel — an AI claiming professional
# credentials is the exact pattern YouTube's 2026 inauthentic-content policy
# and our own charter prohibit.)
_CREDENTIALS = (
    r"(?:financial advisor|retirement advisor|financial planner|"
    r"certified financial planner|cfp|cpa|fiduciary|tax professional|"
    r"tax advisor|accountant|wealth manager|retirement specialist)")

_PERSONA_RE = re.compile(
    # "as a CPA, I…" — but NOT the hypothetical "as a CPA would tell you"
    r"\b(?:as an?|i'?m an?|i am an?|speaking as an?|i'?m your|i am your)\s+"
    + _CREDENTIALS + r"(?!\s+(?:would|might|could|will|can)\b)"
    r"|\bmy clients?\b|\bclients? of mine\b|\bour clients?\b|\bin my practice\b"
    r"|\bi'?ve advised\b|\bi have advised\b"
    r"|\bi advise (?:retirees|clients|people)\b",
    re.IGNORECASE)

_GUARANTEE_RE = re.compile(
    r"\bguaranteed?\s+(?:returns?|profits?|income|growth|gains?)\b"
    # "guaranteed 8% returns" / "I guarantee an 8% return" — a number between
    # the promise and the noun must not be an escape hatch (codex finding 8).
    r"|\bguaranteed?\s+(?:an?\s+)?\d[\d.,]*\s?%(?:\s*(?:returns?|profits?|yield|gains?|growth))?"
    r"|\bi guarantee\b|\brisk[- ]free\b|\bcan(?:'|no)?t lose\b"
    r"|\byou (?:will|'ll) (?:definitely|certainly|surely)\b",
    re.IGNORECASE)

# Direct second-person financial instruction = personalized advice. Education
# frames the same content as "for this example retiree…" / "the rule says…".
# "Whether/if you should claim…" is a legitimate educational frame, excluded
# via fixed-width lookbehinds.
_ADVICE_RE = re.compile(
    r"(?<!whether )(?<!if )\byou (?:should|need to|have to|must) "
    r"(?:buy|sell|invest in|withdraw|claim (?:at|your|now)|"
    r"move your money|roll over|convert|cash out)\b"
    r"|\bi recommend (?:you|buying|selling|claiming)\b",
    re.IGNORECASE)

_URGENCY_RE = re.compile(
    r"\bact now\b|\bbefore it'?s too late\b|\btime is running out\b",
    re.IGNORECASE)

# Autopsy v1 (gen 20260727_0036, 76/100) — three machine-detectable tells that
# survived the LLM critic and must never survive again:
#   greeting opener; "according to X" as a verbal tic; the "nobody tells you"
#   scaffold repeated as filler authority.
_GREETING_OPEN_RE = re.compile(
    r"^\s*(?:hey there|hey|hi there|hi|hello|welcome back|welcome|greetings)\b",
    re.IGNORECASE)
_ATTRIBUTION_TIC_RE = re.compile(r"\baccording to (?:the )?", re.IGNORECASE)
_NOBODY_SCAFFOLD_RE = re.compile(
    r"\b(?:almost )?nobody (?:explains|mentions|talks about|tells you)\b"
    r"|\balmost no one\b|\bthe part almost everyone misses\b"
    r"|\brarely makes it into\b|\bwhat they don'?t tell you\b",
    re.IGNORECASE)
MAX_ATTRIBUTION_TICS = 4
MAX_NOBODY_SCAFFOLDS = 1
# Autopsy v2: "I've read SSA's community forums — this is a top complaint" —
# an unverifiable anecdote dressed as evidence. Reading the RULES is the
# channel's premise; citing forums/comments as data is not.
_ANECDOTE_EVIDENCE_RE = re.compile(
    r"\bi'?ve (?:read|seen|browsed)\b[^.]{0,50}\b(?:forums?|comment section|"
    r"comments|reddit|facebook)\b", re.IGNORECASE)


def fatal_caps(caps: dict[str, int]) -> bool:
    """Whether the deterministic caps constitute a FATAL violation.

    Codex audit finding 4: a cap alone still let a maximally-scored persona
    script pass (54/70 > 53). A fatal flag must force approved=False and a
    writer route — CriticAgent.execute calls this to do exactly that."""
    return (caps.get("niche_compliance", 99) <= 2
            or caps.get("accuracy_trust", 99) <= 4)


def finance_slop_signals(text: str) -> tuple[list[str], dict[str, int]]:
    """Deterministic YMYL scan. Returns (flag messages, dimension caps) — caps
    are HARD maxima enforced in CriticAgent.execute, not suggestions."""
    flags: list[str] = []
    caps: dict[str, int] = {}

    m = _PERSONA_RE.findall(text)
    if m:
        flags.append(
            f"AI-EXPERT PERSONA claim ({len(m)}x, e.g. \"{str(m[0])[:40]}\") — this channel "
            "is BANNED from claiming advisor/CPA credentials or clients; authority must "
            "come from cited sources (SSA/IRS/FBI), never from the narrator")
        caps["accuracy_trust"] = min(caps.get("accuracy_trust", 99), 4)
        caps["niche_compliance"] = min(caps.get("niche_compliance", 99), 1)
    if _GUARANTEE_RE.search(text):
        flags.append("guarantee language (guaranteed returns / risk-free / can't lose) — "
                     "finance fatal rule")
        caps["niche_compliance"] = 0
    if _ADVICE_RE.search(text):
        flags.append("personalized advice framing (\"you should buy/sell/claim…\") — must be "
                     "educational (\"for this example retiree…\" / \"the rule says…\")")
        caps["niche_compliance"] = min(caps.get("niche_compliance", 99), 2)
    if _URGENCY_RE.search(text):
        flags.append("scam-adjacent urgency (\"act now / before it's too late\") — this channel "
                     "teaches scam defense; it must never sound like one")
        caps["anti_ai_cliche"] = min(caps.get("anti_ai_cliche", 99), 3)
    if _GREETING_OPEN_RE.search(text):
        flags.append("greeting opener (\"Hey there / welcome\") — winners cold-open on the "
                     "subject; a greeting burns the most valuable 3 seconds of the video")
        caps["hook_quality"] = min(caps.get("hook_quality", 99), 4)
    tics = len(_ATTRIBUTION_TIC_RE.findall(text))
    if tics > MAX_ATTRIBUTION_TICS:
        flags.append(f"attribution tic: 'according to …' used {tics}x (max "
                     f"{MAX_ATTRIBUTION_TICS}) — vary the sourcing language "
                     "(named document, 'SSA's published figures', 'the rule says') "
                     "and vary its position in the sentence")
        caps["anti_ai_cliche"] = min(caps.get("anti_ai_cliche", 99), 3)
    # Autopsy v3: a long sentence repeated VERBATIM (copy-paste padding) —
    # the LLM reused a whole teaser line twice and the critic missed it.
    sentences = [s.strip().lower() for s in re.split(r"[.!?]\s+", text)
                 if len(s.split()) >= 9]
    seen: dict[str, int] = {}
    for s in sentences:
        key = re.sub(r"[^a-z0-9 ]", "", s)
        seen[key] = seen.get(key, 0) + 1
    dup = next((s for s, n in seen.items() if n >= 2), "")
    if dup:
        flags.append(f"verbatim self-duplication: a long sentence appears twice "
                     f"(\"{dup[:60]}…\") — copy-paste padding, cut one")
        caps["anti_ai_cliche"] = min(caps.get("anti_ai_cliche", 99), 3)
    if _ANECDOTE_EVIDENCE_RE.search(text):
        flags.append("unverifiable anecdote as evidence (\"I've read the forums…\") — "
                     "cite the document, not the comment section")
        caps["accuracy_trust"] = min(caps.get("accuracy_trust", 99), 12)
    scaffolds = len(_NOBODY_SCAFFOLD_RE.findall(text))
    if scaffolds > MAX_NOBODY_SCAFFOLDS:
        flags.append(f"'nobody tells you' scaffold used {scaffolds}x (max "
                     f"{MAX_NOBODY_SCAFFOLDS}) — manufactured-secret framing "
                     "repeated as filler is a signature AI tell")
        caps["anti_ai_cliche"] = min(caps.get("anti_ai_cliche", 99), 3)
    return flags, caps


def dimension_rubric() -> str:
    """Per-dimension scoring bands injected into the critic prompt."""
    return f"""═══ SCORE ON 8 VO DIMENSIONS ({sum(VO_DIMS.values())}pts) + 2 PRODUCTION DIMENSIONS ({sum(PROD_DIMS.values())}pts) ═══
Return one CriticDimension per name below (use these EXACT names and max_score).

── VO GROUP ({sum(VO_DIMS.values())}pts) ──
1. accuracy_trust (max {VO_DIMS['accuracy_trust']}) — THE dimension for this channel. Every dollar amount,
   percentage, threshold, age rule and deadline must carry an attributed source and a year
   ("according to SSA's 2026 fact sheet…"). Numbers must be internally consistent (the same
   figure never changes between scenes; any math shown must actually work). Deduct hard for:
   an uncited precise number, a source named without a year, figures that contradict each
   other, or hedged invented statistics ("some say", "experts estimate" with no source).
   {VO_DIMS['accuracy_trust']}: every claim sourced+dated, math airtight. 8-12: 1-2 uncited or undated numbers.
   0-7: any invented/contradictory figure.
2. clarity_65plus (max {VO_DIMS['clarity_65plus']}) — plain English for a smart 68-year-old who hates being
   patronized. One idea per sentence; every term of art (RMD, IRMAA, provisional income)
   defined in one plain clause on first use; concrete dollar examples over abstractions;
   NO baby-talk, NO "seniors like you". Deduct for jargon runs, nested conditionals,
   or a condescending register.
3. hook_quality (max {VO_DIMS['hook_quality']}) — winner pattern from the competitor cohort: one concrete
   consequence with a REAL number in the first 15 seconds ("Claiming at 62 instead of 67
   costs this retiree $612 every month, for life"). Deduct for vague dread, greeting
   openers, or a hook number that is not sourced later.
4. retention_structure (max {VO_DIMS['retention_structure']}) — open loops resolved on time, chaptered
   structure a viewer can rewatch one section of, hook promises paid off. Deduct −4 for a
   hook figure the body never explains; −3 for teasing content that never arrives.
5. actionability (max {VO_DIMS['actionability']}) — the viewer leaves with a concrete educational step
   ("the SSA calculator shows your exact number", "this IRS form, before this date"), never
   a personal directive. Full marks = a checklist-able takeaway per major section.
6. anti_ai_cliche (max {VO_DIMS['anti_ai_cliche']}) — zero "delve/tapestry/it's important to note/in
   conclusion", no corporate filler, no mechanical counting as the BODY's spine.
   EXEMPT: one numbered checklist in the CLOSING section is this channel's
   format (the tangible-utility pattern its winners share) — never penalise it.
7. niche_compliance (max {VO_DIMS['niche_compliance']}) — finance fatal rules (see FATAL RULES above):
   guarantees, price predictions, promised outcomes, uncited Social Security claims,
   advisor-persona claims → 0-2 per the rules.
8. pacing_compliance (max {VO_DIMS['pacing_compliance']}) — scene word caps + prosody targets
   (~180 wpm register: short sentences, normal adult pace — never slowed "for seniors").

── PRODUCTION GROUP ({sum(PROD_DIMS.values())}pts) ──
9. visual_concreteness (max {PROD_DIMS['visual_concreteness']}) — every scene names a filmable, specific
   visual: the actual form (SSA-44), a statement close-up, a dated letter. Deduct for
   "worried senior stock photo" placeholders.
10. data_visualization (max {PROD_DIMS['data_visualization']}) — every load-bearing number appears
   on screen with its source; comparisons call for a CHART visual. IMPORTANT: this
   channel has a REAL chart renderer (matplotlib, audited against the fact ledger) —
   a visual note naming a "chart" IS the correct, intended staging and must be
   REWARDED, not treated as an AI-image risk. Deduct only if key figures stay
   voice-only or comparisons never get staged as charts at all.

DO NOT PENALISE: spoken source attribution ("according to the FBI's 2025 IC3 report") —
in THIS niche naming the source aloud builds trust and is REQUIRED, not an AI-tell."""


def json_template() -> str:
    """Required-JSON block for the finance dimension set."""
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
        f'  "total_score": <sum of all 10 dimension scores>,\n'
        f'  "voiceover_score": <sum of the 8 VO dimensions, max {sum(VO_DIMS.values())}>,\n'
        f'  "production_score": <sum of the 2 PRODUCTION dimensions, max {sum(PROD_DIMS.values())}>,\n'
        '  "approved": false,\n'
        '  "dimensions": [' + vo + prod + "\n  ],\n"
        '  "rejection_reasons": ["<VO issues — sent to Writer>"],\n'
        '  "specific_fixes": ["<specific fix 1>", "<specific fix 2>"],\n'
        '  "visual_fixes": ["<specific visual fix>"]\n'
        "}"
    )
