"""Deterministic title-shape classification.

WHY THIS LIVES HERE (P0.1 group 2, strategic review §4.8):

`youtube_scanner._classify_title` was already a pure, deterministic, LLM-free
function — but it sat inside a module that pulls in httpx and the scanner
class. Cohort matching needs the same taxonomy to control for FORMAT when it
pairs a winner with a control: if the winner is a "5 mistakes" listicle and the
control is a plain statement title, then any difference the contrast prompt
finds may be nothing but the format difference we ourselves introduced.

So the taxonomy moved to a dependency-free module. `youtube_scanner` re-exports
it under the old private name, so nothing that already imported it changes.

The tags are intentionally coarse and overlapping — this is a cheap PROXY for
format, not a pillar classifier. A real pillar classifier is explicitly out of
scope for P0 (see docs/HANDOFF_MASTER.md §5).
"""

from __future__ import annotations

import re

# Order matters only for readability; a title carries every tag it matches.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("number", re.compile(r"\b\d+\b")),                     # "5 Mistakes", "10 Foods"
    ("question", re.compile(r"\?")),                        # "Why is X..."
    ("how_to", re.compile(r"\b(how to|how i)\b", re.I)),    # "How to..."
    ("second_person", re.compile(r"\b(you|your)\b", re.I)),  # "You're doing X wrong"
    ("warning", re.compile(r"\b(stop|never|don't|avoid|mistake|wrong)\b", re.I)),
    ("insider", re.compile(r"\b(secret|truth|real|hidden|nobody|they won't)\b", re.I)),
)

# Applied when nothing else matched. It is a real class, not a failure code:
# "plain declarative headline" is a format like any other.
FALLBACK_TAG = "statement"


def classify_title(title: str) -> list[str]:
    """Tag title structure — used to learn what formats win in this niche."""
    patterns = [tag for tag, rx in _RULES if rx.search(str(title or ""))]
    return patterns or [FALLBACK_TAG]


def title_format_key(title: str) -> frozenset[str]:
    """Hashable format signature, for matching one title's shape against another."""
    return frozenset(classify_title(title))


def formats_match(a: str, b: str) -> bool:
    """Whether two titles are close enough in shape to be a controlled pair.

    Deliberately NOT set equality. Real titles carry 1-4 overlapping tags, and
    demanding an exact match would reject nearly every candidate control — which
    would trade a format confound for a much worse one: no control at all, on
    almost every winner. The rule is "shares the dominant shape":

      * both plain statements                            -> match
      * one plain statement, one tagged                  -> no match
      * otherwise: they share at least one non-fallback tag
    """
    fa, fb = title_format_key(a), title_format_key(b)
    plain_a, plain_b = fa == {FALLBACK_TAG}, fb == {FALLBACK_TAG}
    if plain_a or plain_b:
        return plain_a and plain_b
    return bool(fa & fb)
