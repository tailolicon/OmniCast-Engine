"""The one thing a video argues, decided before anyone writes a sentence.

Every script this system produced was correct and had nothing to say. The
pipeline asked the writer for a topic ("the 2026 earnings test") and got back
an accurate explanation of it — which is what a reference page does, and what
a viewer already has. The operator's verdict after watching the approved cut
was about exactly this: it reads like a bulletin, not like someone who has a
view.

The missing stage is editorial, not linguistic. Nothing in the pipeline ever
answered: what is this video CLAIMING, what does it push against, and what
should the viewer believe at the end that they did not believe at the start?
Bolting "personality" onto a script that argues nothing produces a bulletin
with jokes in it.

So the angle is decided first, validated as a claim rather than a subject, and
carried into generation as a constraint. The validation is the load-bearing
part: asked for a thesis, a language model will happily return the topic with
a verb in it, and every downstream gate would pass that.

YMYL note: this niche is retirement finance for people who cannot absorb a
loss. A thesis is allowed to argue that a belief is wrong; it is NOT allowed
to instruct a viewer to take a financial action. `check_angle` enforces that
distinction, because it is exactly the line a persuasive angle wants to cross.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, model_validator

from omnicast.agents.base import BaseAgent


@dataclass(frozen=True)
class EditorialAngle:
    """What the video argues, and what it argues against.

    `evidence_ids` point into the fact-citation ledger. An angle with no
    evidence behind it is an opinion the channel has not earned; requiring the
    link at this stage is what stops the writer from reverse-engineering
    sources to fit a thesis it already committed to.
    """

    thesis: str
    against: str
    stake: str
    turn: str
    walk_away: str
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    # The fields below turn a thesis into an editorial through-line. They are
    # optional for backward compatibility with saved/manual angle files;
    # automated production calls ``check_angle(..., require_full=True)``.
    counterpoint: str = ""
    narrator_attitude: str = ""
    reaction_beats: tuple[str, ...] = field(default_factory=tuple)
    felt_metaphor: str = ""
    metaphor_callback: str = ""
    driving_questions: tuple[str, ...] = field(default_factory=tuple)
    ending_question: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "thesis": self.thesis,
            "against": self.against,
            "stake": self.stake,
            "turn": self.turn,
            "walk_away": self.walk_away,
            "evidence_ids": list(self.evidence_ids),
            "counterpoint": self.counterpoint,
            "narrator_attitude": self.narrator_attitude,
            "reaction_beats": list(self.reaction_beats),
            "felt_metaphor": self.felt_metaphor,
            "metaphor_callback": self.metaphor_callback,
            "driving_questions": list(self.driving_questions),
            "ending_question": self.ending_question,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "EditorialAngle":
        """Rebuild an angle from ``as_dict`` output (driver → pipeline handoff).

        A validated operator angle must survive the trip into ``_step_script``
        as an OBJECT, not as prompt prose — prose lets the planner re-plan and
        override it (live failure 2026-08-01: an angle naming H.R. 8344 was
        reduced to advisory text and the generated video contained no bill)."""
        return cls(
            thesis=str(raw.get("thesis", "")),
            against=str(raw.get("against", "")),
            stake=str(raw.get("stake", "")),
            turn=str(raw.get("turn", "")),
            walk_away=str(raw.get("walk_away", "")),
            evidence_ids=tuple(raw.get("evidence_ids", ()) or ()),
            counterpoint=str(raw.get("counterpoint", "")),
            narrator_attitude=str(raw.get("narrator_attitude", "")),
            reaction_beats=tuple(raw.get("reaction_beats", ()) or ()),
            felt_metaphor=str(raw.get("felt_metaphor", "")),
            metaphor_callback=str(raw.get("metaphor_callback", "")),
            driving_questions=tuple(raw.get("driving_questions", ()) or ()),
            ending_question=str(raw.get("ending_question", "")),
        )

    def as_prompt_block(self) -> str:
        """The constraint the writer works under, in the writer's own terms."""
        full = (
            "── THIS VIDEO'S ARGUMENT (decided before writing; do not drift) ──\n"
            f"  CLAIM:        {self.thesis}\n"
            f"  PUSHES AGAINST: {self.against}\n"
            f"  WHY IT COSTS THEM: {self.stake}\n"
            f"  THE TURN:     {self.turn}\n"
            f"  FAIR COUNTERPOINT: {self.counterpoint or '(not supplied)'}\n"
            f"  NARRATOR ATTITUDE: {self.narrator_attitude or '(not supplied)'}\n"
            f"  REACTION BEATS: {' | '.join(self.reaction_beats) or '(not supplied)'}\n"
            f"  FELT METAPHOR: {self.felt_metaphor or '(not supplied)'}\n"
            f"  METAPHOR CALLBACK: {self.metaphor_callback or '(not supplied)'}\n"
            f"  DRIVING QUESTIONS: {' | '.join(self.driving_questions) or '(not supplied)'}\n"
            f"  ENDING QUESTION: {self.ending_question or '(not supplied)'}\n"
            f"  WALK-AWAY:    {self.walk_away}\n"
            f"  EVIDENCE ANCHORS: {', '.join(self.evidence_ids)}\n"
            "  The claim must be recognisable in the first minute, defended in "
            "the middle, tested against the fair counterpoint, and landed in "
            "the viewer's own words at the end. "
            "Explaining the topic without landing the claim is a failed script, "
            "however accurate it is.\n"
            "  React only to a fact immediately after that fact appears. Keep "
            "FACT, INTERPRETATION, and METAPHOR distinct; a metaphor may explain "
            "a sourced fact but may never become evidence for it.\n"
            "  Never invent a personal anecdote, client, credential, interview, "
            "or first-hand experience. The narrator may have an honest attitude "
            "toward the evidence, not a fabricated biography.\n"
            "  Do NOT tell the viewer what to do with their money. Argue what is "
            "TRUE; let them decide what to do about it.\n")
        return full


# A thesis is a claim. These are the shapes that pretend to be one.
_TOPIC_ONLY = re.compile(
    r"^(what|how|why|when|where|who)\b|^(everything|all) you need to know\b"
    r"|^(a|an|the)\s+(guide|overview|breakdown|explainer|introduction)\b",
    re.I)
_HEDGE_ONLY = re.compile(
    r"\b(it depends|may vary|varies by|could be different|"
    r"everyone.s situation|consult (a|your) (professional|advisor|adviser))\b",
    re.I)
# Directives. In a YMYL niche this is the difference between a channel with a
# view and a channel giving unlicensed advice.
_DIRECTIVE = re.compile(
    r"\b(you should|you must|you need to|you ought to|make sure you|"
    r"i recommend|we recommend|don.t wait to|start (claiming|filing|investing)|"
    r"(claim|file|withdraw|convert|buy|sell) (now|today|immediately|at \d+))\b",
    re.I)
_CLAIM_VERBS = re.compile(
    r"\b(is|are|was|were|isn.t|aren.t|does|doesn.t|do|don.t|will|won.t|"
    r"costs?|loses?|gains?|beats?|fails?|hides?|misses?|breaks?|"
    r"has|have|hasn.t|haven.t|can|can.t|cannot|makes?|leaves?|turns?|"
    # Modal mood — a thesis about an unpassed bill or a hypothetical is still a
    # claim ("repeal WOULD not hand retirees new money"). News-frame topics
    # were impossible before these (live failure 2026-08-01: a valid conditional
    # thesis was rejected twice as "no assertive verb").
    r"would|wouldn.t|could|couldn.t|may|might|must|"
    r"means?|matters?|moves?|stops?|stays?|remains?|buys?|saves?)\b",
    re.I)
_FABRICATED_AUTHORITY = re.compile(
    r"\b(?:my clients?|clients? of mine|our clients?|in my practice|"
    r"i(?:'ve| have) advised|i advise (?:retirees|clients|people)|"
    r"when i was (?:an?|your) (?:advisor|adviser|planner|cpa)|"
    r"from my years as (?:an?|your) (?:advisor|adviser|planner|cpa))\b",
    re.I)

MIN_THESIS_WORDS = 6
MAX_THESIS_WORDS = 32


def check_angle(angle: EditorialAngle, *, require_full: bool = False) -> list[str]:
    """Return the reasons this angle is not yet an argument. Empty = usable."""
    problems: list[str] = []
    thesis = (angle.thesis or "").strip()
    words = thesis.split()

    if not thesis:
        problems.append("thesis is empty")
    else:
        if len(words) < MIN_THESIS_WORDS:
            problems.append(
                f"thesis is {len(words)} words — too short to be a claim")
        if len(words) > MAX_THESIS_WORDS:
            problems.append(
                f"thesis is {len(words)} words — a paragraph, not a claim")
        if thesis.rstrip().endswith("?"):
            problems.append("thesis is a question; a question commits to nothing")
        if _TOPIC_ONLY.search(thesis):
            problems.append("thesis names a topic ('what/how/guide to…') "
                            "instead of asserting something")
        if not _CLAIM_VERBS.search(thesis):
            problems.append("thesis has no assertive verb — it reads as a "
                            "subject line, not a position")
        if _HEDGE_ONLY.search(thesis):
            problems.append("thesis hedges to the point of claiming nothing")
        if _DIRECTIVE.search(thesis):
            problems.append("thesis instructs the viewer to act (YMYL): argue "
                            "what is true, not what they should do")

    against = (angle.against or "").strip()
    if not against:
        problems.append("nothing to push against — an argument needs an "
                        "opposing belief a real viewer holds")
    elif _norm(against) == _norm(thesis):
        problems.append("'against' restates the thesis")

    if not (angle.stake or "").strip():
        problems.append("no stake — nothing is lost if the viewer ignores this")
    if not (angle.turn or "").strip():
        problems.append("no turn — no moment where the viewer's mind changes")

    walk = (angle.walk_away or "").strip()
    if not walk:
        problems.append("no walk-away line")
    elif _DIRECTIVE.search(walk):
        problems.append("walk-away instructs the viewer to act (YMYL)")

    if not angle.evidence_ids:
        problems.append("no ledger evidence behind the claim — an unsupported "
                        "position is an opinion this channel has not earned")

    if require_full:
        if not (angle.counterpoint or "").strip():
            problems.append("no fair counterpoint — the thesis is advocacy, not analysis")
        if not (angle.narrator_attitude or "").strip():
            problems.append("no narrator attitude — the script will default to a bulletin")
        if len(angle.reaction_beats) < 2:
            problems.append("fewer than two planned reaction beats")
        if not (angle.felt_metaphor or "").strip():
            problems.append("no felt metaphor")
        if not (angle.metaphor_callback or "").strip():
            problems.append("no metaphor callback")
        if len(angle.driving_questions) < 2:
            problems.append("fewer than two driving questions")
        if not (angle.ending_question or "").strip():
            problems.append("no ending question")

        all_editorial = " ".join([
            angle.thesis, angle.against, angle.stake, angle.turn,
            angle.walk_away, angle.counterpoint, angle.narrator_attitude,
            *angle.reaction_beats, angle.felt_metaphor,
            angle.metaphor_callback, *angle.driving_questions,
            angle.ending_question,
        ])
        if _FABRICATED_AUTHORITY.search(all_editorial):
            problems.append(
                "fabricated experience/credential in editorial angle — the "
                "narrator may react to evidence but may not invent clients or practice")
    return problems


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()


def verify_evidence(angle: EditorialAngle, ledger: dict) -> list[str]:
    """Resolve `evidence_ids` against a fact-citation ledger.

    Without this the field is decoration: `check_angle` can only see that the
    tuple is non-empty, so any three strings would satisfy "the claim rests on
    evidence". An id here is the `value` of a ledger entry (e.g. "$24,480",
    "benefit recalculation at FRA") and it must resolve to an entry with a REAL
    source — a worked example is an illustration of the claim, never its
    ground.
    """
    entries = (ledger or {}).get("ledger", ledger or {}).get("entries", [])
    problems: list[str] = []
    for eid in angle.evidence_ids:
        want = _norm(eid)
        hits = [e for e in entries if _norm(str(e.get("value", ""))) == want]
        if not hits:
            problems.append(f"evidence id {eid!r} matches no ledger entry")
            continue
        if not any((e.get("source_url") or "").strip() for e in hits):
            problems.append(
                f"evidence id {eid!r} resolves only to a worked example — a "
                "hypothetical illustrates a claim, it cannot support one")
    return problems


def angle_is_delivered(angle: EditorialAngle, narration: str,
                       *, head_share: float = 0.25) -> list[str]:
    """Did the finished script actually argue the thing it committed to?

    Deliberately crude: it checks PRESENCE and POSITION, not quality, because a
    stronger claim here would need a judge and a judge is the thing that can be
    talked out of its verdict. A script that never repeats its own claim's
    content words is not making an argument no matter how it reads.

    MEASURED LIMIT, so nobody reads a pass as a verdict: the 2,348-word script
    the operator rejected clears this check with no gaps. It mentions the claim
    early and closes on it — and still reads like a bulletin. This is a FLOOR
    (the claim is at least present and positioned), not evidence that the
    script argues anything. Telling "argues" from "explains" needs a semantic
    judge; the value of the angle is in constraining generation, not in this
    detector.
    """
    problems: list[str] = []
    body = (narration or "").strip()
    if not body:
        return ["script is empty"]
    words = body.split()
    head = " ".join(words[: max(1, int(len(words) * head_share))])
    tail = " ".join(words[-max(1, int(len(words) * 0.2)):])

    key = _content_words(angle.thesis)
    if not key:
        return ["thesis carries no content words to look for"]
    hits_head = sum(1 for k in key if k in _norm(head))
    hits_all = sum(1 for k in key if k in _norm(body))

    if hits_all < max(2, len(key) // 3):
        problems.append("the script never restates its own claim — it explains "
                        "the topic instead of arguing the thesis")
    if hits_head < max(1, len(key) // 4):
        problems.append("the claim does not surface early; the viewer cannot "
                        "tell what this video is for")
    walk_key = _content_words(angle.walk_away)
    if walk_key and not any(k in _norm(tail) for k in walk_key):
        problems.append("the walk-away line never lands in the closing stretch")
    return problems


_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "that", "this", "these", "those", "is", "are", "was", "were", "be", "been",
    "it", "its", "you", "your", "they", "their", "them", "at", "by", "from",
    "as", "than", "then", "not", "no", "do", "does", "did", "so", "if", "what",
    "who", "how", "why", "when", "where", "most", "more", "less", "can", "will",
}


def _content_words(text: str) -> list[str]:
    return [w for w in _norm(text).split() if w not in _STOP and len(w) > 3]


class _EditorialAngleDraft(BaseModel):
    """Strict structured output for the planning call."""

    thesis: str
    against: str
    stake: str
    turn: str
    walk_away: str
    evidence_ids: list[str] = Field(min_length=1)
    counterpoint: str
    narrator_attitude: str
    reaction_beats: list[str] = Field(min_length=2, max_length=4)
    felt_metaphor: str
    metaphor_callback: str
    driving_questions: list[str] = Field(min_length=2, max_length=4)
    ending_question: str

    @model_validator(mode="before")
    @classmethod
    def _normalize_model_variants(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        nested = data.get("editorial_angle")
        if isinstance(nested, dict):
            data = {**data, **nested}
        aliases = {
            "thesis": ("claim", "core_claim", "argument"),
            "against": (
                "pushes_against", "common_belief", "misconception"),
            "stake": (
                "stakes", "why_it_matters", "why_this_matters",
                "audience_stake", "viewer_stake", "stakes_for_viewer",
                "what_is_at_stake", "what_the_viewer_risks", "cost"),
            "turn": (
                "reveal", "pivot", "editorial_turn", "narrative_turn",
                "turning_point", "key_turn", "mechanism"),
            "walk_away": (
                "takeaway", "viewer_takeaway", "core_takeaway", "walkaway",
                "walk_away_message", "mental_model_to_keep",
                "lasting_idea", "bottom_line", "closing_idea"),
            "evidence_ids": (
                "evidence_anchors", "evidence", "source_ids"),
            "counterpoint": (
                "fair_counterpoint", "limitation", "caveat"),
            "narrator_attitude": (
                "stance", "attitude", "voice", "editorial_stance"),
            "felt_metaphor": ("metaphor", "central_metaphor"),
            "metaphor_callback": ("callback", "metaphor_return"),
            "ending_question": (
                "closing_question", "final_question"),
        }
        for canonical, variants in aliases.items():
            if data.get(canonical) in (None, "", []):
                for name in variants:
                    if data.get(name) not in (None, "", []):
                        data[canonical] = data[name]
                        break

        def text(item) -> str:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                for key in (
                    "text", "statement", "summary", "reaction", "question",
                    "value", "description", "meaning",
                ):
                    if item.get(key):
                        return str(item[key])
                return "; ".join(
                    f"{key}: {val}" for key, val in item.items()
                    if val not in (None, "", []))
            return str(item)

        reactions = data.get("reaction_beats")
        if isinstance(reactions, str):
            reactions = [reactions]
        if isinstance(reactions, list):
            normalized = []
            for item in reactions[:4]:
                if isinstance(item, dict):
                    anchor = (
                        item.get("fact") or item.get("evidence_id")
                        or item.get("anchor") or "")
                    reaction = text(item)
                    normalized.append(
                        f"{anchor}: {reaction}" if anchor else reaction)
                else:
                    normalized.append(text(item))
            data["reaction_beats"] = normalized

        questions = data.get("driving_questions")
        if isinstance(questions, str):
            questions = [questions]
        if isinstance(questions, list):
            data["driving_questions"] = [
                text(item) for item in questions[:4]]

        evidence = data.get("evidence_ids")
        if isinstance(evidence, str):
            evidence = [evidence]
        if isinstance(evidence, list):
            data["evidence_ids"] = [
                str(
                    item.get("evidence_id") or item.get("id") or text(item)
                ) if isinstance(item, dict) else str(item)
                for item in evidence
            ]

        for name in (
            "thesis", "against", "stake", "turn", "walk_away",
            "counterpoint", "narrator_attitude", "felt_metaphor",
            "metaphor_callback", "ending_question",
        ):
            if data.get(name) is not None and not isinstance(data.get(name), str):
                data[name] = text(data[name])
        return data


class EditorialAnglePlanner(BaseAgent):
    """Plan the argument once, before variants start writing prose.

    This is deliberately a separate paid call. Asking the Writer to discover
    its position while also producing 2,000 words makes the position drift
    back toward a generic explainer. The planner may only cite anchors present
    in the brief; it cannot manufacture a source id that merely looks real.
    """

    @property
    def name(self) -> str:
        return "editorial_angle"

    @property
    def system_prompt(self) -> str:
        return (
            "You are the editorial director of an accuracy-first retirement "
            "finance channel. Decide what one video ARGUES before a writer "
            "drafts it. You may have an attitude toward evidence, but you may "
            "never invent credentials, clients, interviews, personal history, "
            "or financial advice. Return JSON only."
        )

    async def execute(self, brief) -> EditorialAngle:
        anchors = self._anchors(brief)
        if not anchors:
            raise ValueError(
                "editorial angle requires at least one supplied evidence/context "
                "anchor; refusing to invent a position from a title alone")

        anchor_text = "\n".join(
            f"- {key}: {value}" for key, value in anchors.items())
        prompt = f"""Plan one editorial argument for this video.

TOPIC: {brief.title}
AUDIENCE: {getattr(brief, 'target_audience', '') or 'not supplied'}
PAIN: {getattr(brief, 'pain_point', '') or 'not supplied'}
OPERATOR/CHANNEL ANGLE: {getattr(brief, 'content_angle', '') or 'not supplied'}

ALLOWED INPUT ANCHORS:
{anchor_text}

CONTRACT:
- Return every required key exactly once: thesis, against, stake, turn,
  walk_away, evidence_ids, counterpoint, narrator_attitude, reaction_beats,
  felt_metaphor, metaphor_callback, driving_questions, ending_question.
- stake is the concrete cost to this audience of keeping the mistaken belief.
- turn is the evidence-led reveal that changes the meaning of what came before.
- walk_away is the sharper mental model the viewer should retain; it is not
  personal financial advice or an instruction.
- thesis is one assertive, falsifiable interpretation — not a topic, question,
  instruction, list, or generic "it depends".
- evidence_ids contains ONLY ids from ALLOWED INPUT ANCHORS. An anchor is a
  boundary, not permission to invent facts beyond its wording.
- Do not translate "recalculate" or "credit withheld months" into a
  dollar-for-dollar repayment, refund, guaranteed recovery, or lump-sum return
  unless an allowed anchor says that explicitly.
- A reaction may interpret why a supplied fact changes the argument; it may not
  add prevalence, causation, automatic behavior, life-expectancy math, or a new
  factual mechanism that the anchors never supplied.
- against is a belief a real viewer plausibly holds.
- counterpoint is the strongest fair limitation on the thesis; do not create a
  straw man.
- narrator_attitude is an honest editorial response ("calmly irritated by the
  misleading name"), never biography or authority.
- each reaction beat names WHICH supplied fact it follows and HOW the reaction
  changes the interpretation.
- felt_metaphor clarifies the mechanism; metaphor_callback returns to the same
  image later. Neither is evidence.
- driving questions create the causal route through the body. ending_question
  should leave useful tension, not ask for personal financial disclosure.
- no "my clients", "in my practice", "I've advised", fabricated interview, or
  claim that the narrator personally experienced the event.
- educational YMYL boundary: argue what is true; never tell the viewer to
  buy, sell, claim, withdraw, convert, or file.

Return only the structured JSON requested by the schema."""

        problems: list[str] = []
        last: _EditorialAngleDraft | None = None
        for attempt in range(2):
            ask = prompt
            if problems:
                ask += (
                    "\n\nYOUR PREVIOUS DRAFT FAILED THIS CONTRACT:\n- "
                    + "\n- ".join(problems)
                    + "\nReturn a complete corrected JSON object.")
            _, draft = await self.call_llm_structured(
                [{"role": "system", "content": self.system_prompt},
                 {"role": "user", "content": ask}],
                output_schema=_EditorialAngleDraft,
                max_tokens=4000,
                temperature=0.2,
            )
            last = draft
            angle = EditorialAngle(
                thesis=draft.thesis,
                against=draft.against,
                stake=draft.stake,
                turn=draft.turn,
                walk_away=draft.walk_away,
                evidence_ids=tuple(draft.evidence_ids),
                counterpoint=draft.counterpoint,
                narrator_attitude=draft.narrator_attitude,
                reaction_beats=tuple(draft.reaction_beats),
                felt_metaphor=draft.felt_metaphor,
                metaphor_callback=draft.metaphor_callback,
                driving_questions=tuple(draft.driving_questions),
                ending_question=draft.ending_question,
            )
            problems = check_angle(angle, require_full=True)
            unknown = sorted(set(angle.evidence_ids) - set(anchors))
            if unknown:
                problems.append(
                    "invented evidence ids (not present in brief): "
                    + ", ".join(unknown))
            if not problems:
                return angle

        raise ValueError(
            "editorial angle failed validation after repair: "
            + "; ".join(problems)
            + (f" (last thesis: {last.thesis!r})" if last else ""))

    @staticmethod
    def _anchors(brief) -> dict[str, str]:
        anchors: dict[str, str] = {}
        verified = getattr(brief, "evidence_points", ()) or ()
        if verified:
            for item in verified:
                if not isinstance(item, dict):
                    continue
                evidence_id = str(item.get("evidence_id") or "").strip()
                claim = str(item.get("claim") or "").strip()
                if not evidence_id or not claim:
                    continue
                anchors[evidence_id] = (
                    f"{claim}; value={item.get('value') or '(qualitative)'}; "
                    f"source={item.get('source_name')}; as_of={item.get('as_of')}; "
                    f"verified quote={item.get('quote')}")
            return anchors

        next_id = 1
        for point in getattr(brief, "key_points", ()) or ():
            text = str(point).strip()
            if text and not text.startswith("DO NOT REUSE"):
                anchors[f"E{next_id}"] = text
                next_id += 1
        for url in getattr(brief, "source_urls", ()) or ():
            text = str(url).strip()
            if text:
                anchors[f"E{next_id}"] = (
                    f"Source URL supplied by upstream research: {text}")
                next_id += 1
        return anchors
