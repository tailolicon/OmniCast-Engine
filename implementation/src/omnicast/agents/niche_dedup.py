"""Niche Dedup Agent — semantic similarity via DeepSeek Flash.

WHY NOT JACCARD:
  "Insomnia for adults 50+" vs "Sleep difficulty in older adults"
  Jaccard score ≈ 0.1 (different words) → reports as different niche.
  Flash understands semantics → correctly flags as duplicate.

TWO-STAGE PIPELINE (solves Context Window Bloat at scale):
  Stage 1 — Python keyword pre-filter (O(N), zero cost):
    Tokenize niche_name + audience → score each vault niche by shared tokens.
    Keep only top MAX_CANDIDATES (default 20) by keyword overlap.
    Purpose: HIGH RECALL — don't miss real candidates.

  Stage 2 — LLM semantic check (Flash, ~$0.0002/call):
    Send only the 20 candidates from Stage 1 to Flash.
    Flash does semantic reasoning: "insomnia" ≡ "sleep difficulty"
    Purpose: HIGH PRECISION — reject false positives from Stage 1.

SCALING:
  100  vault niches → send 20 to LLM  (same cost always)
  2000 vault niches → still send 20 to LLM  (O(1) LLM cost regardless of vault size)
  Stage 1 is pure Python string ops — handles 10k niches in <100ms.

FLOW (called from niche_flow.py --scan, before saving cache):
  1. Load existing vault niches (status != archived)
  2. Stage 1: keyword_prefilter() → top 20 candidates per new niche
  3. Stage 2: LLM check on top 20 only
  4. Return (kept, duplicates, borderline) lists

COST: ~$0.0002 × 15 new niches = $0.003/scan regardless of vault size.
"""

from __future__ import annotations

import json
import re
import string
import structlog

from omnicast.llm.client import LLMClient

logger = structlog.get_logger()

# Similarity thresholds
DUPLICATE_THRESHOLD = 0.85    # auto-skip, don't save
BORDERLINE_THRESHOLD = 0.60   # warn user, ask before save

# Stage 1: how many candidates to send to LLM
MAX_CANDIDATES = 20

# English stop words to skip in keyword scoring
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "this", "that", "these", "those",
    "i", "you", "he", "she", "it", "we", "they", "their", "your", "my",
    "who", "which", "what", "how", "when", "where", "not", "no", "s",
    "people", "video", "channel", "youtube", "content", "viewers",
})


def _tokenize(text: str) -> set[str]:
    """Lowercase + strip punctuation + remove stop words → set of meaningful tokens."""
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return {w for w in text.split() if w not in _STOP_WORDS and len(w) > 2}


def keyword_prefilter(
    new_niche: dict,
    vault_niches: list[dict],
    top_n: int = MAX_CANDIDATES,
) -> list[dict]:
    """Stage 1: Python keyword overlap scoring — O(N), zero LLM cost.

    Scores each vault niche by how many tokens it shares with the new niche.
    Returns top_n candidates sorted by overlap score descending.

    This is a HIGH-RECALL filter: it may include false positives
    (e.g. "finance tips" vs "finance fraud"). Stage 2 LLM removes those.

    It should NOT miss real duplicates — "insomnia" tokens ("insomnia",
    "sleep", "adults", "50") will match "sleep difficulty older adults"
    tokens ("sleep", "difficulty", "older", "adults"). Enough overlap
    to surface in top 20 even without synonym matching.
    """
    if not vault_niches:
        return []

    # Build token set for the new niche from name + audience + category
    new_text = " ".join([
        new_niche.get("niche_name", ""),
        new_niche.get("audience_description", ""),
        new_niche.get("category", ""),
        " ".join(new_niche.get("pain_points", [])[:3]),
    ])
    new_tokens = _tokenize(new_text)

    if not new_tokens:
        # No meaningful tokens → return all (up to top_n) to be safe
        return vault_niches[:top_n]

    scored: list[tuple[float, dict]] = []
    for vn in vault_niches:
        vault_text = " ".join([
            vn.get("niche_name", ""),
            vn.get("audience_description", ""),
            vn.get("category", ""),
        ])
        vault_tokens = _tokenize(vault_text)

        if not vault_tokens:
            scored.append((0.0, vn))
            continue

        shared = new_tokens & vault_tokens
        # Score = |shared| / sqrt(|new| * |vault|)  — normalized overlap
        # Better than raw count (avoids bias toward longer descriptions)
        score = len(shared) / (len(new_tokens) * len(vault_tokens)) ** 0.5
        scored.append((score, vn))

    # Sort descending by score, take top_n
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = [vn for _, vn in scored[:top_n]]

    logger.debug(
        "Dedup prefilter",
        new_niche=new_niche.get("niche_id", ""),
        vault_total=len(vault_niches),
        candidates_sent=len(candidates),
        top_score=round(scored[0][0], 3) if scored else 0,
    )
    return candidates


def _build_dedup_prompt(new_niche: dict, existing_niches: list[dict]) -> str:
    existing_list = []
    for n in existing_niches:
        existing_list.append({
            "niche_id": n.get("niche_id", ""),
            "niche_name": n.get("niche_name", ""),
            "audience": n.get("audience_description", n.get("niche_data", {}).get("audience_description", "")),
            "category": n.get("category", n.get("niche_data", {}).get("category", "")),
            "status": n.get("status", "watching"),
        })

    new_summary = {
        "niche_name": new_niche.get("niche_name", ""),
        "audience": new_niche.get("audience_description", ""),
        "category": new_niche.get("category", ""),
    }

    return f"""You are a YouTube niche deduplication system.

Check if a newly discovered niche is semantically equivalent to any existing vault niche.
Two niches are DUPLICATE if they target the SAME core audience on the SAME topic angle,
even if worded differently.

DUPLICATE examples (same audience + topic):
  "Insomnia for adults 50+" ≡ "Sleep difficulty in older adults"
  "Dividend investing retirees" ≡ "Passive income investing retirement"
  "Dog training puppies" ≡ "Puppy behavior correction"

NOT DUPLICATE examples (different audience OR topic):
  "Sleep optimization" vs "Belly fat loss" → different topic
  "Dog training" vs "Dog health" → different angle, same audience but not same content
  "Finance for 30yo" vs "Finance for 60yo" → same topic, different audience

EXISTING VAULT NICHES:
{json.dumps(existing_list, indent=1, ensure_ascii=False)}

NEW NICHE TO CHECK:
{json.dumps(new_summary, indent=1, ensure_ascii=False)}

Return JSON only, no markdown:
{{
  "results": [
    {{
      "existing_niche_id": "niche_id_here",
      "similarity_score": 0.0,
      "is_duplicate": false,
      "reason": "one sentence max"
    }}
  ],
  "verdict": "unique|duplicate|borderline",
  "top_match_id": "niche_id or null",
  "top_match_score": 0.0
}}

Rules:
- similarity_score > {DUPLICATE_THRESHOLD} → is_duplicate: true, verdict: "duplicate"
- similarity_score {BORDERLINE_THRESHOLD}-{DUPLICATE_THRESHOLD} → is_duplicate: false, verdict: "borderline"
- All scores < {BORDERLINE_THRESHOLD} → verdict: "unique"
- verdict is determined by the HIGHEST similarity_score found"""


class NicheDedupAgent:
    """Semantic niche deduplication using DeepSeek Flash."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @property
    def name(self) -> str:
        return "niche_dedup"

    async def check_one(
        self,
        new_niche: dict,
        existing_niches: list[dict],
    ) -> dict:
        """Check one new niche against existing vault niches.

        Two-stage:
          Stage 1 — keyword_prefilter(): top MAX_CANDIDATES by token overlap (Python, free)
          Stage 2 — LLM prompt on those candidates only (Flash, ~$0.0002)

        This keeps LLM context fixed at MAX_CANDIDATES regardless of vault size.

        Returns:
            {
                "verdict": "unique|duplicate|borderline",
                "top_match_id": str | None,
                "top_match_score": float,
                "top_match_reason": str,
                "results": [...],
                "prefilter_candidates": int,  # how many Stage 1 kept
                "vault_total": int,           # total vault size
            }
        """
        if not existing_niches:
            return {
                "verdict": "unique",
                "top_match_id": None,
                "top_match_score": 0.0,
                "top_match_reason": "No existing niches in vault",
                "results": [],
                "prefilter_candidates": 0,
                "vault_total": 0,
            }

        # Stage 1: fast Python keyword pre-filter
        candidates = keyword_prefilter(new_niche, existing_niches, top_n=MAX_CANDIDATES)

        prompt = _build_dedup_prompt(new_niche, candidates)

        try:
            response = await self.llm.complete(
                system=(
                    "You are a YouTube niche deduplication system. "
                    "Return valid JSON only. No markdown. No explanations outside JSON."
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            text = response.content.strip()
            # Strip markdown fences if present
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)

            verdict = data.get("verdict", "unique")
            top_id = data.get("top_match_id")
            top_score = float(data.get("top_match_score", 0.0))

            # Find reason for top match
            top_reason = ""
            for r in data.get("results", []):
                if r.get("existing_niche_id") == top_id:
                    top_reason = r.get("reason", "")
                    break

            logger.info(
                "Niche dedup check",
                new_niche=new_niche.get("niche_id", ""),
                verdict=verdict,
                top_match=top_id,
                top_score=top_score,
                vault_total=len(existing_niches),
                candidates_checked=len(candidates),
            )

            return {
                "verdict": verdict,
                "top_match_id": top_id,
                "top_match_score": top_score,
                "top_match_reason": top_reason,
                "results": data.get("results", []),
                "prefilter_candidates": len(candidates),
                "vault_total": len(existing_niches),
            }

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "Niche dedup parse failed",
                niche=new_niche.get("niche_id", ""),
                error=str(exc),
            )
            # Fail open — keep niche if dedup fails
            return {
                "verdict": "unique",
                "top_match_id": None,
                "top_match_score": 0.0,
                "top_match_reason": f"Dedup check failed: {exc}",
                "results": [],
                "prefilter_candidates": len(candidates),
                "vault_total": len(existing_niches),
            }

    async def filter_niches(
        self,
        new_niches: list[dict],
        existing_niches: list[dict],
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Filter a batch of new niches against existing vault niches.

        Returns:
            kept      — clearly unique (score < BORDERLINE_THRESHOLD)
            duplicates — auto-skipped (score >= DUPLICATE_THRESHOLD)
            borderline — score in [BORDERLINE_THRESHOLD, DUPLICATE_THRESHOLD)
                         → caller should ask user
        """
        import asyncio

        kept: list[dict] = []
        duplicates: list[dict] = []
        borderline: list[dict] = []

        async def _check(niche: dict) -> None:
            result = await self.check_one(niche, existing_niches)
            score = result["top_match_score"]
            niche["_dedup"] = result

            if score >= DUPLICATE_THRESHOLD:
                duplicates.append(niche)
            elif score >= BORDERLINE_THRESHOLD:
                borderline.append(niche)
            else:
                kept.append(niche)

        await asyncio.gather(*[_check(n) for n in new_niches])

        # Preserve original score order for kept
        kept.sort(key=lambda n: n.get("total_score", 0), reverse=True)

        return kept, duplicates, borderline
