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
    "spoken_presence":     10,  # WRITTEN TO BE SPOKEN by a person with a self (see below)
    "clarity_65plus":       9,  # plain English, one idea per sentence, jargon defined on first use
    "hook_quality":         9,  # concrete consequence + real number in the first 15 seconds
    "retention_structure":  9,  # open loops, chapters, promises paid off
    "actionability":        6,  # a step the viewer can take this week, stated as education
    "anti_ai_cliche":       4,  # no "delve/tapestry/in conclusion", no corporate filler
    "niche_compliance":     3,  # finance fatal rules (guarantees, predictions, persona)
    "editorial_courage":    4,  # THE REWARD LANE: contestable opinion + play (operator 2026-08-01)
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


# ── Spoken-presence detectors (operator review 27/07) ─────────────────────────
# The six mechanics that make a script sound like a person, learned from a
# NotebookLM-generated video the operator judged far more alive than our own
# accurate-but-voiceless build.
_COMPANION_RE = re.compile(
    r"\b(?:let'?s|we'?ll|we'?re|we've|we\s+(?:can|need|start|begin|walk|run|look|"
    r"come back|move|end)|together|our\s+(?:example|retiree|math|number))\b",
    re.IGNORECASE)
# The narrator responding to their own fact, not just asserting it.
_REACTION_RE = re.compile(
    r"\b(?:that'?s the part that|here'?s what (?:gets|bothers|surprised)|"
    r"i'?ll be honest|honestly|and yes|no really|that stopped me|"
    r"read that (?:again|twice)|sit with that|it'?s worth pausing|"
    r"annoys me|surprised me|shocked me|frustrating part|maddening|"
    r"strange thing is|odd part|worth saying out loud)\b"
    r"|\b(?:right\?|isn'?t it\?|doesn'?t it\?|sound familiar\?)",
    re.IGNORECASE)
_INVITATION_RE = re.compile(
    r"\b(?:picture|imagine|look at (?:this|that|these)|watch (?:this|what)|"
    r"try this|think about|walk through (?:this|it) with me|"
    r"pull up|grab (?:your|that)|check (?:your|that)|take a (?:second|look))\b",
    re.IGNORECASE)
# Real contractions only — a possessive ("SSA's fact sheet") is written
# register too, so it must not count as spoken.
_CONTRACTION_RE = re.compile(
    r"\b\w+n'?t\b"
    r"|\b(?:i|you|we|they|he|she|it|that|this|there|here|what|who|how|"
    r"let|who|where|when|one)'(?:s|re|ve|ll|d|m)\b",
    re.IGNORECASE)
_SIGNPOST_RE = re.compile(
    r"\b(?:that'?s the (?:history|mechanism|rule|first part|easy part)|"
    r"now (?:the|for|comes|let'?s)|next (?:up|comes|question)|"
    r"before we (?:get|move|go)|so far,? we|coming back to|"
    r"one more (?:thing|wrinkle|piece)|here'?s where we'?re going)\b",
    re.IGNORECASE)


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

    # A machine used to hard-cap ``spoken_presence`` from counts of "let's",
    # contractions, invitations and reaction phrases here. That was gameable:
    # a model could repeat the vocabulary and earn the shape without having a
    # thesis, counterpoint, or genuine response to a fact. Semantic editorial
    # presence belongs to the critic. Deterministic code keeps only a narrow
    # written-register tell (extreme em-dash density), and routes it to
    # anti_ai_cliche rather than pretending it measured a human point of view.
    words = max(1, len(text.split()))
    per_1k = 1000.0 / words
    if words < 400:
        return flags, caps
    dashes = text.count("—")
    if dashes * per_1k > 22:
        flags.append(
            f"em-dash prose: {dashes} em-dashes in {words} words — periodic, balanced "
            "clauses are essay register; break them into spoken fragments")
        caps["anti_ai_cliche"] = min(caps.get("anti_ai_cliche", 99), 3)
    return flags, caps


def finance_presence_diagnostics(text: str) -> dict[str, float | int]:
    """Observable texture for the semantic critic, never a pass/fail score."""
    words = max(1, len((text or "").split()))
    scale = 1000.0 / words
    return {
        "words": words,
        "companionship_per_1k": round(len(_COMPANION_RE.findall(text)) * scale, 2),
        "reaction_phrases_per_1k": round(len(_REACTION_RE.findall(text)) * scale, 2),
        "invitations_per_1k": round(len(_INVITATION_RE.findall(text)) * scale, 2),
        "contractions_per_1k": round(len(_CONTRACTION_RE.findall(text)) * scale, 2),
        "spoken_signposts": len(_SIGNPOST_RE.findall(text)),
        "em_dashes_per_1k": round((text or "").count("—") * scale, 2),
    }


_HUMAN_ANCHOR_CONTRACT_RE = re.compile(
    r"\bthe human anchor\b|\bhuman[- ]anchor\b", re.IGNORECASE)
_HUMAN_ANCHOR_DETAILS_RE = re.compile(
    r"(?im)^\s*HUMAN_ANCHOR_REQUIRED_DETAILS\s*:\s*([^\r\n]+)")
_NAMED_ANCHOR_RE = re.compile(
    r"\b(?:(?:let(?:'s| us)|we(?:'ll| will))\s+call\s+"
    r"(?:her|him|them)\s+|(?:picture|imagine|consider)\s+)"
    r"([A-Z][A-Za-z'-]{1,30})\b",
    re.IGNORECASE)
_ILLUSTRATIVE_CUE_RE = re.compile(
    r"\b(?:hypothetical(?:ly)?|picture|imagine|consider|suppose)\b",
    re.IGNORECASE)
_ANCHOR_DETAIL_GROUPS = (
    re.compile(
        r"\b(?:shift|schedule|part[- ]time|mornings?|job|work|apron|"
        r"garden center|pay ?stub)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:kitchen table|grocer(?:y|ies)|rent|bill|furnace|repair|"
        r"household|estimate|envelope)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:budget|assigned|planned|set aside|deposit|cash[- ]flow|"
        r"due this month|today'?s calendar)\b", re.IGNORECASE),
)


def human_anchor_contract_problems(draft, operator_desc: str = "") -> list[str]:
    """Check an explicit operator-requested human-anchor story contract.

    This is a structural floor, not a machine claim that the story is good. It
    prevents a semantic judge from awarding human-presence points to a
    calculator exercise that merely adds "that stopped me." The contract is
    active only when the operator brief names a HUMAN ANCHOR.
    """
    if not _HUMAN_ANCHOR_CONTRACT_RE.search(operator_desc or ""):
        return []

    pieces: list[tuple[str, str]] = [
        ("HOOK", str(getattr(draft, "hook", "") or ""))]
    pieces.extend(
        (
            str(getattr(segment, "heading", "") or f"SEGMENT {index}"),
            str(getattr(segment, "content", "") or ""),
        )
        for index, segment in enumerate(
            list(getattr(draft, "segments", ()) or ()), 1)
    )
    pieces.append(("OUTRO", str(getattr(draft, "outro", "") or "")))
    narration = "\n".join(text for _, text in pieces)

    requested = _NAMED_ANCHOR_RE.search(operator_desc or "")
    expected_name = requested.group(1) if requested else ""
    anchor_name = expected_name
    problems: list[str] = []

    if not expected_name:
        return []
        problems.append(
            "the script never transparently introduces a named illustrative "
            "person with 'let's/we'll call her/him …'")
        return problems
    name_re = re.compile(rf"\b{re.escape(anchor_name)}\b", re.IGNORECASE)
    if not name_re.search(narration):
        return [
            f"the operator requested anchor {anchor_name}, but the name never "
            "appears in the script"
        ]
    occurrences = len(name_re.findall(narration))
    if occurrences < 3:
        problems.append(
            f"{anchor_name} appears only {occurrences} time(s); the anchor must "
            "return through cause, current consequence, and later turn")

    section_hits = [
        heading for heading, text in pieces if name_re.search(text)
    ]
    if len(section_hits) < 3:
        problems.append(
            f"{anchor_name} appears in only {len(section_hits)} section(s); "
            "a name pasted onto one calculation is not a carried story")
    if not name_re.search(pieces[0][1]):
        problems.append(
            f"{anchor_name} is absent from the hook even though this video's "
            "operator brief explicitly requires the human stake there")

    example_index = next(
        (
            index for index, (heading, _) in enumerate(pieces)
            if "EXAMPLE" in heading.upper()
        ),
        None,
    )
    if example_index is not None and not any(
            name_re.search(text) for _, text in pieces[example_index + 1:]):
        problems.append(
            f"{anchor_name} disappears after the worked example; the later "
            "recalculation must return to the same household")

    anchor_contexts: list[str] = []
    for _, text in pieces:
        for match in name_re.finditer(text):
            anchor_contexts.append(
                text[max(0, match.start() - 220):match.end() + 300])
    anchored_text = "\n".join(anchor_contexts)
    detail_groups = sum(
        bool(pattern.search(anchored_text))
        for pattern in _ANCHOR_DETAIL_GROUPS)
    if detail_groups < 2:
        problems.append(
            "the anchor carries fewer than two ordinary life-detail groups "
            "(work routine, household bill/prop, or current budget plan)")

    all_scenes = list(getattr(draft, "hook_scenes", ()) or [])
    for segment in list(getattr(draft, "segments", ()) or []):
        all_scenes.extend(list(getattr(segment, "scenes", ()) or []))
    all_scenes.extend(list(getattr(draft, "outro_scenes", ()) or []))
    shooting_text = narration + "\n" + "\n".join(
        str(getattr(scene, "visual_prompt", "") or "")
        for scene in all_scenes)
    details_match = _HUMAN_ANCHOR_DETAILS_RE.search(operator_desc or "")
    if details_match:
        required_details = [
            item.strip()
            for item in details_match.group(1).split("|")
            if item.strip()
        ]

        def _detail_norm(value: str) -> str:
            return re.sub(
                r"\s+", " ",
                re.sub(r"[-_/]+", " ", value.casefold()),
            ).strip()

        normalized_shooting = _detail_norm(shooting_text)
        missing_details = [
            detail for detail in required_details
            if _detail_norm(detail) not in normalized_shooting
        ]
        if missing_details:
            problems.append(
                "the requested recurring anchor details are absent from VO "
                "and storyboard: " + ", ".join(missing_details))
    return problems


def dimension_rubric() -> str:
    """Per-dimension scoring bands injected into the critic prompt."""
    return f"""═══ SCORE ON {len(VO_DIMS)} VO DIMENSIONS ({sum(VO_DIMS.values())}pts) + {len(PROD_DIMS)} PRODUCTION DIMENSIONS ({sum(PROD_DIMS.values())}pts) ═══
Return one CriticDimension per name below (use these EXACT names and max_score).

── VO GROUP ({sum(VO_DIMS.values())}pts) ──
1. accuracy_trust (max {VO_DIMS['accuracy_trust']}) — THE dimension for this channel. Every dollar amount,
   percentage, threshold, age rule and deadline must carry an attributed source and a year
   ("according to SSA's 2026 fact sheet…"). Numbers must be internally consistent (the same
   figure never changes between scenes; any math shown must actually work). Deduct hard for:
   an uncited precise number, a source named without a year, figures that contradict each
   other, or hedged invented statistics ("some say", "experts estimate" with no source).
   TWO LANES (do not confuse them): the FACT lane above is evidence-bound. The
   JUDGMENT lane — opinions, interpretations, and professional common knowledge
   voiced AS the narrator's own read ("my read is…", "bills parked in committee
   usually stay parked — that's the pattern, not a statistic") — is NOT an
   accuracy violation and must NOT be deducted here, PROVIDED it attaches no
   specific uncited number, date, percentage, or named-entity fact. Judgment is
   scored under editorial_courage. A judgment dressed as a statistic ("87% of
   bills die in committee" with no source) IS an accuracy violation.
   {VO_DIMS['accuracy_trust']}: every claim sourced+dated, math airtight. 8-12: 1-2 uncited or undated numbers.
   0-7: any invented/contradictory figure.
2. spoken_presence (max {VO_DIMS['spoken_presence']}) — THE ANTI-AI-SLOP DIMENSION. This script is
   SPOKEN by a person who has a self, not an essay read aloud. Score the SIX mechanics
   that separate "a friend telling you something" from "correct content narrated":
   (a) COMPANIONSHIP — "we"/"let's" travelling together through the material, not a
       lecturer addressing an audience ("let's run this one together", "so where does
       that leave us?");
   (b) REACTION — the narrator REACTS to their own facts before moving on ("$7,760 —
       that stopped me too", "and here's the part that annoys me"). A figure stated and
       abandoned with no human response is the single strongest AI tell in this niche;
   (c) INVITATION — imperatives that make the viewer do something in their head
       ("picture the booth", "look at this number for a second", "try this");
   (d) MOUTH-LANGUAGE — contractions, short fragments, spoken connectives ("so", "but
       here's the thing", "honestly"). Deduct hard for essay register: balanced clauses,
       em-dash-heavy periodic sentences, participial stacking — writing that reads well
       on paper but sounds like a document when spoken;
   (e) SIGNPOSTING ALOUD — the narrator says where we are and where we're going ("that's
       the history — now the part that costs money");
   (f) FELT METAPHOR — at least one metaphor aimed at sensation, not just structure
       (a scar that aches vs. merely "a two-lane toll booth").
   Do NOT award points by counting "let's", "honestly", questions, contractions,
   metaphors, or reaction phrases. Those are surface clues and can be stuffed.
   Full credit requires a recognisable THESIS, a fair COUNTERPOINT, and at least
   two moments where the narrator responds to a specific fact with an
   interpretation that advances the argument. The reactions must be adjacent
   to the facts they interpret; generic attitude sprinkled elsewhere does not count.
   EMPATHY ORDER: when the script corrects a misconception or fear, it must
   legitimize the feeling FIRST ("it does make sense to wonder...") and then
   correct it. Instructing the viewer to set a feeling aside before the math
   ("put that fear to one side") is a register failure in this niche — deduct.
   EARNED SUBSCRIBE CONTRACT: near the close, one short spoken invitation must
   connect subscribing to the channel promise the viewer just experienced
   (such as reading the fine print together). ONE brief self-aware
   like/algorithm aside is ALLOWED when it is honest and tied to the video's
   value (cohort winners use exactly this; e.g. "mildly embarrassing to ask,
   but true") — but a generic CTA, algorithm begging, a second subscribe,
   invented friendship, or fabricated authority does not count and costs
   spoken-presence points.
   The final audience question must still be the last spoken line; no second
   CTA or spoken next-video tease follows it.
   {VO_DIMS['spoken_presence']}: 5-6 mechanics present and natural, no essay register anywhere.
   6-8: 3-4 mechanics, occasional written-not-spoken passage.
   3-5: mostly correct prose, narrator has no visible self.
   0-2: reads like a well-sourced article being read out — REJECT-worthy on this channel.
3. clarity_65plus (max {VO_DIMS['clarity_65plus']}) — plain English for a smart 68-year-old who hates being
   patronized. One idea per sentence; every term of art (RMD, IRMAA, provisional income)
   defined in one plain clause on first use; concrete dollar examples over abstractions;
   NO baby-talk, NO "seniors like you". Deduct for jargon runs, nested conditionals,
   or a condescending register.
4. hook_quality (max {VO_DIMS['hook_quality']}) — does the opening earn the next 30 seconds?
   SCORE ON STAKE AND SPECIFICITY, NOT ON A SHAPE. Full marks: the viewer learns
   within the first breaths what is at risk for someone like them, in concrete
   terms, and every figure named in the hook is sourced later in the script.
   Deduct for: a greeting opener; vague dread with nothing concrete; a promise the
   body never keeps; a hook number that is never explained.
   WHAT THIS RUBRIC NO LONGER CLAIMS. Two earlier versions carried competitor
   "findings" as scoring instructions — first stopwatch targets ("first number by
   ~27s", "first dollar by ~79s"), then an opening SHAPE ("event or promise, never
   a maybe" / "abstract condition = the losing shape"). Both came from a 19-video
   pilot. On the full cohort — velocity-based labels, matched pairs, bootstrap CI,
   effect size, cross-channel agreement — NOTHING about openings reached
   rule-grade. The shape reading survives only as a qualitative observation in the
   craft playbook, and an observation must not be scored. Do NOT deduct for an
   opening that begins with a condition rather than an event, and do NOT deduct on
   timing in either direction.
5. retention_structure (max {VO_DIMS['retention_structure']}) — open loops resolved on time, chaptered
   structure a viewer can rewatch one section of, hook promises paid off. Deduct −4 for a
   hook figure the body never explains; −3 for teasing content that never arrives;
   −3 for RE-ARGUING a point the script already settled (the same tension restated
   across sections is padding, not retention — each chapter must add a new fact,
   consequence, or audience segment). A single reveal scheduled aloud in the hook
   and paid off late with an explicit callback is strong craft when present, but
   its absence is not a deduction — do not demand one universal retention shape.
   Do not demand one universal example shape. A compact calculation, document
   walkthrough, anonymous household, recurring human anchor, timeline, contrast,
   or no worked example can all earn full credit when they serve the argument.
   Only score a recurring human-anchor contract when the per-video OPERATOR BRIEF
   explicitly asks for one. A fabricated client, agency action,
   tax/Medicare/spousal effect, or other consequence outside supplied evidence
   is a trust failure, not retention craft.
6. actionability (max {VO_DIMS['actionability']}) — the viewer leaves with a concrete educational step
   supported by the supplied evidence, never a personal directive. A worked
   worksheet using sourced thresholds and ratios can be actionable; never invent a calculator,
   tool, form, deadline, or required input that is absent from the verified evidence pack.
   Full marks = a checklist-able educational takeaway per major section.
7. anti_ai_cliche (max {VO_DIMS['anti_ai_cliche']}) — zero "delve/tapestry/it's important to note/in
   conclusion", no corporate filler, no mechanical counting as the BODY's spine.
   EXEMPT: one numbered checklist in the CLOSING section is this channel's
   format (the tangible-utility pattern its winners share) — never penalise it.
8. niche_compliance (max {VO_DIMS['niche_compliance']}) — finance fatal rules (see FATAL RULES above):
   guarantees, price predictions, promised outcomes, uncited Social Security claims,
   advisor-persona claims → 0-2 per the rules.
9. editorial_courage (max {VO_DIMS['editorial_courage']}) — THE REWARD DIMENSION (operator mandate
   2026-08-01: "I need an advisor, a friend sharing viewpoints — not a stiff
   news bulletin"). Full marks require BOTH, anywhere in the script:
   (a) at least one CONTESTABLE POSITION — an opinion a reasonable viewer could
       push back on, voiced as the narrator's own read ("my read is…", "I'm
       rooting for the simplification"), not hedged into mush; and
   (b) at least one moment of PLAY — wit, a coined metaphor, a wry aside, a
       short human digression that serves the story.
   JUDGMENT-lane statements (see accuracy_trust's two-lane note) are welcome
   and belong here; a recurring channel metaphor reused across videos is a
   brand asset, never repetition. {VO_DIMS['editorial_courage']}: both present, genuinely risky or
   charming. 2-3: one of the two. 0-1: nothing a viewer could disagree with —
   the stiff-bulletin failure mode this channel is explicitly steering out of.

── PRODUCTION GROUP ({sum(PROD_DIMS.values())}pts) ──
10. visual_concreteness (max {PROD_DIMS['visual_concreteness']}) — every scene names a filmable, specific
   visual: the actual form (SSA-44), a statement close-up, a dated letter. Deduct for
   "worried senior stock photo" placeholders.
11. data_visualization (max {PROD_DIMS['data_visualization']}) — every load-bearing number appears
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
        f'  "voiceover_score": <sum of the {len(VO_DIMS)} VO dimensions, max {sum(VO_DIMS.values())}>,\n'
        f'  "production_score": <sum of the 2 PRODUCTION dimensions, max {sum(PROD_DIMS.values())}>,\n'
        '  "approved": false,\n'
        '  "dimensions": [' + vo + prod + "\n  ],\n"
        '  "rejection_reasons": ["<VO issues — sent to Writer>"],\n'
        '  "specific_fixes": ["<specific fix 1>", "<specific fix 2>"],\n'
        '  "visual_fixes": ["<specific visual fix>"]\n'
        "}"
    )
