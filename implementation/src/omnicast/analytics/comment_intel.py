"""What competitor audiences actually say — read, not counted.

WHY (strategic review §4.4):

`fetch_comments` was fixed in P0 and now returns real comment text. Nothing read
it. The scanner still uses only the comment COUNT, which answers "how much
engagement" and none of the questions the review asks:

  * which part did viewers like;
  * what did they not understand;
  * what did they push back on;
  * which questions went unanswered;
  * what sequel are they asking for;
  * what words does this audience actually use;
  * where is trust breaking down (clickbait, undisclosed promotion, bad facts).

DETERMINISTIC FIRST. Classification here is phrase matching, so every signal
comes back with the comment that produced it. A bucket you cannot trace to a
quote is an opinion with a number next to it.

WEIGHTING. A comment with 400 likes is not one viewer's opinion and a comment
with 0 likes is not nothing. Counts are reported BOTH ways — `comments` and
`weighted` — because a single popular objection and forty quiet ones are
different situations and one number cannot express both.

WHAT THIS SAMPLE IS NOT. YouTube returns comments by relevance, replies are
partial, and commenters are a tiny, self-selected slice of viewers. `sample`
carries the size and ordering so no reader mistakes this for the audience.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from omnicast.shared.topic_coverage import content_tokens

# Signals, in the order a reader should care about them. Patterns are phrases,
# not single words, wherever the single word is ambiguous ("wrong" appears in
# "what am I doing wrong?" as often as in "you are wrong").
_PATTERNS: dict[str, tuple[str, ...]] = {
    "confusion": (
        r"\bi (?:don'?t|do not) (?:understand|get) ",
        r"\bwhat do(?:es)? (?:you|he|she|this|that) mean\b",
        r"\bcan (?:you|someone) explain\b", r"\bi'?m confused\b",
        r"\bwent over my head\b", r"\bstill (?:don'?t|do not) understand\b",
        r"\bnot clear\b",
    ),
    "objection": (
        r"\bthis is (?:wrong|false|incorrect|misleading)\b",
        r"\bactually,? (?:it'?s|that'?s|this is)\b", r"\bi disagree\b",
        r"\bnot true\b", r"\bthat'?s not how\b", r"\byou'?re wrong\b",
        r"\bbad advice\b", r"\bdoesn'?t work (?:for|in)\b",
    ),
    "distrust": (
        r"\bclickbait\b", r"\bscam\b", r"\bsponsored\b", r"\bshill\b",
        r"\bwhere'?s? (?:the|your) source\b", r"\bsource\?\b", r"\bcite\b",
        r"\bmisinformation\b", r"\bfear ?monger", r"\bselling (?:us|me) something\b",
    ),
    "sequel_request": (
        r"\b(?:please )?(?:make|do) a (?:video|part|follow[- ]?up) (?:on|about)\b",
        r"\bpart (?:2|two|ii)\b", r"\bcan you cover\b", r"\bwould love to see\b",
        r"\bnext video (?:on|about)\b", r"\bmore (?:videos )?(?:on|about) this\b",
    ),
    "praise_specific": (
        r"\bthe part (?:where|about)\b", r"\bat \d{1,2}:\d{2}\b",
        r"\bthank you for (?:explaining|breaking|covering)\b",
        r"\bfinally someone\b", r"\bbest explanation\b",
    ),
}
_COMPILED = {name: tuple(re.compile(p, re.I) for p in pats)
             for name, pats in _PATTERNS.items()}

SIGNALS = tuple(_COMPILED)

_QUESTION = re.compile(r"\?\s*$|\?\s")
# Timestamps are the single most useful thing in a comment section: they say
# WHERE in the video something landed.
_TIMESTAMP = re.compile(r"\b(\d{1,2}):(\d{2})\b")


@dataclass
class CommentSignal:
    name: str
    comments: int = 0
    weighted: int = 0  # sum of (1 + like_count)
    examples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"signal": self.name, "comments": self.comments,
                "weighted": self.weighted, "examples": list(self.examples)}


@dataclass
class CommentIntel:
    sample: dict = field(default_factory=dict)
    signals: list[CommentSignal] = field(default_factory=list)
    unanswered_questions: list[dict] = field(default_factory=list)
    referenced_timestamps: list[dict] = field(default_factory=list)
    audience_vocabulary: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def signal(self, name: str) -> CommentSignal | None:
        return next((s for s in self.signals if s.name == name), None)

    def as_dict(self) -> dict:
        return {
            "sample": dict(self.sample),
            "signals": [s.as_dict() for s in self.signals],
            "unanswered_questions": list(self.unanswered_questions),
            "referenced_timestamps": list(self.referenced_timestamps),
            "audience_vocabulary": list(self.audience_vocabulary),
            "notes": list(self.notes),
        }


def _seconds(match: re.Match) -> int:
    return int(match.group(1)) * 60 + int(match.group(2))


def analyse_comments(
    comments,
    *,
    max_examples: int = 3,
    vocabulary_size: int = 15,
    min_vocabulary_count: int = 3,
) -> CommentIntel:
    """Turn a comment list (or a `CommentFetch`) into traceable signals."""
    intel = CommentIntel()
    rows = list(comments or [])

    status = getattr(comments, "status", "ok")
    intel.sample = {
        "comments": len(rows),
        "status": status,
        "replies_included": sum(1 for c in rows if c.get("is_reply")),
        "ordering": "as returned by the API (relevance), not a random sample",
        "caveat": (
            "Commenters are a small, self-selected slice of viewers. Treat every "
            "count below as evidence about COMMENTERS, never about the audience."
        ),
    }

    if status != "ok":
        intel.notes.append(
            f"comment fetch did not succeed ({status}) — an empty result here is "
            "a fetch outcome, not a silent audience")
        return intel
    if not rows:
        intel.notes.append("no comments returned")
        return intel

    tallies = {name: CommentSignal(name) for name in SIGNALS}
    vocabulary: Counter[str] = Counter()
    timestamps: Counter[int] = Counter()

    # Threads whose top-level comment got a reply are treated as answered. This
    # is a floor, not a truth: a reply may be another viewer, or "same question".
    answered_threads = {c.get("thread_id") for c in rows if c.get("is_reply")}

    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        weight = 1 + int(row.get("like_count", 0) or 0)
        vocabulary.update(content_tokens(text))

        for name, patterns in _COMPILED.items():
            if any(p.search(text) for p in patterns):
                signal = tallies[name]
                signal.comments += 1
                signal.weighted += weight
                if len(signal.examples) < max_examples:
                    signal.examples.append(text[:240])

        for match in _TIMESTAMP.finditer(text):
            timestamps[_seconds(match)] += weight

        if _QUESTION.search(text) and not row.get("is_reply"):
            if row.get("thread_id") not in answered_threads and \
                    not int(row.get("reply_count", 0) or 0):
                intel.unanswered_questions.append({
                    "text": text[:240],
                    "like_count": int(row.get("like_count", 0) or 0),
                    "comment_id": row.get("comment_id", ""),
                })

    intel.unanswered_questions.sort(key=lambda q: -q["like_count"])
    intel.unanswered_questions = intel.unanswered_questions[:20]

    intel.signals = sorted(
        (s for s in tallies.values() if s.comments),
        key=lambda s: (-s.weighted, s.name),
    )
    intel.referenced_timestamps = [
        {"second": second, "mm_ss": f"{second // 60}:{second % 60:02d}", "weight": weight}
        for second, weight in timestamps.most_common(10)
    ]
    intel.audience_vocabulary = [
        {"term": term, "comments": count}
        for term, count in vocabulary.most_common(vocabulary_size)
        if count >= min_vocabulary_count
    ]

    if not intel.signals:
        intel.notes.append(
            "no signal phrase matched — the comment section may be short, "
            "non-English, or genuinely uneventful; it is NOT evidence of "
            "agreement")
    return intel
