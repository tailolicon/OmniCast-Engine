"""Reference binding — tie each attached image to a specific noun in the prompt.

THE TECHNIQUE (ported from Forget-C/Jellyfish, Apache-2.0, plus the reference
transfer contract from Emily2040/seedance-2.0, MIT).

Attaching reference images and hoping is what the repo did before: a channel's
anchor set went out with every call and the model decided for itself what to do
with them. It cannot know that image 1 was about a face and image 2 was about a
room. So it averages them, and the face drifts anyway.

The fix is two deterministic steps, both here:

  1. The frame prompt is authored in ENTITY NAMES, then every name is replaced
     by the token of the image that stands for it, and a table maps token to
     file. The model no longer has to guess which image is which noun —
     `[IMAGE 1]` IS the noun.

  2. Each row states what that reference controls and what must NOT transfer.
     An identity portrait that does not say "ignore its background" donates its
     background.

Order is load-bearing. `Frame.reference_paths` is the attachment order and the
tokens are numbered from it; shuffling the file list silently re-points every
token in the prompt. That is why mappings are built once, stored, and reused —
never recomputed at call time from an unordered set.
"""

from __future__ import annotations

import re

from omnicast.storyboard.models import (
    DEFAULT_ROLE,
    ROLE_IGNORES,
    Entity,
    EntityKind,
    RefMapping,
    RefRole,
    Shot,
    Storyboard,
    normalize_name,
)

#: Token shape. Bracketed so a leaked/unsubstituted token is greppable, and
#: numbered from 1 because "image 0" reads as "no image" to a language model.
TOKEN_FORMAT = "[IMAGE {n}]"

#: Practical cap on attached references. Gemini degrades once a call carries
#: more than a handful of images — each one competes for the same attention —
#: and Flow's composer caps ingredients outright. Dropping is never silent:
#: `build_mappings` returns what it dropped and callers record it.
MAX_REFS_DEFAULT = 6

#: Kinds ordered by how badly a wrong reference hurts. A character whose face
#: changes mid-video is the defect viewers name; a prop is a detail.
_KIND_PRIORITY: dict[EntityKind, int] = {
    EntityKind.CHARACTER: 0,
    EntityKind.COSTUME: 1,
    EntityKind.LOCATION: 2,
    EntityKind.PROP: 3,
}

#: Scripts without word boundaries (CJK and friends). For these, `(?<!\w)`
#: lookarounds would refuse to match a name followed by a particle, so we fall
#: back to plain substring replacement.
_NO_WORD_BOUNDARY_FROM = 0x2E80


def _has_unbounded_script(text: str) -> bool:
    return any(ord(ch) >= _NO_WORD_BOUNDARY_FROM for ch in text)


def token_for(index: int) -> str:
    """Token for the 0-based position in the attachment list."""
    return TOKEN_FORMAT.format(n=index + 1)


# --------------------------------------------------------------------------
# Building the mapping table
# --------------------------------------------------------------------------

def _pick_image(entity: Entity, role: RefRole) -> str:
    """The one file that represents this entity in this shot.

    Operator-supplied images outrank generated ones: if a human uploaded a
    portrait, that is the character, and a later generation pass must not
    quietly outvote it. Among equals, the first approved image wins so the
    choice is stable across runs (a set would make it random).
    """
    approved = entity.approved_images
    if not approved:
        return ""
    exact = [im for im in approved if im.role == role]
    pool = exact or approved
    pool = sorted(pool, key=lambda im: (im.source.value != "operator",))
    return pool[0].path


def build_mappings(
    shot: Shot,
    board: Storyboard,
    *,
    max_refs: int = MAX_REFS_DEFAULT,
) -> tuple[list[RefMapping], list[str]]:
    """Ordered token→image table for one shot.

    Returns `(mappings, dropped)`. `dropped` names entities that were cut by
    `max_refs` or that had no approved image — callers MUST record it. A
    storyboard that silently drops its lead's reference reads, downstream, as
    "we had no reference", which is exactly the bug this package exists to end.
    """
    mappings: list[RefMapping] = []
    dropped: list[str] = []
    seen: set[str] = set()

    # Declared cast order first (the director's own priority), then the
    # location. Within that, stable-sort by kind so a 3-ref budget spends
    # itself on faces rather than on a coffee cup.
    ordered: list[tuple[str, RefRole | None]] = [
        (c.entity_id, c.role) for c in sorted(shot.cast, key=lambda c: c.index)
    ]
    if shot.location_id:
        ordered.append((shot.location_id, None))

    resolved: list[tuple[Entity, RefRole]] = []
    for entity_id, role_override in ordered:
        if entity_id in seen:
            continue
        seen.add(entity_id)
        entity = board.entity(entity_id)
        if entity is None:
            dropped.append(f"{entity_id} (not in cast registry)")
            continue
        role = role_override or DEFAULT_ROLE.get(entity.kind, RefRole.IDENTITY)
        resolved.append((entity, role))

    resolved.sort(key=lambda pair: _KIND_PRIORITY.get(pair[0].kind, 9))

    for entity, role in resolved:
        path = _pick_image(entity, role)
        if not path:
            dropped.append(f"{entity.name} (no approved reference image)")
            continue
        if len(mappings) >= max_refs:
            dropped.append(f"{entity.name} (over the {max_refs}-reference cap)")
            continue
        mappings.append(RefMapping(
            token=token_for(len(mappings)),
            entity_id=entity.entity_id,
            name=entity.name,
            kind=entity.kind,
            role=role,
            path=path,
        ))
    return mappings, dropped


# --------------------------------------------------------------------------
# Substituting names for tokens
# --------------------------------------------------------------------------

def _branch(spelling: str) -> str:
    """One alternation branch carrying its own word-boundary assertions.

    Lookarounds, not `\\b`: a name may legitimately end in punctuation
    ("Bà Tư (già)") and `\\b` would refuse to anchor there. Scripts without
    word boundaries get a bare literal instead, since `(?!\\w)` would refuse to
    match a CJK name followed by a particle.
    """
    escaped = re.escape(spelling)
    if _has_unbounded_script(spelling):
        return escaped
    return rf"(?<!\w){escaped}(?!\w)"


def _spelling_pattern(spelling: str) -> re.Pattern[str]:
    return re.compile(_branch(spelling), re.IGNORECASE)


def bind_prompt(base_prompt: str, mappings: list[RefMapping],
                board: Storyboard | None = None) -> str:
    """Replace every mapped entity's name (and aliases) with its token.

    ONE PASS, LONGEST SPELLING WINS, OVER THE WHOLE CAST — not just the mapped
    part of it. Both halves of that matter:

      * Longest first, because replacing "Minh" before "Minh Anh" leaves
        "[IMAGE 1] Anh": a phantom second character the model will draw.
      * The WHOLE cast, because the same collision happens when the longer name
        belongs to an entity that is NOT mapped in this shot. An earlier version
        sorted only the mapped spellings, so "Minh looks at Minh Anh" — with
        only Minh bound — came out as "[IMAGE 1] looks at [IMAGE 1] Anh", and
        the unbound-name check could no longer see the mangled "Minh Anh" to
        report it. Unmapped names are matched here purely so they can be left
        ALONE, intact, for `unbound_entity_names` to find.

    A single `re.sub` over one alternation is what makes "longest wins" true:
    sequential per-name passes cannot see what a previous pass already consumed.
    """
    text = (base_prompt or "").strip()
    if not text or not mappings:
        return text

    token_by_key: dict[str, str] = {}
    spellings: list[str] = []

    def _collect(spelling: str, token: str | None) -> None:
        key = normalize_name(spelling)
        if not key or key in token_by_key:
            return
        token_by_key[key] = token or ""
        spellings.append(spelling)

    for mapping in mappings:
        entity = board.entity(mapping.entity_id) if board else None
        for spelling in (entity.all_spellings() if entity else [mapping.name]):
            _collect(spelling, mapping.token)

    if board is not None:
        bound = {m.entity_id for m in mappings}
        for entity in board.entities:
            if entity.entity_id in bound:
                continue
            for spelling in entity.all_spellings():
                _collect(spelling, None)

    if not spellings:
        return text

    spellings.sort(key=len, reverse=True)
    pattern = re.compile("|".join(_branch(s) for s in spellings), re.IGNORECASE)

    def _swap(match: re.Match[str]) -> str:
        token = token_by_key.get(normalize_name(match.group(0)), "")
        return token or match.group(0)

    return pattern.sub(_swap, text)


def unbound_entity_names(text: str, board: Storyboard,
                         mappings: list[RefMapping]) -> list[str]:
    """Cast names still sitting in the prompt with no image behind them.

    A real defect, not a nit: the model reads "Minh walks in", invents a Minh,
    and that invented face is what ships. Surfaced so the gate can block it
    rather than the viewer finding it.
    """
    bound = {m.entity_id for m in mappings}
    hits: list[str] = []
    for entity in board.entities:
        if entity.entity_id in bound:
            continue
        for spelling in entity.all_spellings():
            if _spelling_pattern(spelling).search(text):
                hits.append(entity.name)
                break
    return hits


# --------------------------------------------------------------------------
# Composing the final prompt
# --------------------------------------------------------------------------

def _ignore_clause(role: RefRole) -> str:
    ignores = ROLE_IGNORES.get(role, ())
    if not ignores:
        return f"controls {role.value}"
    # seedance's phrasing, kept close to the source: the ignore list reads as
    # "from that reference", not "its X" — "ignore its any person" is not a
    # sentence, and a malformed clause is a clause the model skips.
    return (f"controls {role.value} ONLY; ignore "
            + ", ".join(ignores) + " from that reference")


def reference_table(mappings: list[RefMapping]) -> str:
    """The block that tells the model what each attached image is FOR."""
    if not mappings:
        return ""
    lines = ["## REFERENCE IMAGES"]
    for m in mappings:
        lines.append(f"{m.token} = {m.name} ({m.kind.value}) — {_ignore_clause(m.role)}.")
    return "\n".join(lines)


def compose_rendered_prompt(
    *,
    base_prompt: str,
    mappings: list[RefMapping],
    style_prompt: str = "",
    board: Storyboard | None = None,
    extra_directives: list[str] | None = None,
) -> str:
    """Assemble the exact text sent to the image model.

    Section order is deliberate. References come first because the model must
    know what the tokens mean before it reads a sentence containing them; style
    comes last because a style block ahead of the scene tends to swallow it.
    """
    bound = bind_prompt(base_prompt, mappings, board)
    blocks: list[str] = []
    table = reference_table(mappings)
    if table:
        blocks.append(table)
    for directive in (extra_directives or []):
        if directive.strip():
            blocks.append(directive.strip())
    blocks.append("## SCENE\n" + bound)
    if style_prompt.strip():
        blocks.append("## STYLE\n" + style_prompt.strip())
    return "\n\n".join(blocks).strip()


# --------------------------------------------------------------------------
# Lint
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\[IMAGE\s+(\d+)\]", re.IGNORECASE)


def binding_issues(*, rendered_prompt: str, mappings: list[RefMapping],
                   board: Storyboard | None = None) -> list[str]:
    """Everything wrong with a binding, named. Empty list means sound.

    Checks the three ways this silently breaks:
      - a token in the text with no image behind it (off-by-one, hand edit);
      - an attached image no sentence ever refers to (paid for, ignored);
      - a cast name left unbound (the model invents that character).
    """
    issues: list[str] = []
    used = {int(n) for n in _TOKEN_RE.findall(rendered_prompt)}
    available = set(range(1, len(mappings) + 1))

    for n in sorted(used - available):
        issues.append(
            f"prompt refers to [IMAGE {n}] but only {len(mappings)} reference "
            f"image(s) are attached — that token points at nothing")

    # The reference table itself names every token, so look only at the scene
    # body when deciding whether a reference is actually used.
    body = rendered_prompt.split("## SCENE", 1)[-1]
    body_used = {int(n) for n in _TOKEN_RE.findall(body)}
    for n in sorted(available - body_used):
        m = mappings[n - 1]
        issues.append(
            f"{m.token} ({m.name}) is attached but never referenced in the "
            f"scene text — it will bleed into the frame with no anchor")

    if board is not None:
        for name in unbound_entity_names(body, board, mappings):
            issues.append(
                f"cast member '{name}' appears in the scene text with no "
                f"reference image bound — the model will invent one")
    return issues
