"""Channel thesis and content architecture (strategic review §11.1, §11.2).

§11.1 asks five questions the system has never been able to answer for any
channel: who is this for, what is the unique promise, why do people come back,
what is the moat, which format does it own long-term.

§11.2 asks for a managed architecture rather than a queue of topics: core and
supporting pillars, an experimental pillar, recurring and seasonal series,
tentpole videos, an evergreen library, sequels.

DECLARED, NOT GENERATED. An LLM can write a plausible thesis for any channel in
four seconds, and that is exactly the problem: it would agree with whatever the
channel is already doing, so it could never be evidence that the channel has
drifted. A thesis is a COMMITMENT an operator makes, which is what makes
"you published twelve videos that serve nobody in this thesis" a finding.

So this module reads what was declared, tells you what is missing, and measures
the DRIFT between the declaration and the library. It never fills a blank.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Pillar roles from §11.2. A pillar with no role declared is not assumed to be
# core: "we never said" and "this is the channel's backbone" are different, and
# the second one changes how much of the calendar it is entitled to.
CORE = "core"
SUPPORTING = "supporting"
EXPERIMENTAL = "experimental"
UNDECLARED = "undeclared"
PILLAR_ROLES = (CORE, SUPPORTING, EXPERIMENTAL, UNDECLARED)

# The five §11.1 questions, in the order the review asks them.
THESIS_QUESTIONS: dict[str, str] = {
    "audience": "Who does this channel exist to serve?",
    "promise": "What is its unique promise?",
    "return_reason": "Why does a viewer come back?",
    "moat": "What stops a competitor from copying it?",
    "owned_format": "Which format does it own long-term?",
}


@dataclass(frozen=True)
class PillarRole:
    pillar_id: str
    role: str = UNDECLARED
    name: str = ""

    def as_dict(self) -> dict:
        return {"pillar_id": self.pillar_id, "role": self.role, "name": self.name}


@dataclass
class ChannelThesis:
    """The five answers, plus an honest account of which are missing."""

    channel_id: str = ""
    answers: dict[str, str] = field(default_factory=dict)

    @property
    def missing(self) -> list[str]:
        return [key for key in THESIS_QUESTIONS
                if not str(self.answers.get(key, "")).strip()]

    @property
    def is_declared(self) -> bool:
        return not self.missing

    @property
    def completeness(self) -> float:
        answered = len(THESIS_QUESTIONS) - len(self.missing)
        return round(answered / len(THESIS_QUESTIONS), 3)

    def as_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "answers": {k: self.answers.get(k, "") for k in THESIS_QUESTIONS},
            "questions": dict(THESIS_QUESTIONS),
            "missing": self.missing,
            "completeness": self.completeness,
            "is_declared": self.is_declared,
            "note": (
                "A thesis is a commitment an operator makes, not text a model "
                "generates. An unanswered question is reported as missing so "
                "that drift against it stays a finding rather than becoming "
                "agreement with whatever the channel already does."
            ),
        }


def load_thesis(channel) -> ChannelThesis:
    raw = getattr(channel, "channel_thesis", None) or {}
    answers = {k: str(raw.get(k, "") or "").strip()
               for k in THESIS_QUESTIONS} if isinstance(raw, dict) else {}
    return ChannelThesis(channel_id=getattr(channel, "channel_id", "") or "",
                         answers=answers)


# ── content architecture ─────────────────────────────────────────────────────

@dataclass
class ContentArchitecture:
    """Declared pillar roles measured against what was actually published."""

    roles: list[PillarRole] = field(default_factory=list)
    published_by_pillar: dict[str, int] = field(default_factory=dict)
    unclassified_videos: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def total_published(self) -> int:
        return sum(self.published_by_pillar.values()) + self.unclassified_videos

    @property
    def share_by_role(self) -> dict[str, float]:
        """Share of PUBLISHED videos per declared role."""
        if self.total_published <= 0:
            return {}
        role_of = {r.pillar_id: r.role for r in self.roles}
        counts: dict[str, int] = {}
        for pillar_id, count in self.published_by_pillar.items():
            counts[role_of.get(pillar_id, UNDECLARED)] = \
                counts.get(role_of.get(pillar_id, UNDECLARED), 0) + count
        if self.unclassified_videos:
            counts[UNDECLARED] = counts.get(UNDECLARED, 0) + self.unclassified_videos
        return {k: round(v / self.total_published, 3)
                for k, v in sorted(counts.items())}

    @property
    def dormant_pillars(self) -> list[str]:
        """Declared pillars with nothing published — an architecture on paper."""
        return sorted(r.pillar_id for r in self.roles
                      if not self.published_by_pillar.get(r.pillar_id))

    def as_dict(self) -> dict:
        return {
            "roles": [r.as_dict() for r in self.roles],
            "published_by_pillar": dict(self.published_by_pillar),
            "unclassified_videos": self.unclassified_videos,
            "total_published": self.total_published,
            "share_by_role": self.share_by_role,
            "dormant_pillars": self.dormant_pillars,
            "notes": list(self.notes),
        }


def review_architecture(channel, published_titles: list[str],
                        published_descriptions: list[str] | None = None
                        ) -> ContentArchitecture:
    """Compare the declared architecture against the published library.

    `published_titles` are the channel's OWN published videos. Classification
    uses the same deterministic pillar matcher the scorer and the brief builders
    use, so a video's pillar is the same answer everywhere — a strategy report
    that classified differently from the scorer would be measuring a library
    that does not exist.
    """
    from omnicast.analytics.pillars import classify_pillar, load_pillars

    architecture = ContentArchitecture()
    # A bare string is not a list of titles: iterating it counted every
    # CHARACTER as an unclassified video.
    if isinstance(published_titles, (str, bytes)):
        published_titles = [published_titles]
    elif published_titles is None:
        published_titles = []
    else:
        try:
            published_titles = list(published_titles)
        except TypeError:
            published_titles = []
    if isinstance(published_descriptions, (str, bytes)):
        published_descriptions = [published_descriptions]
    raw_pillars = getattr(channel, "content_pillars", None) or []
    pillars = load_pillars(raw_pillars)

    if not pillars:
        architecture.notes.append(
            "no content pillars declared — §11.2 asks for core/supporting/"
            "experimental, and without them every video is unclassified and no "
            "drift can be measured")
        architecture.unclassified_videos = len(published_titles or [])
        return architecture

    seen_ids: set[str] = set()
    for raw in raw_pillars:
        if not isinstance(raw, dict):
            continue
        pillar_id = str(raw.get("id") or raw.get("pillar_id") or "").strip()
        if not pillar_id:
            continue
        if pillar_id in seen_ids:
            # `role_of` is a dict keyed by pillar id, so a second declaration
            # silently reassigned 100% of that pillar's published share to the
            # later role — a core pillar could report 0% while every one of its
            # videos was attributed to `experimental`.
            architecture.notes.append(
                f"pillar '{pillar_id}' is declared more than once; the later "
                "declaration was ignored, because two roles for one id means "
                "its published share would be attributed to whichever came last")
            continue
        seen_ids.add(pillar_id)
        role = str(raw.get("role") or "").strip().lower() or UNDECLARED
        if role not in PILLAR_ROLES:
            architecture.notes.append(
                f"pillar '{pillar_id}' declares role '{role}', which is not one "
                f"of {PILLAR_ROLES} — treated as undeclared")
            role = UNDECLARED
        architecture.roles.append(
            PillarRole(pillar_id=pillar_id, role=role,
                       name=str(raw.get("name") or pillar_id)))

    descriptions = list(published_descriptions or [])
    for index, title in enumerate(published_titles or []):
        description = descriptions[index] if index < len(descriptions) else ""
        # Coerced, not trusted. A published title arriving as an int from a
        # JSON round-trip used to raise out of the whole architecture review.
        match = classify_pillar(str(title or ""), str(description or ""), pillars)
        if match.is_classified:
            architecture.published_by_pillar[match.pillar_id] = \
                architecture.published_by_pillar.get(match.pillar_id, 0) + 1
        else:
            architecture.unclassified_videos += 1

    if architecture.unclassified_videos:
        architecture.notes.append(
            f"{architecture.unclassified_videos} published video(s) match no "
            "declared pillar — either the library has drifted or the pillar "
            "keywords no longer describe it")
    for pillar_id in architecture.dormant_pillars:
        architecture.notes.append(
            f"pillar '{pillar_id}' is declared but has never been published to")
    if not any(r.role != UNDECLARED for r in architecture.roles):
        architecture.notes.append(
            "no pillar declares a role — core/supporting/experimental is what "
            "decides how much of the calendar each one is entitled to")
    return architecture
