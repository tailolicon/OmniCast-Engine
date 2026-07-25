"""Production mode router — what KIND of visual does this scene need?

WHY (strategic review §7, P0 in §15):

The pipeline is strong at exactly one production grammar: voiceover + stock
footage + AI images + captions + music. Real channels use many, and nothing in
the system asks the question the review poses directly:

    Does this scene need stock? A real photo? A chart? An AI reconstruction?
    Character animation? A screen capture? A talking head? Or no new visual at
    all — just a hold?

`channel_styles.enforce_policy` already coerces a finished storyboard towards a
channel's preferred SOURCE. That is a different question: it decides where a
picture comes from, after something has already decided that a picture is what
this scene needs. This module decides the second thing, and does it before the
storyboard is committed.

THREE PROPERTIES THAT MATTER MORE THAN CLASSIFICATION ACCURACY:

1. IT ROUTES ONLY TO MODES WE CAN ACTUALLY PRODUCE. A router that returns
   `talking_head` to a pipeline with no presenter has not helped anybody; it has
   moved the failure downstream to whatever renders scenes. Unavailable modes
   fall back along a declared chain, and the fallback is RECORDED with the
   reason — a substituted visual that looks chosen is how a channel drifts away
   from its own format without anyone noticing.

2. IT SAYS WHEN IT IS GUESSING. `confidence` is low when the decision came from
   the default branch rather than from a signal, and the signal that fired is
   attached. A storyboard reviewer needs to know which scenes were classified
   and which were merely defaulted.

3. IT FLAGS WHAT NEEDS DISCLOSURE. A dramatised reconstruction of a real event,
   or an AI image standing in for real evidence, is exactly the material that
   requires an AI-generated-content disclosure. The router marks it rather than
   leaving it to be noticed at upload time.

WHAT THIS IS NOT: an animation system. §7.1 is explicit that character rigs,
lip sync, expression libraries and timing are a subsystem, not a prompt tweak.
`ANIMATION` is therefore routable only when a channel declares the capability,
and otherwise falls back with a note saying so instead of generating a pile of
AI frames and crossfading them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── the eight modes (§15) plus the hold the review asks about ────────────────
REAL_EVIDENCE = "real_evidence"
STOCK = "stock"
AI_ILLUSTRATION = "ai_illustration"
RECONSTRUCTION = "reconstruction"
INFOGRAPHIC = "infographic"
ANIMATION = "animation"
SCREEN_CAPTURE = "screen_capture"
TALKING_HEAD = "talking_head"
SILENCE_HOLD = "silence_hold"

ALL_MODES = (REAL_EVIDENCE, STOCK, AI_ILLUSTRATION, RECONSTRUCTION, INFOGRAPHIC,
             ANIMATION, SCREEN_CAPTURE, TALKING_HEAD, SILENCE_HOLD)

# What each mode needs from the operation. Matched against the same capability
# vocabulary as `shared.production_signals`, so a channel declares its limits
# once and both the topic scorer and the router respect them.
MODE_REQUIREMENTS: dict[str, frozenset[str]] = {
    REAL_EVIDENCE: frozenset({"archival_licence"}),
    STOCK: frozenset(),
    AI_ILLUSTRATION: frozenset(),
    RECONSTRUCTION: frozenset(),
    INFOGRAPHIC: frozenset(),
    ANIMATION: frozenset({"character_animation"}),
    SCREEN_CAPTURE: frozenset({"screen_capture"}),
    TALKING_HEAD: frozenset({"face_cam"}),
    SILENCE_HOLD: frozenset(),
}

# Where each mode goes when we cannot produce it. Ordered, and it always
# terminates at STOCK, which needs nothing.
FALLBACKS: dict[str, tuple[str, ...]] = {
    REAL_EVIDENCE: (RECONSTRUCTION, AI_ILLUSTRATION, STOCK),
    ANIMATION: (AI_ILLUSTRATION, STOCK),
    SCREEN_CAPTURE: (INFOGRAPHIC, AI_ILLUSTRATION, STOCK),
    TALKING_HEAD: (STOCK, AI_ILLUSTRATION),
    RECONSTRUCTION: (AI_ILLUSTRATION, STOCK),
    INFOGRAPHIC: (AI_ILLUSTRATION, STOCK),
    AI_ILLUSTRATION: (STOCK,),
    STOCK: (AI_ILLUSTRATION,),
    SILENCE_HOLD: (),
}

# Modes that depict something that did not happen in front of a camera. When the
# scene is about a REAL event, that combination is what an AI-content disclosure
# exists for.
SYNTHETIC_MODES = frozenset({AI_ILLUSTRATION, RECONSTRUCTION, ANIMATION})

# How the router's answer maps onto the storyboard's existing vocabulary, so
# `channel_styles.enforce_policy` and the renderers keep working unchanged.
VISUAL_TYPE: dict[str, str] = {
    REAL_EVIDENCE: "stock_video",
    STOCK: "stock_video",
    AI_ILLUSTRATION: "generated_image",
    RECONSTRUCTION: "generated_image",
    INFOGRAPHIC: "generated_image",
    ANIMATION: "generated_image",
    SCREEN_CAPTURE: "generated_image",
    TALKING_HEAD: "stock_video",
    SILENCE_HOLD: "hold",
}


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.I) for p in patterns)


# Ordered: the first rule that fires wins. Order encodes priority, and priority
# is a real decision — a scene that quotes a statistic AND names a year is a
# chart, not a reconstruction.
_RULES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (INFOGRAPHIC, _rx(
        r"\d+\s?%", r"\bpercent\b", r"[$€£]\s?\d", r"\b\d+\s?(?:million|billion|trillion)\b",
        r"\bcompared (?:to|with)\b", r"\bversus\b", r"\bvs\.?\b", r"\bratio\b",
        r"\bthe (?:chart|graph|numbers|data) shows?\b", r"\bbreakdown of\b",
        r"\bgrew by\b", r"\bfell by\b", r"\btimes (?:more|less|higher|lower)\b")),
    (SCREEN_CAPTURE, _rx(
        r"\bclick\b", r"\bthe (?:app|dashboard|settings|menu|website|browser)\b",
        r"\blog ?in\b", r"\bthe form\b", r"\bon your screen\b", r"\bthis tool\b",
        r"\bopen the\b.*\b(?:tab|page|panel)\b")),
    (REAL_EVIDENCE, _rx(
        r"\baccording to\b", r"\bthe (?:study|report|filing|ruling|transcript)\b",
        r"\bresearchers? (?:found|say)\b", r"\bthe documents? shows?\b",
        r"\bon record\b", r"\bthe original (?:photo|footage|recording)\b",
        r"\bcourt (?:filing|record)\b", r"\bofficial (?:data|figures)\b")),
    (RECONSTRUCTION, _rx(
        r"\bin (?:1[0-9]{3}|20[0-4][0-9])\b", r"\bcenturies ago\b", r"\bancient\b",
        r"\bprehistoric\b", r"\bimagine\b", r"\bpicture this\b", r"\bwhat it (?:was|would have been) like\b",
        r"\bback then\b", r"\bthousands of years\b", r"\bthe night (?:it|he|she|they)\b")),
    (ANIMATION, _rx(
        r"\bour (?:character|hero)\b", r"\bhe (?:leaps|dashes|tumbles)\b",
        r"\bcartoon\b", r"\bthe little\b.*\bwalks (?:in|over)\b",
        r"\bcomic (?:panel|strip)\b")),
    (TALKING_HEAD, _rx(
        r"\bon camera\b", r"\bi'?m (?:standing|sitting) here\b",
        r"\blet me (?:show|tell) you (?:personally|myself)\b", r"\bpiece to camera\b")),
    (STOCK, _rx(
        r"\b(?:a|the) (?:city|street|office|hospital|forest|beach|kitchen|train)\b",
        r"\bpeople walking\b", r"\baerial\b", r"\btime ?lapse\b", r"\bb-?roll\b",
        r"\bestablishing shot\b")),
)

# A beat with no new subject at all: a rhetorical pause, a one-word line.
_HOLD = _rx(r"^\s*[.…]{2,}\s*$", r"^\s*\(?(?:beat|pause|silence)\)?\s*$")


@dataclass
class SceneRoute:
    scene_index: int
    mode: str
    requested_mode: str
    confidence: float
    evidence: str = ""
    fallback_reason: str = ""
    requires_disclosure: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def was_substituted(self) -> bool:
        return self.mode != self.requested_mode

    @property
    def visual_type(self) -> str:
        return VISUAL_TYPE[self.mode]

    def as_dict(self) -> dict:
        return {
            "scene_index": self.scene_index,
            "mode": self.mode,
            "requested_mode": self.requested_mode,
            "was_substituted": self.was_substituted,
            "fallback_reason": self.fallback_reason,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "requires_disclosure": self.requires_disclosure,
            "visual_type": self.visual_type,
            "notes": list(self.notes),
        }


def classify_scene(text: str) -> tuple[str, float, str]:
    """(mode, confidence, evidence) from the scene's narration and visual note.

    Confidence is 0.4 for the default branch, because "no rule fired" is not
    evidence for illustration — it is evidence of nothing, and a storyboard
    reviewer has to be able to see which scenes were merely defaulted."""
    body = (text or "").strip()
    if not body:
        return AI_ILLUSTRATION, 0.0, ""
    if any(p.search(body) for p in _HOLD):
        return SILENCE_HOLD, 0.9, "explicit beat/pause"

    for mode, patterns in _RULES:
        for pattern in patterns:
            match = pattern.search(body)
            if match:
                return mode, 0.75, match.group(0)
    return AI_ILLUSTRATION, 0.4, ""


def route_scene(
    index: int,
    text: str,
    *,
    capabilities: set[str] | frozenset[str] | None = None,
    depicts_real_events: bool = False,
) -> SceneRoute:
    """Classify one scene and route it to a mode we can actually produce."""
    available = set(capabilities or set())
    mode, confidence, evidence = classify_scene(text)
    requested = mode
    notes: list[str] = []
    reason = ""

    missing = MODE_REQUIREMENTS[mode] - available
    if missing:
        chain = FALLBACKS.get(mode, (STOCK,))
        for candidate in chain:
            if not (MODE_REQUIREMENTS[candidate] - available):
                reason = (
                    f"{requested} needs {sorted(missing)}, which this operation "
                    f"has not declared — substituted {candidate}")
                mode = candidate
                break
        else:
            reason = (
                f"{requested} needs {sorted(missing)} and no fallback was "
                f"available either — left as {requested}, which WILL fail to render")
            notes.append("unroutable scene: declare a capability or rewrite the beat")
        if mode == RECONSTRUCTION and requested == REAL_EVIDENCE:
            notes.append(
                "a reconstruction is standing in for real evidence — the script "
                "must not describe it as footage of the actual event")

    disclosure = bool(depicts_real_events and mode in SYNTHETIC_MODES)
    if disclosure:
        notes.append(
            "synthetic visual depicting a real event — requires AI-content "
            "disclosure at upload")

    if confidence <= 0.4 and mode == AI_ILLUSTRATION:
        notes.append(
            "defaulted: no production signal fired, so this is the fallback "
            "grammar rather than a decision")

    return SceneRoute(scene_index=index, mode=mode, requested_mode=requested,
                      confidence=confidence, evidence=evidence,
                      fallback_reason=reason, requires_disclosure=disclosure,
                      notes=notes)


def route_storyboard(
    scenes: list[dict],
    *,
    capabilities: set[str] | frozenset[str] | None = None,
    depicts_real_events: bool = False,
) -> list[SceneRoute]:
    """Route a whole board. Each scene dict may carry `narration`/`text` and
    `visual`/`image_prompt`; both are read, because the production grammar is
    often stated in the visual note and the evidence in the narration."""
    routes: list[SceneRoute] = []
    for index, scene in enumerate(scenes or []):
        if not isinstance(scene, dict):
            routes.append(route_scene(index, "", capabilities=capabilities))
            continue
        parts = [str(scene.get(key) or "") for key in
                 ("narration", "text", "voiceover", "visual", "image_prompt",
                  "stock_query")]
        routes.append(route_scene(
            index, "\n".join(p for p in parts if p),
            capabilities=capabilities,
            depicts_real_events=depicts_real_events))
    return routes


def summarise(routes: list[SceneRoute]) -> dict:
    """The grammar of the video, and how much of it we actually chose."""
    counts: dict[str, int] = {}
    for route in routes:
        counts[route.mode] = counts.get(route.mode, 0) + 1
    substituted = [r.as_dict() for r in routes if r.was_substituted]
    defaulted = sum(1 for r in routes if r.confidence <= 0.4)
    return {
        "scenes": len(routes),
        "modes": counts,
        "substituted": substituted,
        "substituted_count": len(substituted),
        "defaulted_count": defaulted,
        "classified_ratio": (round(1 - defaulted / len(routes), 3) if routes else 0.0),
        "requires_disclosure": any(r.requires_disclosure for r in routes),
    }


def capabilities_from_channel(channel) -> set[str]:
    """Which production modes this channel has declared it can deliver.

    Derived from the same `supported_production` list the topic scorer reads, so
    an operator declares a capability once. `screen_capture` is granted by
    default because OmniCast can record a screen; nothing else is, because
    nothing else is true of the engine by default."""
    declared = {str(x).strip().lower()
                for x in (getattr(channel, "supported_production", None) or [])
                if str(x).strip()}
    return declared | {"screen_capture"}
