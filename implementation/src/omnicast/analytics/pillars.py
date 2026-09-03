"""Content pillars — which recurring theme a video belongs to.

WHY (strategic review §4.2, §4.5, §4.6):

Competitor intelligence is keyed by `niche`, which is far too broad: "finance"
covers a 25-year-old learning about index funds and a 65-year-old worried about
outliving savings, and one thumbnail playbook cannot serve both. The review asks
for a scope of
`channel/archetype + audience segment + format + market + content pillar`,
and the pillar is the piece the system had no notion of at all. Schedule
analysis needs it too — "cadence per pillar" is meaningless without one.

DESIGN: DECLARED, NOT DISCOVERED.

Pillars are configured per channel, and classification is keyword matching with
the matched keywords returned as evidence. No LLM, no clustering, no inference.
That is a deliberate limit:

  * an LLM classifier costs a call per video and cannot be audited after the
    fact — you get a label with no way to ask why;
  * a clustering classifier invents pillars that nobody agreed to, and they
    then key the playbook store, so a shift in clustering silently reshuffles
    which channel reads which playbook.

`suggest_pillars` exists for the bootstrap problem — it proposes candidates from
real titles — but its output is explicitly labelled as a proposal for a human,
never written back automatically.

An unconfigured channel returns `UNCONFIGURED`, never a guess. Downstream must
degrade (fall back to the broader scope) rather than pretend to a precision the
configuration does not support.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from omnicast.shared.topic_coverage import content_tokens

# No pillar list configured for this channel.
UNCONFIGURED = "unconfigured"
# Pillars are configured, but this video matched none of them. Distinct from
# UNCONFIGURED on purpose: "we looked and it fits nothing" and "we never looked"
# call for different actions.
UNCLASSIFIED = "unclassified"


def _boundary(word: str) -> str:
    """Word-boundary pattern that survives keywords ending in punctuation."""
    escaped = re.escape(word.lower())
    left = r"\b" if word[:1].isalnum() else ""
    right = r"\b" if word[-1:].isalnum() else ""
    return f"{left}{escaped}{right}"


@dataclass(frozen=True)
class Pillar:
    pillar_id: str
    name: str = ""
    keywords: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, raw: dict) -> "Pillar | None":
        pillar_id = str((raw or {}).get("id") or (raw or {}).get("pillar_id") or "").strip()
        if not pillar_id:
            return None
        keywords = tuple(
            str(k).strip().lower() for k in (raw.get("keywords") or []) if str(k).strip()
        )
        return cls(pillar_id=pillar_id, name=str(raw.get("name") or pillar_id),
                   keywords=keywords)


@dataclass(frozen=True)
class PillarMatch:
    pillar_id: str
    evidence: tuple[str, ...] = ()
    score: int = 0
    # Every pillar that matched at all, strongest first. A video sitting on the
    # boundary between two pillars is a real and useful signal; reporting only
    # the winner hides it.
    alternatives: tuple[str, ...] = field(default=())

    @property
    def is_classified(self) -> bool:
        return self.pillar_id not in {UNCONFIGURED, UNCLASSIFIED}

    def as_dict(self) -> dict:
        return {
            "pillar_id": self.pillar_id,
            "evidence": list(self.evidence),
            "score": self.score,
            "alternatives": list(self.alternatives),
        }


def load_pillars(raw_pillars) -> list[Pillar]:
    pillars = []
    for raw in raw_pillars or []:
        pillar = Pillar.from_config(raw) if isinstance(raw, dict) else None
        if pillar:
            pillars.append(pillar)
    return pillars


def classify_pillar(title: str, description: str, pillars: list[Pillar]) -> PillarMatch:
    """Assign one pillar, with the keywords that caused it.

    The title is weighted double: a keyword in the title is what the video is
    about, the same keyword 300 words into a description is often boilerplate
    (channel blurb, affiliate list, standing disclaimer)."""
    if not pillars:
        return PillarMatch(UNCONFIGURED)

    title_text = (title or "").lower()
    body_text = (description or "")[:1000].lower()

    scored: list[tuple[int, int, Pillar, list[str]]] = []
    for pillar in pillars:
        hits: list[str] = []
        title_hits = body_hits = 0
        for keyword in pillar.keywords:
            pattern = _boundary(keyword)
            if re.search(pattern, title_text):
                title_hits += 1
                hits.append(f"title:{keyword}")
            elif re.search(pattern, body_text):
                body_hits += 1
                hits.append(f"description:{keyword}")
        if title_hits or body_hits:
            scored.append((title_hits, body_hits, pillar, hits))

    if not scored:
        return PillarMatch(UNCLASSIFIED)

    # The title DOMINATES — it is not merely worth more points. Two boilerplate
    # keywords in a description ("subscribe for retirement and pension content")
    # must not outvote the one keyword in the title that says what the video is
    # about, which is what any additive weighting eventually allows.
    # Ties break on pillar_id so the answer never depends on config ordering.
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].pillar_id))
    title_hits, body_hits, best, evidence = scored[0]
    alternatives = tuple(p.pillar_id for _t, _b, p, _h in scored[1:])
    return PillarMatch(best.pillar_id, tuple(evidence),
                       title_hits * 2 + body_hits, alternatives)


def suggest_pillars(titles: list[str], *, top_n: int = 6, min_count: int = 3
                    ) -> list[dict]:
    """Propose candidate pillars from real titles — for a human to confirm.

    Returned as proposals, never written back. Auto-adopting these would let a
    clustering wobble re-key the playbook store between two runs, so that a
    channel silently starts reading a different playbook than it read yesterday.
    """
    counts: Counter[str] = Counter()
    for title in titles or []:
        counts.update(content_tokens(title))
    return [
        {"suggested_keyword": token, "titles_matched": count,
         "status": "proposal — requires operator confirmation"}
        for token, count in counts.most_common(top_n)
        if count >= min_count
    ]
