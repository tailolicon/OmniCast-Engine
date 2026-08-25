"""Pre-writing, source-backed evidence for YMYL scripts.

The post-writing fact ledger proves that a script *has an attribution*. It
cannot prove that the cited page exists or contains what the script says.
This stage runs before an EditorialAngle is planned:

1. an LLM proposes a small set of primary-source claims and exact short quotes;
2. Python fetches each URL itself;
3. domain, current-year recency, quote presence and value presence are checked;
4. only verified entries become Writer evidence anchors.

This is intentionally conservative. A blocked source costs one research retry;
an invented retirement rule costs the channel its trust.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, model_validator

from omnicast.agents.base import BaseAgent

PRIMARY_SOURCE_DOMAINS = (
    "ssa.gov",
    "irs.gov",
    "fbi.gov",
    "cfpb.gov",
    "medicare.gov",
    "congress.gov",
    "govinfo.gov",
    "vanguard.com",
    "fidelity.com",
)


class SourceEvidence(BaseModel):
    evidence_id: str = ""
    claim: str = Field(min_length=8)
    value: str = ""
    source_name: str = Field(min_length=3)
    source_url: str
    as_of: str
    year_sensitive: bool = False
    quote: str = Field(min_length=12, max_length=500)
    quote_extracted_from_page: bool = False

    @model_validator(mode="before")
    @classmethod
    def _model_key_variants(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        aliases = {
            "claim": ("fact", "supported_claim"),
            "value": ("figure", "number"),
            "source_url": ("url", "official_url"),
            "as_of": ("year", "rule_year"),
            "quote": (
                "verbatim_quote", "excerpt_quote", "source_excerpt", "excerpt"),
        }
        for canonical, variants in aliases.items():
            if not data.get(canonical):
                for name in variants:
                    if data.get(name):
                        data[canonical] = data[name]
                        break
        for name in (
            "evidence_id",
            "claim",
            "value",
            "source_name",
            "source_url",
            "as_of",
            "quote",
        ):
            if data.get(name) is not None and not isinstance(data.get(name), str):
                data[name] = str(data[name])
        return data


class EvidencePack(BaseModel):
    topic: str
    entries: list[SourceEvidence] = Field(min_length=2)
    rejected: list[str] = Field(default_factory=list)
    verified_at: str = ""

    def writer_points(self) -> list[dict[str, str]]:
        return [
            {
                "evidence_id": item.evidence_id,
                "claim": item.claim,
                "value": item.value,
                "source_name": item.source_name,
                "source_url": item.source_url,
                "as_of": item.as_of,
                "quote": item.quote,
            }
            for item in self.entries
        ]


class _EvidenceDraft(BaseModel):
    entries: list[SourceEvidence] = Field(min_length=3, max_length=10)

    @model_validator(mode="before")
    @classmethod
    def _top_level_variants(cls, value):
        if isinstance(value, list):
            return {"entries": value}
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not data.get("entries"):
            for name in ("evidence_pack", "evidence", "sources", "claims"):
                if isinstance(data.get(name), list):
                    data["entries"] = data[name]
                    break
        return data


def evidence_coverage_problems(
    pack: EvidencePack,
    topic: str,
    *,
    current_year: int | None = None,
) -> list[str]:
    """Check that verified facts answer the question, not merely the domain.

    Live research once returned six valid SSA excerpts for a 2026 earnings-test
    topic but omitted the 2026 exempt amount itself. The Writer then filled the
    hole from stale memory. URL/quote verification cannot catch an *absent*
    load-bearing fact, so narrow, high-risk topics need a small coverage gate.
    """
    year = current_year or datetime.now(timezone.utc).year
    subject = _norm(topic)
    corpus = " ".join(
        f"{entry.claim} {entry.value} {entry.quote} {entry.as_of}"
        for entry in pack.entries
    )
    normalized = _norm(corpus)
    problems: list[str] = []

    is_ssa_earnings = (
        "social security" in subject
        and any(word in subject for word in ("earn", "withhold", "working"))
    )
    if not is_ssa_earnings:
        return problems

    current_threshold = any(
        entry.year_sensitive
        and str(year) in (entry.as_of or "")
        and bool(_numeric_atoms(entry.value))
        and any(term in _norm(entry.claim)
                for term in ("limit", "exempt amount", "threshold"))
        for entry in pack.entries
    )
    if not current_threshold:
        problems.append(
            "missing an exact current-year exempt amount/earnings limit")

    recalculation_covered = (
        "recalculat" in normalized
        and ("withheld" in normalized or "withhold" in normalized)
        and ("credit" in normalized or "not lost" in normalized)
    ) or (
        "not lost" in normalized
        and "monthly benefit" in normalized
        and "increased permanently" in normalized
        and ("withheld" in normalized or "withhold" in normalized)
    )
    if not recalculation_covered:
        problems.append(
            "missing the recalculation/credit mechanism for withheld benefits")
    earnings_types_covered = (
        ("wages" in normalized or "wages from your job" in normalized)
        and ("net profit" in normalized or "self-employed" in normalized)
        and (
            "pensions" in normalized
            or "investment income" in normalized
            or "interest" in normalized
        )
    )
    if not earnings_types_covered:
        problems.append(
            "missing what earnings count and do not count under the test")
    for entry in pack.entries:
        claim = _norm(entry.claim)
        if (
            "payroll tax" in claim
            or "contribution and benefit base" in claim
            or "maximum taxable earnings" in claim
        ):
            problems.append(
                f"{entry.evidence_id or 'entry'} is an adjacent payroll-tax "
                "fact, not evidence for the retirement earnings test")
    return problems


def _host_allowed(url: str, domains: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain)
               for domain in domains)


def _page_text(raw: str) -> str:
    value = re.sub(r"(?is)<(?:script|style|noscript)\b.*?</(?:script|style|noscript)>",
                   " ", raw or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _norm(text: str) -> str:
    value = html.unescape(text or "").lower()
    value = value.replace("’", "'").replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n\"'.,;:")


def _value_key(text: str) -> str:
    return re.sub(r"[^a-z0-9.%$-]", "", _norm(text))


_CLAIM_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "in", "is", "it", "of", "on", "or", "that", "the", "their", "this", "to",
    "was", "we", "were", "will", "with", "you", "your",
}


def _stem(token: str) -> str:
    value = token.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if len(value) > len(suffix) + 4 and value.endswith(suffix):
            return value[:-len(suffix)]
    return value


def _claim_lexemes(text: str) -> set[str]:
    return {
        _stem(token)
        for token in re.findall(r"[a-zA-Z]{3,}", _norm(text))
        if token.lower() not in _CLAIM_STOP
    }


def _numeric_atoms(text: str) -> list[str]:
    normalized = (text or "").replace(",", "")
    return [
        token.lower()
        for token in re.findall(r"\$?\d+(?:\.\d+)?%?", normalized)
    ]


_SMALL_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}


def _parse_number_words(words: list[str]) -> int | None:
    if not words:
        return None
    total = 0
    current = 0
    saw_number = False
    for word in words:
        if word == "and":
            continue
        if word in _SMALL_NUMBER_WORDS:
            current += _SMALL_NUMBER_WORDS[word]
            saw_number = True
        elif word == "hundred":
            current = max(1, current) * 100
            saw_number = True
        elif word in ("thousand", "million", "billion"):
            total += max(1, current) * _NUMBER_SCALES[word]
            current = 0
            saw_number = True
        else:
            return None
    return total + current if saw_number else None


def _spoken_numeric_values(text: str) -> list[tuple[int, str]]:
    """Extract digit and English-word numbers from narration.

    The ordinary numeric ledger only saw ``$1,340`` while a stale threshold
    written as "twenty-two thousand three hundred twenty" sailed through. This
    narrow parser covers natural US finance narration without pretending to be
    a general natural-language arithmetic engine.
    """
    found: list[tuple[int, str]] = []
    for match in re.finditer(r"\$?\d[\d,]*(?:\.\d+)?", text or ""):
        try:
            found.append((
                int(float(match.group(0).replace("$", "").replace(",", ""))),
                match.group(0),
            ))
        except ValueError:
            continue

    tokens = re.findall(r"[a-z]+", (text or "").lower().replace("-", " "))
    run: list[str] = []

    def flush() -> None:
        nonlocal run
        if run:
            value = _parse_number_words(run)
            if value is not None:
                found.append((value, f"{value:,}"))
        run = []

    for token in tokens:
        if token in _SMALL_NUMBER_WORDS or token in _NUMBER_SCALES:
            run.append(token)
        elif token == "and" and run:
            run.append(token)
        else:
            flush()
    flush()

    unique: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _integer_words(value: int) -> str:
    ones = (
        "zero", "one", "two", "three", "four", "five", "six", "seven",
        "eight", "nine", "ten", "eleven", "twelve", "thirteen",
        "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
        "nineteen",
    )
    tens = (
        "", "", "twenty", "thirty", "forty", "fifty", "sixty",
        "seventy", "eighty", "ninety",
    )
    if value < 20:
        return ones[value]
    if value < 100:
        return tens[value // 10] + (
            " " + ones[value % 10] if value % 10 else "")
    if value < 1_000:
        return (
            ones[value // 100] + " hundred"
            + (" " + _integer_words(value % 100) if value % 100 else "")
        )
    for scale, name in (
        (1_000_000_000, "billion"),
        (1_000_000, "million"),
        (1_000, "thousand"),
    ):
        if value >= scale:
            return (
                _integer_words(value // scale) + f" {name}"
                + (" " + _integer_words(value % scale)
                   if value % scale else "")
            )
    return str(value)


def _verified_number_replacements(pack: EvidencePack) -> list[tuple[re.Pattern, str]]:
    replacements: list[tuple[re.Pattern, str]] = []
    seen: set[int] = set()
    for entry in pack.entries:
        raw = entry.value or ""
        atoms = _numeric_atoms(raw)
        # Compound ratios ($1 for every $2) are spoken naturally; normalize only
        # one-value thresholds/limits whose exact digits matter.
        if len(atoms) != 1:
            continue
        try:
            value = int(float(atoms[0].replace("$", "").replace("%", "")))
        except ValueError:
            continue
        if value <= 10 or value in seen:
            continue
        seen.add(value)
        display_match = re.search(r"\$?\d[\d,]*(?:\.\d+)?%?", raw)
        display = display_match.group(0) if display_match else f"{value:,}"
        canonical = _integer_words(value)
        variants = {canonical}
        # Models often emit "$24,480" as "twenty-four thousand, four
        # eighty", dropping "hundred". It is unambiguous in context but poor
        # for both TTS and deterministic checking, so normalize it.
        if " hundred " in f" {canonical} ":
            variants.add(canonical.replace(" hundred", ""))
        for phrase in variants:
            words = phrase.split()
            pattern = r"\b" + r"[\s,-]+".join(
                re.escape(word) for word in words) + r"\b"
            replacements.append((re.compile(pattern, re.IGNORECASE), display))
    return replacements


def normalize_draft_evidence_numbers(draft, pack: EvidencePack):
    """Canonicalize verified thresholds in VO to the pack's exact digits."""
    replacements = _verified_number_replacements(pack)
    if not replacements:
        return draft

    def replace(text: str) -> str:
        value = text or ""
        for pattern, display in replacements:
            value = pattern.sub(display, value)
        return value

    hook_scenes = [
        scene.model_copy(update={"voiceover": replace(scene.voiceover)})
        for scene in (getattr(draft, "hook_scenes", ()) or ())
    ]
    segments = []
    for segment in (getattr(draft, "segments", ()) or ()):
        scenes = [
            scene.model_copy(update={"voiceover": replace(scene.voiceover)})
            for scene in (getattr(segment, "scenes", ()) or ())
        ]
        segments.append(segment.model_copy(update={
            "scenes": scenes,
            "content": (
                " ".join(scene.voiceover for scene in scenes)
                if scenes else replace(getattr(segment, "content", ""))),
        }))
    outro_scenes = [
        scene.model_copy(update={"voiceover": replace(scene.voiceover)})
        for scene in (getattr(draft, "outro_scenes", ()) or ())
    ]
    return draft.model_copy(update={
        "hook_scenes": hook_scenes,
        "hook": (
            " ".join(scene.voiceover for scene in hook_scenes)
            if hook_scenes else replace(getattr(draft, "hook", ""))),
        "segments": segments,
        "outro_scenes": outro_scenes,
        "outro": (
            " ".join(scene.voiceover for scene in outro_scenes)
            if outro_scenes else replace(getattr(draft, "outro", ""))),
    })


def gate_draft_against_pack(draft, pack: EvidencePack) -> list[str]:
    """Block unverified rule figures before an LLM critic can bless them.

    Invented inputs are permitted only inside a backstage segment whose heading
    says EXAMPLE or HYPOTHETICAL. This is structural metadata, not a required
    spoken phrase. Even there, a sentence attributing a number to an agency,
    rule, limit or threshold must match the verified pack.
    """
    evidence_text = " ".join(
        f"{entry.claim} {entry.value} {entry.quote} {entry.as_of}"
        for entry in pack.entries
    )
    allowed = {
        value for value, _ in _spoken_numeric_values(evidence_text)
    }
    for entry in pack.entries:
        ratio_text = f"{entry.value} {entry.claim} {entry.quote}"
        if "for every" not in _norm(ratio_text):
            continue
        ratio_match = re.search(
            r"(?:withhold\w*|deduct\w*)\s+\$?(\d+(?:\.\d+)?)"
            r"[^.;]{0,50}?for every\s+\$?"
            r"(\d+(?:\.\d+)?)",
            _norm(ratio_text),
        )
        if ratio_match:
            try:
                numerator = float(ratio_match.group(1))
                denominator = float(ratio_match.group(2))
                percentage = numerator / denominator * 100
                if percentage.is_integer():
                    allowed.add(int(percentage))
            except (ValueError, ZeroDivisionError):
                pass
    direct_authoritative_claim = re.compile(
        r"\b(?:ssa|irs|medicare|official|according\s+to|published|"
        r"fact\s+sheet)\b[^.!?]{0,80}"
        r"\b(?:is|was|sets?|lists?|publishes?|says?|states?|gives?)\b|"
        r"\b(?:official\s+)?(?:rule|law|limit|threshold|exempt\s+amount)\b"
        r"\s*(?:is|was|equals?|of|:)\s*",
        re.IGNORECASE,
    )
    problems: list[str] = []

    sections: list[tuple[str, list]] = [
        ("HOOK", list(getattr(draft, "hook_scenes", ()) or ())),
    ]
    sections.extend(
        (getattr(segment, "heading", "") or f"SEGMENT {index}",
         list(getattr(segment, "scenes", ()) or ()))
        for index, segment in enumerate(
            getattr(draft, "segments", ()) or (), 1)
    )
    sections.append(
        ("OUTRO", list(getattr(draft, "outro_scenes", ()) or ())))

    for heading, scenes in sections:
        illustrative = (
            "hypothetical" in heading.lower()
            or "example" in heading.lower()
        )
        for scene in scenes:
            voiceover = getattr(scene, "voiceover", "") or ""
            for value, display in _spoken_numeric_values(voiceover):
                # Small counts and the $1-for-$2/$3 ratios are not threshold-like
                # claims. Values above ten, ages, years and money are.
                if value <= 10 or value in allowed:
                    continue
                # Twelve is a calendar constant in this context, not a sourced
                # benefits threshold.  Without this narrow exception the gate
                # rejected "twelve monthly checks" while correctly allowing the
                # much riskier dollar claims around it.
                if value == 12 and re.search(
                    r"\b(?:12|twelve)\s+(?:monthly\s+)?(?:months?|checks?)\b",
                    voiceover,
                    re.IGNORECASE,
                ):
                    continue
                if illustrative:
                    # A labelled example may invent inputs and derived values.
                    # Saying "$5,520 over the threshold" is not an attribution;
                    # directly presenting an unverified figure as an official
                    # rule value still is.
                    if not direct_authoritative_claim.search(voiceover):
                        continue
                problems.append(
                    f"{heading}: figure {display} is not in verified evidence; "
                    "remove it, replace it with an E-anchor value, or move a "
                    "illustrative input into a backstage EXAMPLE segment")
    return list(dict.fromkeys(problems))


def gate_draft_claims_against_pack(
    draft,
    pack: EvidencePack,
) -> list[str]:
    """Block recurring qualitative overclaims that numeric matching cannot see.

    The fact-ledger model is not a completeness oracle: the same unchanged
    script once failed for an unverified calculator and then passed when the
    model simply omitted that claim.  This gate covers narrow, deterministic
    boundary violations for the SSA earnings-test adapter.
    """
    subject = _norm(pack.topic)
    if not (
        "social security" in subject
        and any(word in subject for word in ("earn", "withhold", "working"))
    ):
        return []

    sections: list[tuple[str, str]] = [
        ("HOOK", " ".join(
            scene.voiceover
            for scene in (getattr(draft, "hook_scenes", ()) or ())
        ) or (getattr(draft, "hook", "") or "")),
    ]
    sections.extend(
        (
            getattr(segment, "heading", "") or f"SEGMENT {index}",
            " ".join(
                scene.voiceover
                for scene in (getattr(segment, "scenes", ()) or ())
            ) or (getattr(segment, "content", "") or ""),
        )
        for index, segment in enumerate(
            getattr(draft, "segments", ()) or (), 1)
    )
    sections.append(("OUTRO", " ".join(
        scene.voiceover
        for scene in (getattr(draft, "outro_scenes", ()) or ())
    ) or (getattr(draft, "outro", "") or "")))

    pack_corpus = _norm(" ".join(
        f"{entry.claim} {entry.quote} {entry.source_url}"
        for entry in pack.entries
    ))
    patterns: list[tuple[re.Pattern[str], str]] = []
    if "earnings test calculator" not in pack_corpus:
        patterns.append((
            re.compile(
                r"\b(?:retirement\s+)?earnings test calculator\b|"
                r"\bssa(?:'s)?\s+(?:earnings test\s+)?calculator\b",
                re.IGNORECASE,
            ),
            "named SSA calculator is absent from the verified evidence pack",
        ))
    patterns.extend([
        (
            re.compile(
                r"\b(?:pay|pays|paid|give|gives|giving)\s+"
                r"(?:it|the money|those dollars)\s+back\b|"
                r"\b(?:later|delayed)\s+(?:payment\s+)?schedule\b|"
                r"\b(?:paid|benefits paid)\s+on a different timeline\b|"
                r"\b(?:withheld dollar|that money)\b[^.]{0,60}\b(?:on|has)\s+"
                r"(?:a\s+)?timeline\b|"
                r"\bmoney comes back\b|"
                r"\bshortfall is temporary in structure\b|"
                r"\bschedule behind it stays real\b|"
                r"\b(?:withheld money|withheld amount|those dollars)\b"
                r"[^.]{0,30}\bescrow\b|"
                r"\bescrow account\b|"
                r"\bnot (?:go|going) into (?:some |the )?general fund\b|"
                r"\b(?:personal|your|their)\s+ledger\b|"
                r"\brepays? your later self\b|"
                r"\b(?:money|those dollars)\b[^.]{0,50}\b(?:folded|rolled)\s+"
                r"into (?:a\s+)?bigger check\b|"
                r"\bdollar total didn't disappear from (?:their|your) "
                r"lifetime benefit\b|"
                r"\bforced savings account\b|\bdelayed release\b|\brefund\b",
                re.IGNORECASE,
            ),
            "recalculation is described as repayment/refund or delayed dollars; "
            "the verified source supports only a permanent monthly-benefit "
            "increase accounting "
            "for withheld months",
        ),
        (
            re.compile(
                r"\bmonthly limit only in (?:your|the) first year\b|"
                r"\bspecial monthly exempt amount\b|"
                r"\bonly your remaining months face the earnings test\b|"
                r"\btest only looks forward from your claiming month\b|"
                r"\bswitches over and counts your earnings annually\b",
                re.IGNORECASE,
            ),
            "the one-year special rule is stated more broadly than E8 supports",
        ),
        (
            re.compile(
                r"\bdoesn't spread evenly across (?:12|twelve) checks\b|"
                r"\bspread(?:s|ing)? (?:the withholding|it|that amount)\s+"
                r"across (?:the )?(?:year'?s|monthly) checks\b|"
                r"\b(?:smaller|equal|even)\s+amount\b[^.]{0,45}"
                r"\bwithheld from each (?:individual )?month\b|"
                r"\bholds? back entire monthly checks\b|"
                r"\bzero dollars for several months\b",
                re.IGNORECASE,
            ),
            "monthly-check withholding administration is not in an E-anchor",
        ),
        (
            re.compile(
                r"\b(?:borrow|take a loan)\s+(?:against|from)\s+"
                r"(?:it|the withheld amount|those dollars)\b|"
                r"\bssa\b[^.]{0,50}\b(?:accelerate|advance)\s+"
                r"(?:it|the recalculation|the increase)\b",
                re.IGNORECASE,
            ),
            "withheld-benefit account/administration claim is not in an E-anchor",
        ),
        (
            re.compile(
                r"\b(?:nobody|no one)\s+at\s+ssa\b[^.]{0,80}"
                r"\b(?:sends?|tells?|explains?|warns?)\b|"
                r"\b(?:statement|letter|notice)\b[^.]{0,60}"
                r"\b(?:just|only|doesn't|does not|never)\b[^.]{0,40}"
                r"\b(?:shows?|says?|explains?)\b",
                re.IGNORECASE,
            ),
            "agency communication/statement behavior is not in an E-anchor",
        ),
        (
            re.compile(
                r"\b(?:no|does not|doesn't|never)\s+"
                r"(?:lump[- ]sum payout|break[- ]even calculator|"
                r"published timeline|stated timeline|way to draw it earlier)\b|"
                r"\b(?:public rule|public materials?|ssa materials?)\b"
                r"[^.]{0,60}\b(?:does not|doesn't|never|isn't)\s+"
                r"(?:specify|state|describe|publish|show)\b",
                re.IGNORECASE,
            ),
            "negative claim about absent agency material is not verified by an E-anchor",
        ),
        (
            re.compile(
                r"\bfear spreads\b|\bpeople (?:start )?cut(?:ting)? hours\b|"
                r"\bcutting hours\b|\bturning down shifts\b|"
                r"\bquitting a job\b|\bdraining savings\b|"
                r"\bfear alone can steer\b|\bpeople oversell\b|"
                r"\bdelay filing out of\b|\bmost people\b|"
                r"\bpeople asking\b|\brarely makes it\b|"
                r"\bheadlines about\b|\bmost explanations skip\b|"
                r"\bstops people cold\b|"
                r"\b(?:penalty|lost forever|rumor)\b[^.]{0,45}"
                r"\bspreads? faster\b",
                re.IGNORECASE,
            ),
            "audience prevalence/behavior claim has no supporting E-anchor",
        ),
        (
            re.compile(
                r"\bdeliberately loosening\b|\bone design\b|"
                r"\bexists specifically\b",
                re.IGNORECASE,
            ),
            "policy intent/design motive is inferred beyond the verified rule",
        ),
    ])
    problems: list[str] = []
    for heading, text in sections:
        for pattern, explanation in patterns:
            if pattern.search(text):
                problems.append(f"{heading}: {explanation}")

        normalized = _norm(text)
        if "$70,000" in text and "$65,160" in text and "$1,613" in text:
            if not (
                "before the month" in normalized
                or "before reaching full retirement age" in normalized
                or "before full retirement age" in normalized
            ):
                problems.append(
                    f"{heading}: FRA-year example applies the $65,160 limit "
                    "to $70,000 without saying that $70,000 was earned before "
                    "the month full retirement age was reached (E6 boundary)")
            if not re.search(
                r"\b(?:about|roughly|approximately)\s+\$1,613\b",
                text,
                re.IGNORECASE,
            ):
                problems.append(
                    f"{heading}: $4,840 ÷ 3 is rounded to $1,613 without "
                    "labeling the result approximate")
        if (
            "$40,000" in text
            and "$70,000" in text
            and "similar income" in normalized
        ):
            problems.append(
                f"{heading}: the example calls $40,000 and $70,000 similar "
                "income levels")
    return list(dict.fromkeys(problems))


def gate_draft_visuals_against_pack(
    draft,
    pack: EvidencePack,
) -> list[str]:
    """Prevent storyboard prompts from inventing official tools/forms/UI."""
    corpus = _norm(" ".join(
        f"{entry.claim} {entry.quote} {entry.source_name} {entry.source_url}"
        for entry in pack.entries
    ))
    official_artifact = re.compile(
        r"\b(?:ssa-\d+[a-z]?|ssa\s*1099|retirement earnings test calculator|"
        r"my\s*social\s*security(?:\s+account)?|"
        r"social security\s+calculator)\b",
        re.IGNORECASE,
    )
    fabricated_field = re.compile(
        r"\b(?:withholding line item|zero deposit line|\$0\.00 deposit line)\b",
        re.IGNORECASE,
    )
    problems: list[str] = []
    section_scenes = [
        ("HOOK", list(getattr(draft, "hook_scenes", ()) or ())),
    ]
    section_scenes.extend(
        (
            getattr(segment, "heading", "") or f"SEGMENT {index}",
            list(getattr(segment, "scenes", ()) or ()),
        )
        for index, segment in enumerate(
            getattr(draft, "segments", ()) or (), 1)
    )
    section_scenes.append(
        ("OUTRO", list(getattr(draft, "outro_scenes", ()) or ())))
    for heading, scenes in section_scenes:
        for scene_index, scene in enumerate(scenes, 1):
            visual = getattr(scene, "visual_prompt", "") or ""
            for match in official_artifact.finditer(visual):
                artifact = _norm(match.group(0))
                if artifact not in corpus:
                    problems.append(
                        f"{heading} visual {scene_index}: official artifact "
                        f"{match.group(0)!r} is absent from verified evidence")
            if fabricated_field.search(visual):
                problems.append(
                    f"{heading} visual {scene_index}: prompt invents a bank/"
                    "benefit-statement field not present in verified evidence")
    return list(dict.fromkeys(problems))


_SSA_EARNINGS_EDITORIAL_REPAIRS: dict[str, tuple[str, str | None]] = {
    (
        "The fear alone could be steering this decision, right now, before "
        "anyone checks the actual math."
    ): (
        "Put that fear to one side for a moment and check the actual math.",
        "notepad beside official SSA rule page",
    ),
    (
        "This is about what actually happens to that withheld dollar, on "
        "Social Security's own timeline."
    ): (
        "This is about what SSA says happens to withheld benefits at full "
        "retirement age.",
        "verified SSA earnings-test page highlighted",
    ),
    "This has a schedule. We'll walk through it. But there's one more mechanical detail first.": (
        "The rule has one more exception. We'll examine it before turning to "
        "full retirement age.",
        "rule diagram with one exception branch",
    ),
    (
        "That ramp is why the withholding rate itself changes, not just the "
        "dollar threshold underneath it."
    ): (
        "The changing rate and threshold make the full-retirement-age year a "
        "different calculation.",
        "two-column rate and threshold comparison",
    ),
    (
        "You can earn any amount, from any job, and every benefit dollar "
        "arrives on schedule."
    ): (
        "You can earn any amount without the earnings test reducing your "
        "benefit.",
        "verified SSA page beside an unrestricted earnings arrow",
    ),
    (
        "That's not a technicality. It's the exact mechanism separating a "
        "temporary hold from a genuine loss."
    ): (
        "That is the mechanism separating withholding under this test from a "
        "permanent loss.",
        "WITHHELD versus PERMANENTLY LOST comparison",
    ),
    (
        "Your benefit is adjusted upward to reflect that, not as a bonus, but "
        "as a correction."
    ): (
        "SSA says the monthly benefit increases permanently to account for "
        "months benefits were withheld.",
        "monthly benefit arrow rising after full retirement age",
    ),
    (
        "For someone with no other income source, that gap isn't inconvenient "
        "— it's the entire month's grocery budget."
    ): (
        "For someone using every check for essentials, that gap could include "
        "money already set aside for groceries.",
        "grocery receipt beside monthly budget envelope",
    ),
    (
        "That's the honest weight of the mechanism, even while the schedule "
        "behind it stays real."
    ): (
        "That is the honest weight of the cash-flow gap, even with a later "
        "permanent monthly increase.",
        "cash-flow gap beside later monthly increase",
    ),
    (
        "Both of those things are true at the same time, and that's the part "
        "most explanations skip entirely."
    ): (
        "Both facts belong in the same explanation.",
        "two verified facts shown side by side",
    ),
    (
        "If cash flow is the real concern, your own earnings and record are "
        "what determine roughly how many months it affects."
    ): (
        "These verified thresholds explain the rule, but they do not calculate "
        "an individual result.",
        "verified thresholds beside blank personal-input fields",
    ),
    (
        "That pattern is broken down further in the video linked in the pinned "
        "comment below."
    ): (
        "Keep that withheld-versus-lost distinction in mind when you hear other "
        "Social Security timing claims.",
        "WITHHELD IS NOT PERMANENTLY LOST title card",
    ),
    (
        "Spread across monthly checks, that can mean months where the deposit "
        "shows as reduced or missing."
    ): (
        "In this hypothetical, $7,760 is benefit cash flow unavailable during "
        "the withholding period.",
        "$7,760 highlighted as current cash-flow gap",
    ),
    (
        "Practically speaking, that means this worker needs to budget around "
        "missing income for part of the year."
    ): (
        "This hypothetical worker would need a plan for that cash-flow gap.",
        "monthly budget with a highlighted cash-flow gap",
    ),
    (
        "That's the exact moment the fear kicks in. Watching a check shrink and "
        "assuming it's gone for good."
    ): (
        "A $7,760 reduction can feel permanent. That reaction is exactly why "
        "the distinction matters.",
        "$7,760 reduction beside WITHHELD versus LOST labels",
    ),
    (
        "If this worker had a whole month with low enough earnings, that special "
        "one-year rule could pay that month in full."
    ): (
        "If SSA considers a whole month retired, the special one-year rule can "
        "pay that month's full benefit.",
        "one calendar month marked CONSIDERED RETIRED",
    ),
    (
        "Same worker, two different hypothetical incomes, dramatically smaller "
        "withholding, purely because the year changed."
    ): (
        "This second calculation illustrates the different threshold and rate "
        "in the year full retirement age is reached.",
        "lower-year and FRA-year formulas side by side",
    ),
    (
        "That's the full arc. Withheld under one rate, phased under a second "
        "rate, released entirely at full retirement age, then reflected in a "
        "recalculated check."
    ): (
        "That is the full arc: two rates before full retirement age, no test "
        "starting that month, then a permanent monthly increase accounting for "
        "withheld months.",
        "age timeline with two rates, stop, and monthly increase",
    ),
    (
        "Think of it less like a toll being taken, and more like a savings clock "
        "quietly running until full retirement age."
    ): (
        "The cleanest model is not a toll or a savings account. It is an "
        "age-limited earnings test followed by a permanent monthly adjustment.",
        "toll and savings icons crossed out beside age-limited test",
    ),
    (
        "When that clock stops, what was paused gets folded into a permanently "
        "higher monthly benefit, not handed back as a lump sum."
    ): (
        "SSA describes a permanently higher monthly benefit accounting for "
        "withheld months, not a lump-sum repayment.",
        "monthly increase graphic beside crossed-out lump sum",
    ),
    (
        "That's the version worth remembering long after this video ends — not "
        "fear, just a formula with a schedule."
    ): (
        "Remember the age-limited formula, its hard stop, and the permanent "
        "monthly increase afterward.",
        "three-step rule summary",
    ),
    (
        "Withheld benefits under the earnings test are better understood as a "
        "permanent boost to your future monthly benefit, not money that "
        "vanishes. If that shortfall becomes a permanently higher monthly "
        "benefit instead of disappearing, what does that change about how you'd "
        "think through claiming while still working?"
    ): (
        "SSA says benefits withheld under the earnings test are not lost. After "
        "full retirement age, the monthly benefit is increased permanently to "
        "account for withheld months. How does that sharper distinction change "
        "the way you frame the decision?",
        "verified SSA quote beside final question",
    ),
    "That's not exotic income. It's an ordinary paycheck for a lot of working retirees — and I think that's exactly why this rule catches people off guard.": (
        "That published line matters because it is the exact point where the "
        "formula changes from no withholding to withholding.",
        "SSA 2026 threshold line highlighted",
    ),
    "That belief pushes people toward real decisions.": (
        "Let's separate two questions before we make any decision from that smaller number.",
        "two-question worksheet on desk",
    ),
    "Cutting hours. Turning down shifts. Quitting a job they didn't actually need to quit.": (
        "And here is why I want us to use careful words: a current reduction is "
        "not the same thing as a permanent loss.",
        "CURRENT REDUCTION versus PERMANENT LOSS",
    ),
    "Draining savings early, out of fear the withheld benefit is gone for good.": (
        "The reduction can still strain today's budget. We do not need to "
        "exaggerate it to take that pain seriously.",
        "current household budget shortfall",
    ),
    "It's an easy leap to make, when a number just gets smaller with no formula shown.": (
        "What we can verify is narrower: current payments are reduced, and a "
        "separate recalculation happens at full retirement age.",
        "withholding then recalculation timeline",
    ),
    "That gap between rule and number is exactly where the 'lost forever' story takes hold.": (
        "So keep those two verified steps separate while we work through the numbers.",
        "two verified steps side by side",
    ),
    "Reading the actual rule takes five minutes. Believing the rumor takes five seconds.": (
        "Let's slow down and read both parts of the rule before we name the result.",
        "SSA rule page read carefully",
    ),
    "That's not a check mailed to you today.": (
        "SSA describes the later change as a higher monthly benefit at full retirement age.",
        "higher monthly benefit after FRA",
    ),
    "The adjustment arrives as a higher monthly benefit later — not as cash back this month.": (
        "That later monthly adjustment does not solve the smaller current payment.",
        "current payment beside later adjustment",
    ),
    "If rent is due this month, a higher benefit five years from now doesn't pay this month's rent.": (
        "A benefit increase at full retirement age cannot cover rent due before full retirement age.",
        "rent envelope before FRA marker",
    ),
    "That's the honest weak point in the 'it all comes back eventually' argument — eventually isn't a grocery bill's timeline.": (
        "That is the weak point in saying timing does not matter: grocery bills "
        "follow today's calendar.",
        "grocery receipt on current calendar",
    ),
    "Even a fully accurate rule can still land unevenly on someone who needed this month's dollars, not next decade's.": (
        "The rule can be accurate and still leave a household with less current benefit income.",
        "current benefit income reduced",
    ),
    "I keep coming back to that sentence — it's the part most explainers skip entirely.": (
        "That is the distinction I want us to carry into the calculation.",
        "WITHHELD NOW and RECALCULATED LATER",
    ),
    "The limit applies to earnings from work — the kind of income SSA actually tracks.": (
        "SSA counts wages from a job and net profit from self-employment, "
        "including bonuses, commissions, and vacation pay.",
        "SSA counted earnings list",
    ),
    "But here's a detail that surprises people: the counting doesn't necessarily run through December.": (
        "It does not count pensions, annuities, investment income, interest, "
        "veterans benefits, or other government or military retirement benefits.",
        "SSA excluded income list",
    ),
    "That's a rule easy to miss if you assume earnings count for the whole year, and it matters directly if 2026 is your milestone year.": (
        "If 2026 is your full-retirement-age year, the month matters as much as "
        "the annual total.",
        "2026 calendar with FRA month",
    ),
    "Full retirement age itself isn't the same for everyone — it depends on your birth year.": (
        "Use the full-retirement-age month SSA identifies for you; this rule "
        "keys off that month.",
        "personal FRA month blank field",
    ),
    "But whatever your specific full retirement age is, these thresholds attach to it, not to one fixed age everyone assumes applies to them.": (
        "For this calculation, the relevant boundary is your own "
        "full-retirement-age month.",
        "personal FRA month highlighted",
    ),
    "Two people born a few months apart can face genuinely different limits in the very same year.": (
        "That is why the worksheet needs a month field, not just one annual "
        "earnings box.",
        "month field beside annual earnings",
    ),
    "Look up your own full retirement age on SSA.gov directly — that number sets your actual threshold, not a birthday everyone assumes.": (
        "On that same page, SSA links an earnings test calculator to show how "
        "work earnings could affect benefit payments.",
        "SSA earnings test calculator link",
    ),
    "I read that jump as SSA acknowledging the transition year deserves different treatment, not just a bigger number for its own sake.": (
        "The published rule itself uses a higher threshold and a different "
        "ratio in that year.",
        "SSA 2026 two-rule comparison",
    ),
    "That's one more reason a flat 'you lose money for working' headline oversimplifies a graduated rule.": (
        "Calling both stages one flat loss hides the higher limit, gentler "
        "ratio, and shorter counting window.",
        "three FRA-year differences",
    ),
    "That's a narrow exception, but it's proof the agency isn't applying one blunt formula the same way to everyone.": (
        "It is a separate path in the published rule, so keep it separate from "
        "the annual formula.",
        "special monthly rule branch",
    ),
    "If you want to see where you stand, there's a simple sequence to run yourself.": (
        "Let's turn the rule into a small worksheet we can fill out together, "
        "without guessing at any SSA value.",
        "three-field worksheet",
    ),
    "First, find your own full retirement age. Second, subtract $24,480 from what you expect to earn this year.": (
        "Before your full-retirement-age year, compare full-year work earnings "
        "with $24,480 and keep only the overage.",
        "full-year earnings minus $24,480",
    ),
    "Whatever's left over — that's the overage. Halve it, and that's what gets withheld.": (
        "Apply $1-for-$2 to that overage. In the full-retirement-age year, use "
        "the separate $65,160 and $1-for-$3 path.",
        "two worksheet formulas side by side",
    ),
    "That $2,760 — I find that number worth pausing on, because it's exactly the size of an ordinary part-time paycheck's overflow.": (
        "That $2,760 is worth pausing on, because a correct formula can still "
        "produce a painful current reduction.",
        "$2,760 current reduction highlighted",
    ),
    "That $2,760, in this hypothetical, is the total withheld from benefits over the year — not the whole check, just a slice of it.": (
        "In this worked example, $2,760 is the formula's annual withholding result.",
        "$2,760 worksheet result",
    ),
    "Notice what that number is not. It's not the whole benefit. It's nowhere near the full $30,000 earned.": (
        "It is not calculated on all $30,000. The formula starts only above the "
        "verified limit.",
        "$30,000 minus verified limit",
    ),
    "That's not a one-time makeup payment. It changes the monthly amount permanently, for as long as that benefit is paid.": (
        "SSA's source describes an ongoing higher monthly amount, and it uses "
        "the word permanently.",
        "PERMANENTLY highlighted in SSA quote",
    ),
    "Not a one-time debt repaid — an ongoing rate, adjusted forward.": (
        "Keep the language exact: current withholding first, permanent monthly "
        "increase at full retirement age.",
        "withholding then permanent increase",
    ),
    "The hypothetical $2,760 withheld doesn't disappear — it's factored into that future permanent increase.": (
        "SSA says the months benefits were withheld are credited in the "
        "recalculation at full retirement age.",
        "withheld months credited at FRA",
    ),
    "It becomes part of the formula behind that future higher monthly benefit.": (
        "Our verified evidence gives the recalculation rule, not this worker's "
        "future dollar amount.",
        "verified rule beside blank future amount",
    ),
    "How much that future increase adds, in dollar terms, isn't specified in SSA's public materials for any individual case.": (
        "A precise future increase would require facts outside this example, so "
        "we will not invent one.",
        "future amount left blank",
    ),
    "Not into some general fund. And not into nothing.": (
        "The verified answer is a sequence, not a destination.",
        "two-stage sequence diagram",
    ),
    "It goes into a recalculation of your own monthly benefit, timed to full retirement age.": (
        "SSA withholds current benefits, then recalculates the monthly benefit "
        "at full retirement age.",
        "withholding then FRA recalculation",
    ),
    "In practice, that mismatch means the withheld amount doesn't help this year's budget — it raises the monthly benefit starting at full retirement age.": (
        "The current reduction does not help today's budget. The later "
        "recalculation changes the monthly benefit from full retirement age onward.",
        "current budget beside later monthly amount",
    ),
    "Calling it a penalty is a simpler story than the actual mechanics. I understand why people reach for it.": (
        "Calling it a penalty is simpler than describing both stages, but it is "
        "less precise.",
        "PENALTY crossed out beside two stages",
    ),
    "Understanding where a dollar goes — even a withheld one — is part of making it last.": (
        "Understanding the sequence helps us plan around the current reduction "
        "without confusing it with permanent loss.",
        "current reduction planning worksheet",
    ),
    "Think of the earnings test as temporary withholding that permanently raises your future benefit — not gone, but not free money either.": (
        "SSA's rule has two stages: benefits may be withheld first, then the "
        "monthly benefit is recalculated permanently to credit those months.",
        "verified two-stage rule summary",
    ),
    "If reading the actual SSA rule instead of the rumor was useful today, that's what this channel does every week — subscribe for the next one.": (
        "If reading the fine print together helped, subscribe. We will keep "
        "turning official rules into plain English, one careful page at a time.",
        "restrained subscribe end card",
    ),
    "So if the shrinkage is temporary and the increase is permanent, what's the real cost of treating this year's smaller check as money lost forever?": (
        "What would help you plan more: knowing the current reduction, or "
        "understanding the later recalculation?",
        "quiet question end card",
    ),
}


def sanitize_ssa_earnings_draft(draft, pack: EvidencePack):
    """Apply narrowly reviewed, exact-match repairs without another full rewrite."""
    subject = _norm(pack.topic)
    if not (
        "social security" in subject
        and any(word in subject for word in ("earn", "withhold", "working"))
    ):
        return draft, []

    applied: list[str] = []

    def repair_scene(scene):
        replacement = _SSA_EARNINGS_EDITORIAL_REPAIRS.get(scene.voiceover)
        if replacement is None:
            return scene
        voiceover, visual = replacement
        applied.append(scene.voiceover)
        updates = {"voiceover": voiceover}
        if visual:
            updates["visual_prompt"] = visual
        return scene.model_copy(update=updates)

    hook_scenes = [repair_scene(scene) for scene in draft.hook_scenes]
    hook_words = sum(len(scene.voiceover.split()) for scene in hook_scenes)
    evidence_corpus = " ".join(
        f"{entry.claim} {entry.value} {entry.quote}"
        for entry in pack.entries
    )
    if (
        hook_words > 100
        and "$24,480" in evidence_corpus
        and len(hook_scenes) >= 5
    ):
        concise_hook = [
            (
                "According to SSA's 2026 page, your Social Security check can "
                "shrink after work earnings cross $24,480.",
                "SSA 2026 page with $24,480 highlighted",
                "slow",
            ),
            (
                "That smaller deposit can hurt now, when rent and groceries "
                "arrive on schedule.",
                "rent envelope and grocery receipt",
                "slow",
            ),
            (
                "But SSA says benefits withheld while you work are not lost.",
                "SSA NOT LOST sentence highlighted",
                "normal",
            ),
            (
                "At full retirement age, it recalculates the monthly benefit "
                "permanently to credit the months it withheld.",
                "withheld months to FRA recalculation",
                "normal",
            ),
            (
                "So let's read the fine print together: cash-flow pain, "
                "a later adjustment, and no pretending those feel the same.",
                "current pain beside later adjustment",
                "slow",
            ),
        ]
        hook_scenes = [
            hook_scenes[index].model_copy(update={
                "voiceover": voiceover,
                "visual_prompt": visual,
                "sfx": None,
                "pace": pace,
                "pause_after_ms": 0 if index < 4 else 500,
                "emphasis": (
                    ["$24,480"] if index == 0
                    else ["not lost"] if index == 2
                    else []
                ),
            })
            for index, (voiceover, visual, pace)
            in enumerate(concise_hook)
        ]
        applied.append("overlong SSA earnings-test hook")
    segments = []
    for segment in draft.segments:
        scenes = [repair_scene(scene) for scene in segment.scenes]
        segments.append(segment.model_copy(update={
            "scenes": scenes,
            "content": " ".join(scene.voiceover for scene in scenes),
        }))
    outro_scenes = [repair_scene(scene) for scene in draft.outro_scenes]
    if not applied:
        return draft, []
    words = sum(
        len(scene.voiceover.split())
        for scene in (
            hook_scenes
            + [scene for segment in segments for scene in segment.scenes]
            + outro_scenes
        )
    )
    repaired = draft.model_copy(update={
        "hook_scenes": hook_scenes,
        "hook": " ".join(scene.voiceover for scene in hook_scenes),
        "segments": segments,
        "outro_scenes": outro_scenes,
        "outro": " ".join(scene.voiceover for scene in outro_scenes),
        "word_count": words,
        "estimated_duration_seconds": round(words / 2.5),
    })
    return repaired, applied


def _atoms_present(wanted: list[str], text: str) -> bool:
    available = Counter(_numeric_atoms(text))
    required = Counter(wanted)
    return all(available[token] >= count for token, count in required.items())


def extract_supporting_quote(
    entry: SourceEvidence,
    page_text: str,
    *,
    max_words: int = 90,
) -> str:
    """Select a verbatim source sentence that actually supports the claim.

    The model proposes a primary page and a narrow claim; Python supplies the
    quotation. Only contiguous words from the fetched page can be returned,
    and every load-bearing numeric atom must occur in the selected passage.
    """
    page = re.sub(r"\s+", " ", page_text or "").strip()
    if not page:
        return ""
    claim_words = _claim_lexemes(entry.claim)
    if len(claim_words) < 2:
        return ""
    # A value-only match is not enough.  A previous pack attached the correct
    # $24,480 sentence to a claim that also asserted the $1-for-$2 mechanism,
    # even though that mechanism was absent from the quotation.  The quote is
    # evidence for the whole claim, so every numeric atom in both fields must
    # occur in the selected passage.
    wanted_numbers = list(dict.fromkeys(
        _numeric_atoms(f"{entry.claim} {entry.value}")))
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", page)
        if len(sentence.split()) >= 5
    ]
    candidates = sentences + [
        f"{left} {right}"
        for left, right in zip(sentences, sentences[1:])
        if len(left.split()) + len(right.split()) <= 90
    ]
    candidates += [
        f"{first} {second} {third}"
        for first, second, third in zip(
            sentences, sentences[1:], sentences[2:])
        if (
            len(first.split()) + len(second.split()) + len(third.split())
            <= 120
        )
    ]
    best = ""
    best_score = 0.0
    for candidate in candidates:
        if wanted_numbers and not _atoms_present(wanted_numbers, candidate):
            continue
        overlap = claim_words & _claim_lexemes(candidate)
        coverage = len(overlap) / max(1, len(claim_words))
        min_hits = 1 if wanted_numbers else 2
        min_coverage = 0.20 if wanted_numbers else 0.30
        if len(overlap) < min_hits or coverage < min_coverage:
            continue
        score = coverage + min(len(overlap), 6) * 0.02
        if score > best_score:
            best, best_score = candidate, score
    if not best:
        return ""
    words = best.split()
    if len(words) > max_words:
        window_best = ""
        window_score = -1.0
        for start in range(0, len(words) - max_words + 1):
            window = " ".join(words[start:start + max_words])
            if wanted_numbers and not _atoms_present(wanted_numbers, window):
                continue
            overlap = claim_words & _claim_lexemes(window)
            score = len(overlap) / max(1, len(claim_words))
            if score > window_score:
                window_best, window_score = window, score
        best = window_best
    return best if len(best.split()) >= 5 else ""


def _claim_quote_support_problems(entry: SourceEvidence) -> list[str]:
    """Check that a verbatim quote supports the asserted mechanism, not just URL.

    This intentionally targets recurring high-stakes claim shapes rather than
    pretending lexical overlap is general-purpose entailment.
    """
    claim = _norm(f"{entry.claim} {entry.value}")
    quote = _norm(entry.quote)
    problems: list[str] = []

    wanted_numbers = list(dict.fromkeys(
        _numeric_atoms(f"{entry.claim} {entry.value}")))
    if wanted_numbers and not _atoms_present(wanted_numbers, entry.quote):
        problems.append(
            "source quote omits a load-bearing number from the claim")

    if "for every" in claim and not (
        "for every" in quote
        and re.search(r"\b(?:withhold|deduct|reduce)\w*\b", quote)
    ):
        problems.append(
            "source quote does not support the asserted withholding ratio")

    recalculation_claim = (
        ("not lost" in claim or "recalculat" in claim)
        and ("withheld" in claim or "withhold" in claim)
    )
    if recalculation_claim and not (
        ("not lost" in quote or "recalculat" in quote
         or "increased permanently" in quote)
        and ("withheld" in quote or "withhold" in quote or "reduced" in quote)
        and ("benefit" in quote)
    ):
        problems.append(
            "source quote does not support recalculation of withheld benefits")

    no_test_claim = (
        ("full retirement age" in claim or "normal retirement age" in claim)
        and (
            "no further" in claim
            or "removes" in claim
            or "regardless of earnings" in claim
            or "test entirely" in claim
        )
    )
    if no_test_claim and not (
        ("no limit" in quote and (
            "starting with the month" in quote
            or "reach full retirement age" in quote))
        or (
            "applies only" in quote
            and ("below normal retirement age" in quote
                 or "below full retirement age" in quote)
        )
    ):
        problems.append(
            "source quote does not support the test ending at retirement age")

    monthly_claim = (
        "monthly" in claim
        and ("first year" in claim or "one year" in claim)
        and ("special" in claim or "transition" in claim)
    )
    if monthly_claim and not (
        "special rule" in quote
        and "one year" in quote
        and ("whole month" in quote or "monthly" in quote)
    ):
        problems.append(
            "source quote does not support the one-year monthly special rule")

    return problems


def verify_entry_against_text(
    entry: SourceEvidence,
    page_text: str,
    *,
    current_year: int,
    allowed_domains: tuple[str, ...] = PRIMARY_SOURCE_DOMAINS,
) -> list[str]:
    """Deterministic checks against bytes fetched by Python, not model memory."""
    problems: list[str] = []
    if not _host_allowed(entry.source_url, allowed_domains):
        problems.append("source URL is not an allowed HTTPS primary-source domain")

    page = _norm(page_text)
    quote = _norm(entry.quote)
    if len(quote.split()) < 5:
        problems.append("source quote is too short to verify uniquely")
    elif quote not in page:
        problems.append("source quote does not occur on the fetched page")

    if entry.value:
        atoms = _numeric_atoms(entry.value)
        value_found = (
            _atoms_present(atoms, page_text)
            if atoms
            else _value_key(entry.value) in _value_key(page_text)
        )
        if not value_found:
            problems.append(
                f"value {entry.value!r} does not occur on the fetched page")

    problems.extend(_claim_quote_support_problems(entry))

    year_match = re.search(r"(?:19|20)\d{2}", entry.as_of or "")
    if not year_match:
        problems.append("as_of has no parseable year")
    else:
        year = int(year_match.group(0))
        if year > current_year:
            problems.append("as_of is in the future")
        if entry.year_sensitive and year != current_year:
            problems.append(
                f"year-sensitive evidence is dated {year}, not {current_year}")
        if entry.year_sensitive and str(year) not in page_text:
            problems.append("rule year does not occur on the fetched page")
    return problems


def _reader_url(url: str) -> str:
    return "https://r.jina.ai/" + url


def _reader_markdown_text(raw: str, source_url: str) -> str:
    """Validate reader provenance and flatten its Markdown decoration."""
    match = re.search(r"(?im)^URL Source:\s*(\S+)\s*$", raw or "")
    if not match or match.group(1).rstrip("/").lower() != source_url.rstrip("/").lower():
        raise ValueError("reader response does not identify the requested primary URL")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)
    text = re.sub(r"[*_`#]", "", text)
    return text


async def fetch_source_text(
    url: str,
    *,
    timeout_s: float = 25.0,
    allowed_domains: tuple[str, ...] = PRIMARY_SOURCE_DOMAINS,
) -> str:
    """Fetch one primary source without trusting a model-proposed host.

    Some US government sites return 403 to non-browser HTTP clients.  For those
    bot-block responses only, fall back to Jina Reader as a transport while
    requiring its ``URL Source`` marker to equal the original allowlisted URL.
    The evidence still has to pass exact quote/value/year checks afterwards.
    """
    if not _host_allowed(url, allowed_domains):
        raise ValueError(
            "source URL is not an allowed HTTPS primary-source domain")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = None
    use_reader = False
    async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout_s, headers=headers) as client:
        response = await client.get(url)
        if response.status_code in {403, 429}:
            use_reader = True
        else:
            response.raise_for_status()
            if not _host_allowed(str(response.url), allowed_domains):
                raise ValueError(
                    "primary source redirected outside the allowed domain set")
            raw = response.text
    if use_reader:
        # Jina rejects a browser-spoofed UA even though it accepts a transparent
        # programmatic verifier UA. Do not reuse the primary-site header set.
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_s,
            headers={
                "User-Agent": "OmniCastEvidenceVerifier/1.0",
                "Accept": "text/plain",
            },
        ) as reader_client:
            reader_response = await reader_client.get(_reader_url(url))
            reader_response.raise_for_status()
            raw = _reader_markdown_text(reader_response.text, url)
    if not use_reader:
        content_type = (response.headers.get("content-type") or "").lower()
        if "pdf" in content_type or response.content.startswith(b"%PDF"):
            raise ValueError(
                "PDF source needs text extraction; choose the official HTML "
                "version for automated verification")
    return _page_text(raw)


def _source_sentence_window(
    page_text: str,
    *required_groups: tuple[str, ...],
    max_sentences: int = 3,
) -> str:
    """Return the shortest verbatim sentence window satisfying every group."""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", page_text or "")
        if len(sentence.split()) >= 4
    ]
    for width in range(1, max_sentences + 1):
        candidates: list[str] = []
        for start in range(0, len(sentences) - width + 1):
            candidate = " ".join(sentences[start:start + width])
            normalized = _norm(candidate)
            if all(
                any(_norm(term) in normalized for term in group)
                for group in required_groups
            ):
                candidates.append(candidate)
        if candidates:
            return min(candidates, key=lambda value: len(value.split()))
    return ""


async def _official_ssa_earnings_pack(
    topic: str,
    *,
    current_year: int,
    allowed_domains: tuple[str, ...],
) -> EvidencePack | None:
    """Parse SSA's stable official HTML before asking a model for source URLs."""
    subject = _norm(topic)
    if not (
        "social security" in subject
        and any(word in subject for word in ("earn", "withhold", "working"))
    ):
        return None

    working_url = (
        "https://www.ssa.gov/benefits/retirement/planner/whileworking.html")
    exempt_url = "https://www.ssa.gov/oact/cola/rtea.html"
    try:
        working_page, exempt_page = await asyncio.gather(
            fetch_source_text(working_url, allowed_domains=allowed_domains),
            fetch_source_text(exempt_url, allowed_domains=allowed_domains),
        )
    except Exception:
        return None

    lower_quote = _source_sentence_window(
        working_page,
        ("under full retirement age for the entire year",),
        ("deduct $1", "withhold $1"),
        ("every $2",),
        (f"for {current_year}",),
    )
    higher_quote = _source_sentence_window(
        working_page,
        ("year you reach full retirement age",),
        ("deduct $1", "withhold $1"),
        ("every $3",),
        (f"in {current_year}, this limit",),
    )
    no_limit_quote = _source_sentence_window(
        working_page,
        ("starting with the month",),
        ("reach full retirement age",),
        ("no limit",),
    )
    pre_fra_quote = _source_sentence_window(
        working_page,
        ("only count your earnings up to the month before",),
        ("reach your full retirement age",),
        ("not your earnings for the entire year",),
    )
    special_quote = _source_sentence_window(
        working_page,
        ("special rule",),
        ("one year",),
        ("whole month",),
    )
    earnings_types_quote = _source_sentence_window(
        working_page,
        ("count only the wages",),
        ("net profit", "self-employed"),
        ("bonuses", "commissions"),
        ("don't count", "do not count"),
        max_sentences=3,
    )
    calculator_quote = _source_sentence_window(
        working_page,
        ("earnings test calculator",),
        ("see how your earnings",),
        ("affect your benefit payments",),
    )
    recalculation_quote = _source_sentence_window(
        exempt_page,
        ('not "lost"', "not lost"),
        ("monthly benefit",),
        ("increased permanently",),
        ("benefits were withheld", "benefits withheld"),
    )
    lower_match = re.search(
        rf"For {current_year}, that limit is (\$[\d,]+)",
        lower_quote,
        re.IGNORECASE,
    )
    higher_match = re.search(
        rf"In {current_year}, this limit on your earnings is (\$[\d,]+)",
        higher_quote,
        re.IGNORECASE,
    )
    if not all((
        lower_quote, higher_quote, no_limit_quote, pre_fra_quote, special_quote,
        earnings_types_quote, calculator_quote, recalculation_quote,
        lower_match, higher_match,
    )):
        return None

    lower_value = lower_match.group(1)
    higher_value = higher_match.group(1)
    common_name = "Social Security Administration — Working While Retired"
    candidates = [
        SourceEvidence(
            claim=(
                f"For {current_year}, the annual earnings limit for someone "
                f"under full retirement age all year is {lower_value}."),
            value=lower_value, source_name=common_name, source_url=working_url,
            as_of=str(current_year), year_sensitive=True, quote=lower_quote,
            quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                "Below full retirement age all year, SSA deducts $1 in "
                "benefits for every $2 earned above the annual limit."),
            value="$1 for every $2", source_name=common_name,
            source_url=working_url, as_of=str(current_year),
            year_sensitive=False, quote=lower_quote,
            quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                f"In the year full retirement age is reached, the "
                f"{current_year} earnings limit is {higher_value}."),
            value=higher_value, source_name=common_name, source_url=working_url,
            as_of=str(current_year), year_sensitive=True, quote=higher_quote,
            quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                "In the year full retirement age is reached, SSA deducts $1 "
                "in benefits for every $3 earned above the different limit."),
            value="$1 for every $3", source_name=common_name,
            source_url=working_url, as_of=str(current_year),
            year_sensitive=False, quote=higher_quote,
            quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                "Starting with the month full retirement age is reached, "
                "there is no earnings limit for receiving benefits."),
            value="", source_name=common_name, source_url=working_url,
            as_of=str(current_year), year_sensitive=False,
            quote=no_limit_quote, quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                "In the year full retirement age is reached, SSA counts only "
                "earnings through the month before full retirement age, not "
                "earnings for the entire year."),
            value="", source_name=common_name, source_url=working_url,
            as_of=str(current_year), year_sensitive=False,
            quote=pre_fra_quote, quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                "Benefits withheld while working are not lost; at normal "
                "retirement age the monthly benefit is increased permanently "
                "to account for months in which benefits were withheld."),
            value="",
            source_name=(
                "Social Security Administration — Earnings Test Exempt Amounts"),
            source_url=exempt_url, as_of=str(current_year),
            year_sensitive=False, quote=recalculation_quote,
            quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                "SSA has a special rule for one year that can pay a full "
                "benefit for a whole month considered retired regardless of "
                "yearly earnings."),
            value="", source_name=common_name, source_url=working_url,
            as_of=str(current_year), year_sensitive=False, quote=special_quote,
            quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                "For the earnings test, SSA counts wages from a job and net "
                "self-employment profit, including bonuses, commissions and "
                "vacation pay; it does not count pensions, annuities, "
                "investment income, interest, veterans benefits, or other "
                "government or military retirement benefits."),
            value="", source_name=common_name, source_url=working_url,
            as_of=str(current_year), year_sensitive=False,
            quote=earnings_types_quote, quote_extracted_from_page=True,
        ),
        SourceEvidence(
            claim=(
                "SSA links an earnings test calculator for eligible people "
                "still working to see how earnings could affect benefit payments."),
            value="", source_name=common_name, source_url=working_url,
            as_of=str(current_year), year_sensitive=False,
            quote=calculator_quote, quote_extracted_from_page=True,
        ),
    ]
    pages = {working_url: working_page, exempt_url: exempt_page}
    for candidate in candidates:
        if verify_entry_against_text(
            candidate, pages[candidate.source_url],
            current_year=current_year, allowed_domains=allowed_domains,
        ):
            return None
    pack = EvidencePack(
        topic=topic,
        entries=[
            entry.model_copy(update={"evidence_id": f"E{index}"})
            for index, entry in enumerate(candidates, 1)
        ],
        verified_at=datetime.now(timezone.utc).isoformat(),
    )
    return (
        pack
        if not evidence_coverage_problems(
            pack, topic, current_year=current_year)
        else None
    )


async def reverify_evidence_pack(
    pack: EvidencePack,
    *,
    current_year: int | None = None,
    allowed_domains: tuple[str, ...] = PRIMARY_SOURCE_DOMAINS,
    min_verified: int = 2,
) -> EvidencePack:
    """Refetch a saved pack and keep only claims that still verify.

    URLs are fetched once even when several claims share a page. No LLM is
    involved, so a retry of the same pipeline topic is deterministic and does
    not spend another research call merely because a later stage failed.
    """
    year = current_year or datetime.now(timezone.utc).year
    official_pack = await _official_ssa_earnings_pack(
        pack.topic,
        current_year=year,
        allowed_domains=allowed_domains,
    )
    if official_pack is not None:
        return official_pack
    urls = list(dict.fromkeys(entry.source_url for entry in pack.entries))

    async def fetch_one(url: str):
        try:
            return url, await fetch_source_text(
                url, allowed_domains=allowed_domains), ""
        except Exception as exc:  # noqa: BLE001
            return url, "", str(exc)

    fetched = {
        url: (text, error)
        for url, text, error in await asyncio.gather(
            *(fetch_one(url) for url in urls))
    }
    valid: list[SourceEvidence] = []
    rejected = list(pack.rejected)
    for entry in pack.entries:
        text, fetch_error = fetched[entry.source_url]
        if fetch_error:
            rejected.append(
                f"{entry.source_url}: fetch failed during cache revalidation: "
                f"{fetch_error}")
            continue
        candidate = entry
        problems = verify_entry_against_text(
            candidate,
            text,
            current_year=year,
            allowed_domains=allowed_domains,
        )
        if problems:
            quote = extract_supporting_quote(candidate, text)
            if quote:
                candidate = candidate.model_copy(update={
                    "quote": quote,
                    "quote_extracted_from_page": True,
                })
                problems = verify_entry_against_text(
                    candidate,
                    text,
                    current_year=year,
                    allowed_domains=allowed_domains,
                )
        if problems:
            rejected.append(
                f"{entry.source_url}: cache revalidation: "
                + "; ".join(problems))
        else:
            valid.append(candidate)
    if len(valid) < min_verified:
        raise ValueError(
            f"cached evidence revalidation left {len(valid)}/{min_verified} "
            "verified claims")
    refreshed = EvidencePack(
        topic=pack.topic,
        entries=valid,
        rejected=rejected,
        verified_at=datetime.now(timezone.utc).isoformat(),
    )
    coverage = evidence_coverage_problems(
        refreshed, pack.topic, current_year=year)
    if coverage:
        raise ValueError(
            "cached evidence is valid but incomplete for the topic: "
            + "; ".join(coverage))
    return refreshed


async def merge_operator_evidence(
    pack: EvidencePack,
    evidence_path: str | Path,
    *,
    current_year: int | None = None,
    allowed_domains: tuple[str, ...] = PRIMARY_SOURCE_DOMAINS,
) -> EvidencePack:
    """Verify operator-supplied evidence entries and append the survivors.

    The official-pack fast path in ``reverify_evidence_pack`` deliberately
    returns ONLY the curated SSA pack for earnings-test topics — right for the
    rule numbers, but it silently discards operator-researched news evidence
    (live failure 2026-08-01: verified govinfo bill facts vanished on
    revalidation, and the figure gate then rejected every bill number as
    unverified). This channel is NOT a bypass: every entry is refetched and
    quote-verified with the same fail-closed checks before it may join the
    pack; failures land in ``rejected`` where the operator can see them.
    """
    year = current_year or datetime.now(timezone.utc).year
    raw = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    raw_entries = raw.get("entries", raw) if isinstance(raw, dict) else raw
    entries = [SourceEvidence.model_validate(e) for e in raw_entries]

    have = {e.evidence_id for e in pack.entries}
    urls = list(dict.fromkeys(e.source_url for e in entries))
    fetched: dict[str, tuple[str, str]] = {}
    for url in urls:
        try:
            fetched[url] = (
                await fetch_source_text(url, allowed_domains=allowed_domains),
                "")
        except Exception as exc:  # noqa: BLE001 — recorded, never silent
            fetched[url] = ("", str(exc))

    valid = list(pack.entries)
    rejected = list(pack.rejected)
    for entry in entries:
        if entry.evidence_id in have:
            rejected.append(
                f"operator evidence {entry.evidence_id}: id already present "
                "in the verified pack; skipped")
            continue
        text, fetch_error = fetched[entry.source_url]
        if fetch_error:
            rejected.append(
                f"operator evidence {entry.evidence_id}: fetch failed: "
                f"{fetch_error}")
            continue
        problems = verify_entry_against_text(
            entry, text, current_year=year, allowed_domains=allowed_domains)
        if problems:
            rejected.append(
                f"operator evidence {entry.evidence_id}: "
                + "; ".join(problems))
            continue
        valid.append(entry)
        have.add(entry.evidence_id)
    return pack.model_copy(update={"entries": valid, "rejected": rejected})


async def evidence_for_topic(
    agent: "EvidenceResearchAgent",
    topic: str,
    cache_path: str | Path,
) -> tuple[EvidencePack, bool]:
    """Return a reverified same-topic cache or run fresh research.

    ``bool`` reports whether no research LLM call was needed. A corrupt,
    mismatched, or no-longer-verifiable cache is never trusted; it simply falls
    through to the normal fail-closed research path.
    """
    path = Path(cache_path)
    if path.exists():
        try:
            saved = EvidencePack.model_validate_json(
                path.read_text(encoding="utf-8"))
            if saved.topic.strip().casefold() == topic.strip().casefold():
                pack = await reverify_evidence_pack(saved)
                path.write_text(
                    pack.model_dump_json(indent=2), encoding="utf-8")
                return pack, True
        except Exception:
            pass
    pack = await agent.execute(topic)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pack.model_dump_json(indent=2), encoding="utf-8")
    return pack, False


class EvidenceResearchAgent(BaseAgent):
    """Propose, fetch and verify a minimum evidence pack before writing."""

    @property
    def name(self) -> str:
        return "evidence_research"

    @property
    def system_prompt(self) -> str:
        return (
            "You are a source researcher for a US retirement-finance newsroom. "
            "Use primary sources only. Never invent a URL or paraphrase a quote. "
            "Every quote must be a short verbatim excerpt you expect to occur on "
            "the linked HTML page. Return JSON only."
        )

    async def execute(
        self,
        topic: str,
        *,
        current_year: int | None = None,
        allowed_domains: tuple[str, ...] = PRIMARY_SOURCE_DOMAINS,
        min_verified: int = 2,
    ) -> EvidencePack:
        year = current_year or datetime.now(timezone.utc).year
        domain_text = ", ".join(allowed_domains)
        official_pack = await _official_ssa_earnings_pack(
            topic,
            current_year=year,
            allowed_domains=allowed_domains,
        )
        if official_pack is not None:
            return official_pack
        failures: list[str] = []
        verified: list[SourceEvidence] = []

        for attempt in range(2):
            feedback = ""
            if failures:
                feedback = (
                    "\nPREVIOUS CANDIDATES FAILED LIVE FETCH/VERIFICATION:\n- "
                    + "\n- ".join(failures[-12:])
                    + "\nUse different official HTML pages or correct the exact quote.")
            prompt = f"""Build a compact evidence pack before a script is written.

TOPIC: {topic}
CURRENT RULE YEAR: {year}
ALLOWED PRIMARY DOMAINS: {domain_text}

Return 3-8 entries. Each entry needs:
- claim: the narrow fact the page supports, with no advice or causal overreach;
- value: exact load-bearing figure if any, otherwise empty;
- source_name and direct HTTPS source_url;
- as_of year; year_sensitive=true for limits, thresholds, premiums, brackets,
  COLA and other figures that change annually;
- quote: 5-35 words copied verbatim from the linked HTML page and containing
  the value when one exists.
- The quote must support EVERY clause and every number in claim, not merely
  occur somewhere on the same page. If one short quote cannot support a
  threshold and a ratio together, split them into separate narrow entries.

Coverage is mandatory, not optional:
- Answer every explicit number/date/mechanism requested by the TOPIC.
- Put ONE load-bearing figure in each entry. Never hide a current threshold in
  the quote while leaving value empty or using value for a different ratio.
- For a current-year Social Security earnings-test topic, include the exact
  lower annual exempt amount as its own year_sensitive entry and include the
  later recalculation/credit mechanism. Include the higher FRA-year amount as
  a separate entry when it is relevant.
- Do not include adjacent Social Security figures such as the payroll-tax
  contribution and benefit base unless the TOPIC explicitly asks for them.

Prefer official HTML pages over PDFs. Do not use search-result URLs, news
articles, competitor videos, snippets, blogs, or model memory as evidence.
Do not output evidence_id; the verifier assigns it after live validation.
{feedback}"""
            _, draft = await self.call_llm_structured(
                [{"role": "system", "content": self.system_prompt},
                 {"role": "user", "content": prompt}],
                output_schema=_EvidenceDraft,
                max_tokens=6000,
                temperature=0.1,
            )

            async def verify(candidate: SourceEvidence):
                try:
                    text = await fetch_source_text(
                        candidate.source_url, allowed_domains=allowed_domains)
                    problems = verify_entry_against_text(
                        candidate, text, current_year=year,
                        allowed_domains=allowed_domains)
                    if problems:
                        extracted = extract_supporting_quote(candidate, text)
                        if extracted:
                            candidate = candidate.model_copy(update={
                                "quote": extracted,
                                "quote_extracted_from_page": True,
                            })
                            problems = verify_entry_against_text(
                                candidate, text, current_year=year,
                                allowed_domains=allowed_domains)
                except Exception as exc:  # noqa: BLE001 — becomes research feedback
                    problems = [f"fetch failed: {exc}"]
                return candidate, problems

            checked = await asyncio.gather(
                *(verify(entry) for entry in draft.entries))
            for candidate, problems in checked:
                if problems:
                    failures.append(
                        f"{candidate.source_url}: {'; '.join(problems)}")
                    continue
                duplicate = any(
                    e.source_url == candidate.source_url
                    and _norm(e.claim) == _norm(candidate.claim)
                    for e in verified)
                if not duplicate:
                    verified.append(candidate)
            coverage: list[str] = []
            if len(verified) >= min_verified:
                probe = EvidencePack(
                    topic=topic,
                    entries=[
                        entry.model_copy(update={"evidence_id": f"E{i}"})
                        for i, entry in enumerate(verified, 1)
                    ],
                )
                coverage = evidence_coverage_problems(
                    probe, topic, current_year=year)
            if len(verified) >= min_verified and not coverage:
                break
            failures.extend(
                f"TOPIC COVERAGE: {problem}" for problem in coverage
                if f"TOPIC COVERAGE: {problem}" not in failures)

        if len(verified) < min_verified:
            raise ValueError(
                f"only {len(verified)}/{min_verified} source claims survived "
                "live verification: " + "; ".join(failures[-8:]))

        coverage = evidence_coverage_problems(
            EvidencePack(topic=topic, entries=verified),
            topic,
            current_year=year,
        )
        if coverage:
            raise ValueError(
                "verified sources did not cover the topic: "
                + "; ".join(coverage))

        numbered = [
            entry.model_copy(update={"evidence_id": f"E{i}"})
            for i, entry in enumerate(verified, 1)
        ]
        return EvidencePack(
            topic=topic,
            entries=numbered,
            rejected=failures,
            verified_at=datetime.now(timezone.utc).isoformat(),
        )


def gate_ledger_against_pack(ledger, pack: EvidencePack) -> list[str]:
    """Ensure post-writing attribution cannot escape pre-verified sources."""
    allowed_urls = {entry.source_url.rstrip("/") for entry in pack.entries}
    allowed_values = {
        value
        for entry in pack.entries
        for value, _ in _spoken_numeric_values(
            f"{entry.value} {entry.as_of}")
    }
    # A verified $1-for-$2/$3 rule also verifies its exact percentage
    # equivalent when the ledger renders the same mechanism that way.
    for entry in pack.entries:
        ratio = re.search(
            r"\$?(\d+(?:\.\d+)?)[^.;]{0,50}?for every\s+\$?"
            r"(\d+(?:\.\d+)?)",
            _norm(f"{entry.value} {entry.claim}"),
        )
        if ratio:
            numerator, denominator = map(float, ratio.groups())
            if denominator:
                percentage = numerator / denominator * 100
                if percentage.is_integer():
                    allowed_values.add(int(percentage))
    problems: list[str] = []
    for i, entry in enumerate(getattr(ledger, "entries", ()) or (), 1):
        source_name = (getattr(entry, "source_name", "") or "").lower()
        if "worked example" in source_name:
            continue
        url = (getattr(entry, "source_url", "") or "").rstrip("/")
        if not url:
            problems.append(f"entry {i} has no source_url from verified evidence pack")
        elif url not in allowed_urls:
            problems.append(
                f"entry {i} cites a source not verified before writing: {url}")
        raw_value = (getattr(entry, "value", "") or "").strip()
        placeholder = _norm(raw_value) in {
            "", "qualitative", "(qualitative)", "n/a", "none", "not applicable"}
        ledger_values = {
            value for value, _ in _spoken_numeric_values(raw_value)
        }
        if (
            not placeholder
            and ledger_values
            and allowed_values
            and not ledger_values.issubset(allowed_values)
        ):
            problems.append(
                f"entry {i} value {raw_value!r} was not in "
                "the pre-writing evidence pack")
    return problems


def fact_ledger_from_evidence_pack(
    script_text: str,
    pack: EvidencePack,
    *,
    current_year: int,
):
    """Bind verified figures without asking an LLM to rediscover their source.

    The script has already passed ``gate_draft_against_pack``: every official
    figure must come from this pack and every illustrative input must live in
    a backstage EXAMPLE/HYPOTHETICAL section. Build the numeric ledger from
    those two typed sources, leaving the LLM ledger as a fallback only when this
    deterministic binding cannot cover the script.
    """
    from omnicast.compliance.fact_ledger import (
        FactEntry,
        FactLedger,
        numeric_tokens,
    )

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", script_text or "")
        if sentence.strip()
    ]

    def sentence_for(keys: set[tuple[str, float]]) -> str:
        for sentence in sentences:
            sentence_keys = {token.key for token in numeric_tokens(sentence)}
            if keys and keys.issubset(sentence_keys):
                return sentence
        return ""

    entries: list[FactEntry] = []
    pack_keys: set[tuple[str, float]] = set()
    for source in pack.entries:
        tokens = numeric_tokens(source.value or "")
        keys = {token.key for token in tokens}
        pack_keys.update(keys)
        if not keys:
            continue
        spoken_claim = sentence_for(keys) or source.claim
        entries.append(FactEntry(
            claim=spoken_claim,
            value=source.value,
            source_name=source.source_name,
            source_url=source.source_url,
            as_of=source.as_of or str(current_year),
            year_sensitive=source.year_sensitive,
            section=source.evidence_id,
        ))

    # Bracketed headings are the canonical flattened product format.
    sections = re.split(r"(?m)^\[([^\]]+)\]\s*$", script_text or "")
    for index in range(1, len(sections), 2):
        heading = sections[index].strip()
        if (
            "hypothetical" not in heading.lower()
            and "example" not in heading.lower()
        ):
            continue
        body = sections[index + 1] if index + 1 < len(sections) else ""
        body_sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", body)
            if sentence.strip()
        ]
        for token in numeric_tokens(body):
            if token.key in pack_keys:
                continue
            if token.kind == "year" and int(token.value) == current_year:
                continue
            claim = next(
                (
                    sentence for sentence in body_sentences
                    if token.key in {
                        item.key for item in numeric_tokens(sentence)
                    }
                ),
                f"Illustrative worked-example value {token.raw}",
            )
            entries.append(FactEntry(
                claim=claim,
                value=token.raw,
                source_name="worked example (illustrative input)",
                source_url="",
                as_of=str(current_year),
                year_sensitive=False,
                section=heading,
            ))

    return FactLedger(entries=entries).stamp(
        script_text, "verified_evidence_pack")
