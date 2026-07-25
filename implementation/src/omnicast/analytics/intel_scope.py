"""Scope keys for competitor intelligence (strategic review §4.2).

THE PROBLEM, CONCRETELY:

Playbooks are stored under `niche`. "finance" is one key, so a channel teaching
25-year-olds about index funds and a channel reassuring 65-year-olds about
outliving their savings read — and OVERWRITE — the same thumbnail playbook. The
last learner to run wins, and neither channel is told. Every finance channel in
the system has been quietly sharing one playbook.

The review's requested scope:

    channel/archetype + audience segment + format + market + content pillar

WHY A FALLBACK CHAIN AND NOT JUST A NARROWER KEY:

Narrowing the key alone trades one silent failure for another. A channel with a
pillar configured would look up
`fin_retirement_us|55plus|longform|us|annuities`, find nothing on its first
ever run, and get no playbook at all — while a perfectly good niche-level
playbook sat one row away. So a lookup walks from the most specific key to the
least, and REPORTS WHICH LEVEL ANSWERED. A caller that receives a niche-level
playbook must be able to tell that it did; borrowing a broader playbook is a
reasonable default and a terrible thing to do silently.

Keys are lowercase, `|`-separated, with `*` for a dimension the channel has not
configured. `*` is not a wildcard at read time — it is a literal, so a channel
that has declared no pillar cannot collide with one that has.
"""

from __future__ import annotations

import re

SEPARATOR = "|"
ANY = "*"

# Most specific first. Each entry names the dimensions kept at that level.
_LEVELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exact", ("archetype", "audience", "format", "market", "pillar")),
    ("no_pillar", ("archetype", "audience", "format", "market")),
    ("no_format", ("archetype", "audience", "market")),
    ("archetype_market", ("archetype", "market")),
    ("niche", ("niche",)),
)

_CLEAN = re.compile(r"[^a-z0-9_.+-]+")


def _slug(value) -> str:
    text = _CLEAN.sub("_", str(value or "").strip().lower()).strip("_")
    return text or ANY


def dimensions_for(channel, *, pillar_id: str = "") -> dict[str, str]:
    """Read the scope dimensions off a channel profile.

    `getattr` with defaults rather than attribute access: this must keep working
    for the hand-built stand-ins used across the test suite and for older
    channel JSON that predates the newer fields."""
    from omnicast.analytics.pillars import UNCLASSIFIED, UNCONFIGURED

    niche = getattr(getattr(channel, "niche", None), "value", None) or \
        getattr(channel, "niche", "") or ANY
    market = getattr(getattr(channel, "market", None), "value", None) or \
        getattr(channel, "market", "") or ANY
    # Archetype identifies WHOSE playbook this is. `channel_id` is the honest
    # default: two channels are only known to share an archetype when an
    # operator says so.
    archetype = (getattr(channel, "intel_archetype", "")
                 or getattr(channel, "channel_id", "") or ANY)
    audience = getattr(channel, "audience_segment", "") or ANY
    content_format = getattr(channel, "content_format", "") or ANY
    pillar = pillar_id if pillar_id not in ("", UNCONFIGURED, UNCLASSIFIED) else ANY

    return {
        "niche": _slug(niche),
        "market": _slug(market),
        "archetype": _slug(archetype),
        "audience": _slug(audience),
        "format": _slug(content_format),
        "pillar": _slug(pillar),
    }


def build_key(dimensions: dict[str, str], level: str = "exact") -> str:
    for name, parts in _LEVELS:
        if name == level:
            return SEPARATOR.join(dimensions.get(part, ANY) for part in parts)
    raise ValueError(f"unknown scope level {level!r}")


def scope_key(channel, *, pillar_id: str = "") -> str:
    """The key a learning run writes under — always the most specific one."""
    return build_key(dimensions_for(channel, pillar_id=pillar_id), "exact")


def fallback_chain(channel, *, pillar_id: str = "") -> list[tuple[str, str]]:
    """[(level, key), ...] from most specific to the legacy niche-only key.

    Duplicate keys are collapsed: on a channel with nothing configured, several
    levels produce the same string, and reporting `niche` for a lookup that
    matched at `no_format` would be a lie about specificity."""
    dimensions = dimensions_for(channel, pillar_id=pillar_id)
    chain: list[tuple[str, str]] = []
    seen: set[str] = set()
    for level, _parts in _LEVELS:
        key = build_key(dimensions, level)
        if key in seen:
            continue
        seen.add(key)
        chain.append((level, key))
    return chain


def describe_level(level: str) -> str:
    """One line a caller can log or attach to a playbook it borrowed."""
    return {
        "exact": "intel learned for this exact channel/audience/format/market/pillar",
        "no_pillar": "intel learned for this channel/audience/format/market, any pillar",
        "no_format": "intel learned for this channel/audience/market, any format",
        "archetype_market": "intel learned for this channel and market only",
        "niche": ("BORROWED: niche-wide intel, not specific to this channel's "
                  "audience or format — the failure mode §4.2 describes"),
    }.get(level, level)
