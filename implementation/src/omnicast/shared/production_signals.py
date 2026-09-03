"""What a video would take to MAKE — inferred from its own title/description.

WHY THIS EXISTS (P0.1 group 3, strategic review §3.3):

`StackProfile.unsupported_requirements` is matched against
`raw_metrics["production_requirements"]`, and a hit is a hard zero on stack fit.
No scanner ever wrote that key either, so the veto could not fire on a real run:
OmniCast was free to auto-approve a topic whose winning format is a face-to-face
interview it has no way to shoot.

DESIGN CONSTRAINT — FALSE POSITIVES ARE EXPENSIVE. A hit is a hard veto, not a
nudge. An operator who watches good topics get vetoed for the wrong reason stops
configuring the feature, which is worse than not having it. So:

* patterns are multi-word phrases wherever the single word is ambiguous
  ("livestream", not "live" — "How to live on $2,000 a month" is a normal topic);
* every pattern is anchored on word boundaries;
* the module returns an empty set rather than guessing, and an empty set means
  "no requirement detected", which the scorer treats as no evidence either way.

The tags are the vocabulary `StackProfile.unsupported_requirements` uses.
"""

from __future__ import annotations

import re

# tag -> patterns that imply it. Ordered only for readability.
_SIGNALS: dict[str, tuple[str, ...]] = {
    # Someone must sit in front of a camera and be a person.
    "face_cam": (
        r"\bmy reaction\b", r"\breacting to\b", r"\breaction video\b",
        r"\bface reveal\b", r"\bday in my life\b", r"\bvlog(?:s|ging)?\b",
        r"\bstory ?time\b", r"\bq ?& ?a\b", r"\bask me anything\b",
    ),
    # A second human being, live, in conversation.
    "interview": (
        # NOT the bare word. "The truth about interviews for a job at 60" is a
        # topic ABOUT interviews, not a video that requires conducting one, and
        # a hard veto cannot afford to confuse the two.
        r"\binterview with\b", r"\binterviews? (?:with|of)\b",
        r"\b(?:exclusive|full|rare) interview\b", r"\binterviewing [a-z]",
        r"\bsits? down with\b", r"\bin conversation with\b",
        r"\bpodcast with\b", r"\bfireside chat\b",
    ),
    # Footage shot at a place, by us.
    "on_location": (
        r"\bon location\b", r"\bwe visited\b", r"\bi visited\b",
        r"\bwalking tour\b", r"\bfactory tour\b", r"\bbehind the scenes at\b",
        r"\bcome with me to\b",
    ),
    # Real-time broadcast material.
    "live_footage": (
        r"\blive ?stream(?:s|ed|ing)?\b", r"\bgoing live\b", r"\blive q ?& ?a\b",
        r"\bwatch (?:me|us) live\b", r"\bfull match\b", r"\bfull game\b",
    ),
    # A physical object must be handled on camera.
    "in_person_demo": (
        r"\bunboxing\b", r"\bhands[- ]on (?:review|with)\b", r"\bteardown\b",
        r"\btaste test\b", r"\bi (?:built|cooked|assembled) (?:this|it)\b",
    ),
    # We record a screen. OmniCast CAN do this — it is here so a channel that
    # cannot may declare it, and so the tag vocabulary is complete.
    "screen_capture": (
        r"\bscreen ?(?:share|recording)\b", r"\bstep[- ]by[- ]step in\b",
        r"\bsoftware (?:tutorial|walkthrough)\b",
    ),
}

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    tag: tuple(re.compile(p, re.I) for p in pats) for tag, pats in _SIGNALS.items()
}

ALL_TAGS = frozenset(_COMPILED)


def infer_production_requirements(title: str, description: str = "") -> set[str]:
    """Production capabilities this video's format appears to require.

    Empty set = nothing detected. That is NOT "no requirements exist"; it is
    "this cheap text test found none", and the scorer treats it as no evidence.
    """
    # `str()` on both sides: the title was already coerced by the f-string and
    # the description was not, so a non-string description raised while a
    # non-string title did not — from the same call site.
    haystack = f"{str(title or '')}\n{str(description or '')[:500]}"
    if not haystack.strip():
        return set()
    return {tag for tag, patterns in _COMPILED.items()
            if any(p.search(haystack) for p in patterns)}
