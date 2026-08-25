"""Anti-slop linter — the words that make a generated frame look generated.

WHY DETERMINISTIC. "Write vividly, avoid generic phrasing" is an instruction a
model obeys most of the time, and the times it does not are invisible until the
render. This repo already learned that lesson on the script side: the
stylometric gates match SHAPES rather than trusting a prompt to be followed.
This is the same move for image prompts.

THE MECHANISM (seedance-2.0 `anti-slop-lexicon.md`, MIT). Abstract quality words
destabilise generation because the model cannot tell which element to emphasise.
"Cinematic" does not name a camera, a light, or a lens, so it is spent budget
that buys an average of everything the word has ever labelled. Decomposing it —
camera verb + speed + viewpoint, light source + direction + behaviour, material
+ texture + motion — is what stabilises the image.

POSITION IS PART OF THE COST. Attention is a budget and early clauses draw more
of it, so one empty evaluator in the opening clause outranks three in the tail.
`lint` reports opening-position hits separately and `blocking_findings` treats
them as hard: a prompt that opens "Cinematic shot of a woman reading" has spent
its most valuable clause before naming what changes on screen.

NEGATION SUMMONS. "no blur, no extra fingers" plants exactly what it forbids;
the repair is to lock the positive ("hands rest still on the table"). This
module flags negation slop in the POSITIVE prompt only — a provider's dedicated
negative field is a different mechanism and is left alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

#: Ceiling on "the opening" when a prompt has no early clause break.
OPENING_CHARS = 120
#: Floor, so a two-word first clause ("Night. …") does not shrink the opening
#: to nothing and let the real first clause through unchecked.
OPENING_MIN = 40

_CLAUSE_BREAK = re.compile(r"[.,;:]")


def opening_span(text: str) -> int:
    """How far into `text` counts as the opening CLAUSE, not the first N chars.

    A raw character count mis-reads position: "…the room otherwise dark and
    still, the mood atmospheric." puts its hedge at char 110, which a flat
    120-char window calls an opening-position hit when it is plainly the tail.
    The mechanism is about clauses — the first one draws the most attention —
    so the boundary is the first clause break, floored and capped.
    """
    body = (text or "").strip()
    if not body:
        return 0
    match = _CLAUSE_BREAK.search(body)
    edge = match.start() if match else len(body)
    return max(OPENING_MIN, min(edge, OPENING_CHARS))


class SlopClass(str, Enum):
    EMPTY_EVALUATOR = "empty_evaluator"
    BORROWED_TOKEN = "borrowed_token"
    TAG_SALAD = "tag_salad"
    NEGATION = "negation"
    ADJECTIVE_STACK = "adjective_stack"
    FEEL_SUFFIX = "feel_suffix"
    #: Asks for someone else's identity or mark. Blocks: a likeness or logo
    #: survives the render and becomes a takedown after upload.
    IP_RISK = "ip_risk"
    #: Legitimate story surface that image filters routinely bounce. Reported
    #: with production wording that keeps the intent; never blocked, because a
    #: horror channel needs these beats.
    FILTER_RISK = "filter_risk"
    #: A motion prompt that only moves the camera. Checked on clip prompts
    #: only — a still prompt has no motion to describe.
    LAZY_MOTION = "lazy_motion"


#: Identity and marks that belong to someone else. From seedance's
#: `filter-vocab.md` rows on celebrity/brand/franchise, which this repo treats
#: as harder than the source does: OmniCast uploads to a monetised channel, so
#: a likeness that renders fine is still a claim waiting to happen.
IP_SURFACES: dict[str, str] = {
    "celebrity": "original character with broad archetype traits",
    "celebrity face": "original character with broad archetype traits",
    "famous actor": "original character with broad archetype traits",
    "famous actress": "original character with broad archetype traits",
    "real person": "original character, no living likeness",
    "copy this person": "original character; keep only user-owned identity",
    "brand logo": "generic product mark or blank label",
    "corporate logo": "generic product mark or blank label",
    "trademark": "generic product mark or blank label",
    "copyrighted character": "original world with a similar genre function",
    "like the movie": "original scene with similar camera function and mood",
    "in the style of the movie": "original scene with similar palette and pacing",
}

#: Surfaces that get a safe prompt refused. seedance's own rule governs the
#: repair: "Preserve intent. Change risky surface wording" — restate the beat in
#: production language, never disguise the same request. These are WARN only.
FILTER_SURFACES: dict[str, str] = {
    "violent impact": "high-energy collision, non-graphic action beat",
    "weapon close-up": "prop object held safely, action-scene staging",
    "blood": "red fabric accent, coloured liquid, non-graphic aftermath",
    "blood-red": "deep red practical light, red fabric accent",
    "gore": "non-graphic aftermath, implied off-frame",
    "injury": "visible fatigue, dramatic tension, character distress",
    "wound": "visible fatigue, dramatic tension, character distress",
    "fight": "choreographed action sequence, staged confrontation",
    "fight scene": "choreographed action sequence, staged confrontation",
    "hostage": "locked-door suspense scene, no restraints and no harm",
    "corpse": "still figure, non-graphic aftermath, implied off-frame",
    "knife": "safe prop object on a table, not used for harm",
}


#: Word → what to say instead. Straight from the lexicon's replacement table:
#: every entry converts an evaluation into something a camera, a light meter or
#: a stopwatch could detect.
REPLACEMENTS: dict[str, str] = {
    "cinematic": "name the shot scale, camera move, light direction and grade",
    "epic": "name the physical scale: crowd size, lens distance, stakes",
    "beautiful": "name the colour, texture, composition or light behaviour",
    "gorgeous": "name the one detail that earns it",
    "stunning": "name the visible contrast, reveal or movement",
    "breathtaking": "name the visible contrast, reveal or movement",
    "mesmerizing": "name the motion path that holds the eye",
    "dramatic": "name the blocking, shadow, silence or camera pressure",
    "dynamic": "name the movement, its speed and its endpoint",
    "striking": "describe the one frame the viewer remembers",
    "magical": "name the particle behaviour, glow source and motion path",
    "professional": "name the lighting setup, background and camera control",
    "ultra-realistic": "name material behaviour, skin texture, lens artefacts",
    "photorealistic": "name material behaviour, skin texture, lens artefacts",
    "hyperrealistic": "name material behaviour, skin texture, lens artefacts",
    "atmospheric": "name the physical cause: fog, practical light, silence",
    "moody": "name the light direction and what is left unlit",
    "aesthetic": "name the actual art direction",
    "vibey": "name the physical cause of the feeling",
    "evocative": "name what is shown that provokes it",
    "hauntingly": "name what is withheld and by what",
    "masterpiece": "delete — quality is not a request",
    "award-winning": "delete — quality is not a request",
    "high quality": "delete — quality is a render setting, not prose",
    "highly detailed": "name the two details that matter",
    "insanely detailed": "name the two details that matter",
    "8k": "delete — resolution is a setting, not prose",
    "4k": "delete — resolution is a setting, not prose",
    "ultra hd": "delete — resolution is a setting, not prose",
    "trending on artstation": "delete — a gallery ranking is not art direction",
    "unreal engine": "delete — name the look, not the renderer",
    "octane render": "delete — name the look, not the renderer",
    "raw photo": "delete — name the lens and light instead",
    "bokeh": "name the aperture effect you want and on what",
}

_EMPTY_EVALUATORS = (
    "cinematic", "epic", "beautiful", "gorgeous", "stunning", "breathtaking",
    "mesmerizing", "dramatic", "dynamic", "striking", "magical", "professional",
    "ultra-realistic", "photorealistic", "hyperrealistic", "evocative",
    "hauntingly", "majestic", "captivating", "immersive", "iconic",
)

_BORROWED_TOKENS = (
    "8k", "4k", "ultra hd", "uhd", "masterpiece", "award-winning", "award winning",
    "trending on artstation", "artstation", "unreal engine", "octane render",
    "raw photo", "highly detailed", "insanely detailed", "high quality",
    "best quality", "hdr", "dslr", "35mm film look",
)

_FEEL_SUFFIX = (
    "atmospheric", "moody", "aesthetic", "vibey", "dreamy", "ethereal",
    "电影感", "雰囲気のある", "감성적인", "atmosférico", "атмосферный",
)

#: Negations in the POSITIVE prompt. A provider's own negative field is a
#: different mechanism — see the module docstring.
_NEGATION_RE = re.compile(
    r"\b(?:no|without|avoid|free of|not)\s+"
    r"(?:any\s+)?"
    r"(blur\w*|artifact\w*|distort\w*|deform\w*|extra\s+\w+|mutat\w+|"
    r"ugly|bad\s+\w+|watermark\w*|text|logo|weird\s+\w+|malform\w*)",
    re.IGNORECASE)

#: Three or more evaluator-ish adjectives in a row make one weak claim.
_STACK_RE = re.compile(
    r"\b(\w+(?:ing|ful|ous|ive|ic|y))\s*,?\s+(\w+(?:ing|ful|ous|ive|ic|y))\s*,?\s+"
    r"(\w+(?:ing|ful|ous|ive|ic|y))\b", re.IGNORECASE)

_VERB_HINT = re.compile(
    r"\b(?:is|are|was|were|stands?|sits?|walks?|turns?|holds?|looks?|reaches?|"
    r"opens?|closes?|leans?|moves?|pulls?|pushes?|enters?|exits?|rests?|lifts?|"
    r"sets?|places?|watches?|waits?|steps?|falls?|rises?|slides?|drops?)\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class SlopFinding:
    slop_class: SlopClass
    text: str
    position: int
    in_opening: bool
    repair: str

    def as_dict(self) -> dict:
        return {"class": self.slop_class.value, "text": self.text,
                "position": self.position, "in_opening": self.in_opening,
                "repair": self.repair}

    def describe(self) -> str:
        where = "in the opening clause" if self.in_opening else f"at char {self.position}"
        return f"'{self.text}' ({self.slop_class.value}, {where}) — {self.repair}"


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)


def _scan_words(text: str, words: tuple[str, ...], slop_class: SlopClass,
                default_repair: str, opening: int) -> list[SlopFinding]:
    found: list[SlopFinding] = []
    for word in words:
        for match in _phrase_pattern(word).finditer(text):
            found.append(SlopFinding(
                slop_class=slop_class,
                text=match.group(0),
                position=match.start(),
                in_opening=match.start() < opening,
                repair=REPLACEMENTS.get(word.lower(), default_repair)))
    return found


def _is_tag_salad(text: str) -> bool:
    """Comma-separated keyword dumps ported from image prompting.

    Detected by shape, not by a keyword list: many short comma fragments and
    almost no verbs means there is no action and no time axis for a video model
    to work with.
    """
    fragments = [f.strip() for f in text.split(",") if f.strip()]
    if len(fragments) < 5:
        return False
    short = sum(1 for f in fragments if len(f.split()) <= 3)
    verbs = len(_VERB_HINT.findall(text))
    return short >= 5 and short / len(fragments) >= 0.6 and verbs <= 1


#: Camera vocabulary. Not slop — a clip needs a camera instruction — but a clip
#: made only of these describes a move with nothing moving.
_CAMERA_VOCAB = frozenset("""
camera pan pans panning tilt tilts tilting zoom zooms zooming push pushes in out
dolly dolly-in dolly-out track tracks tracking crane orbit orbits slow slowly
gentle gently steady static locked frame shot close-up wide medium closeup
left right up down forward backward towards toward on the a an of and it its
""".split())

#: Phrasings the source calls out by name as lazy, whatever else surrounds them.
_LAZY_MOTION_PHRASES = (
    "camera pans left", "camera pans right", "camera slowly zooms in",
    "character smiles",
)


def _scan_motion(text: str, opening: int) -> list[SlopFinding]:
    """Flag a clip prompt that never leaves the camera."""
    repair = ("name what changes on screen — the subject's action, an object "
              "transforming, or the environment reacting — then the camera")
    for phrase in _LAZY_MOTION_PHRASES:
        match = _phrase_pattern(phrase).search(text)
        if match:
            return [SlopFinding(
                slop_class=SlopClass.LAZY_MOTION, text=match.group(0),
                position=match.start(), in_opening=match.start() < opening,
                repair=repair)]

    words = [w for w in re.findall(r"[A-Za-z][\w'-]*", text.lower()) if w]
    if not words:
        return []
    off_camera = [w for w in words if w not in _CAMERA_VOCAB]
    # Under a fifth of the words carrying anything but camera language means the
    # clip is a move with nothing moving.
    if len(off_camera) / len(words) < 0.2:
        return [SlopFinding(
            slop_class=SlopClass.LAZY_MOTION,
            text=text[:60] + ("…" if len(text) > 60 else ""),
            position=0, in_opening=True, repair=repair)]
    return []


def lint(prompt: str, *, motion: bool = False) -> list[SlopFinding]:
    """Every slop hit in a prompt, ordered by position. Empty means clean.

    `motion=True` adds the clip-only check: a video prompt whose whole content
    is camera vocabulary. Cap Assistant's directive prompt states the rule
    bluntly — "Do NOT just write basic, boring camera movements… I2V prompts
    MUST describe SUBJECT ACTIONS, OBJECT TRANSFORMATIONS, and ENVIRONMENTAL
    DYNAMICS" — and its formula is subject + interaction + physics + camera.
    This repo does not adopt the formula wholesale: `clips.py` deliberately
    withholds anything the start frame already shows, and restating the subject
    is what makes a model redraw and drift it. The two rules agree on the part
    that matters and that is what is enforced here: the prompt must name what
    CHANGES. A camera move alone names nothing.
    """
    text = (prompt or "").strip()
    if not text:
        return []

    opening = opening_span(text)
    findings: list[SlopFinding] = []
    findings += _scan_words(text, _EMPTY_EVALUATORS, SlopClass.EMPTY_EVALUATOR,
                            "convert to the one observable detail that earns it",
                            opening)
    findings += _scan_words(text, _BORROWED_TOKENS, SlopClass.BORROWED_TOKEN,
                            "delete — an image-model token, not art direction",
                            opening)
    findings += _scan_words(text, _FEEL_SUFFIX, SlopClass.FEEL_SUFFIX,
                            "name the physical cause of the feeling", opening)

    for match in _NEGATION_RE.finditer(text):
        findings.append(SlopFinding(
            slop_class=SlopClass.NEGATION,
            text=match.group(0),
            position=match.start(),
            in_opening=match.start() < opening,
            repair=("naming a flaw plants it — lock the positive instead "
                    "(\"hands rest still on the table\")")))

    for match in _STACK_RE.finditer(text):
        words = [match.group(i).lower() for i in (1, 2, 3)]
        if sum(1 for w in words if w in _EMPTY_EVALUATORS or w in _FEEL_SUFFIX) < 2:
            continue
        findings.append(SlopFinding(
            slop_class=SlopClass.ADJECTIVE_STACK,
            text=match.group(0),
            position=match.start(),
            in_opening=match.start() < opening,
            repair="three synonyms make one weak claim — keep the single detail"))

    for phrase, safer in IP_SURFACES.items():
        for match in _phrase_pattern(phrase).finditer(text):
            findings.append(SlopFinding(
                slop_class=SlopClass.IP_RISK,
                text=match.group(0),
                position=match.start(),
                in_opening=match.start() < opening,
                repair=f"someone else's identity or mark — use {safer}"))

    for phrase, safer in FILTER_SURFACES.items():
        for match in _phrase_pattern(phrase).finditer(text):
            findings.append(SlopFinding(
                slop_class=SlopClass.FILTER_RISK,
                text=match.group(0),
                position=match.start(),
                in_opening=match.start() < opening,
                repair=f"image filters bounce this — keep the beat, say {safer}"))

    if motion:
        findings += _scan_motion(text, opening)

    if _is_tag_salad(text):
        findings.append(SlopFinding(
            slop_class=SlopClass.TAG_SALAD,
            text=text[:60] + ("…" if len(text) > 60 else ""),
            position=0,
            in_opening=True,
            repair=("rewrite as a shooting brief: one sentence per element — "
                    "subject and action, camera, light, sound")))

    # De-duplicate overlapping hits at the same position, keeping the first
    # class that claimed it, then order by position so a reader walks the
    # prompt front to back.
    seen: set[tuple[int, str]] = set()
    unique: list[SlopFinding] = []
    for f in sorted(findings, key=lambda f: (f.position, f.slop_class.value)):
        key = (f.position, f.text.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


def blocking_findings(findings: list[SlopFinding], *,
                      max_total: int = 2) -> list[SlopFinding]:
    """The subset that should stop a frame from being generated.

    Four rules:
      * IP_RISK blocks wherever it sits and whatever else is clean — a likeness
        or a mark is not a quality problem, it is a claim after upload;
      * FILTER_RISK never blocks on its own: those beats are legitimate (this
        repo ships a horror channel), the finding just carries the production
        wording that survives the provider's filter;
      * ANY other slop in the opening clause blocks — the most expensive real
        estate in the prompt, spent on nothing;
      * NEGATION and TAG_SALAD block wherever they sit, because neither is a
        position effect. "no blur" plants blur from anywhere in the prompt, and
        a keyword dump has no action or time axis to give a video model at all;
      * more than `max_total` hits anywhere blocks, because at that density the
        prompt describes a mood rather than a picture.

    Everything else is reported and left alone: one hedge word deep in a
    constraint tail is not worth a retake.
    """
    always = {SlopClass.NEGATION, SlopClass.TAG_SALAD, SlopClass.IP_RISK,
              SlopClass.LAZY_MOTION}
    hard = [
        f for f in findings
        if f.slop_class in always
        or (f.in_opening and f.slop_class is not SlopClass.FILTER_RISK)
    ]
    if hard:
        return hard
    # Density counts style slop only: three legitimate horror surfaces in one
    # prompt is a horror prompt, not a bad one.
    style = [f for f in findings if f.slop_class is not SlopClass.FILTER_RISK]
    if len(style) > max_total:
        return style
    return []


def summarize(findings: list[SlopFinding]) -> str:
    """One line per finding, for a repair prompt or an operator note."""
    return "\n".join(f"- {f.describe()}" for f in findings)
