"""Channel Name Debate — 4-stage LLM pipeline to select optimal channel name.

PROBLEM:
  Single LLM call generates a name with no alternatives, no handle availability check.
  A bad name or a taken handle (@RetirementClarity7892) destroys the trust score
  we spend the entire pipeline trying to build.

PIPELINE:
  Stage 1   — Generator (Flash): 6 distinct name candidates, each targeting a
               different psychographic angle (authority, outcome, community…)
  Stage 1.5 — Handle Check (HTTP/API): verify each @Handle on YouTube in parallel.
               Marks candidates [Available] / [TAKEN] BEFORE scoring and selection.
               Rationale: a TAKEN handle forces ugly suffixes that signal spam/clone
               and collapse audience trust — the most weighted scoring dimension.
  Stage 2   — Critic (Flash): scores each candidate on 4 audience-specific
               dimensions: trust, memorability, searchability, differentiation.
               TAKEN handles get an automatic -2.0 trust penalty.
  Stage 3   — Selector (Chat): holistic winner selection. Prompt injects handle
               availability so it strongly prefers handles that are still clean.

KEY INSIGHT:
  Name fit is audience-dependent. "CryptoClarity" → wrong for 65+ retirees.
  "Retirement Clarity" + @RetirementClarity available → perfect combination.
  "Retirement Clarity" + @RetirementClarity TAKEN → must pick runner-up or adjust.

USAGE:
  agent = ChannelNameDebateAgent(flash_llm=flash, chat_llm=chat, yt_api_key="...")
  result = await agent.debate(niche_dict)
  # result.winner.name, result.winner.handle, result.winner.handle_available
"""

from __future__ import annotations

import asyncio
import json
import re
import textwrap
from dataclasses import dataclass, field

import structlog

from omnicast.llm.client import LLMClient

logger = structlog.get_logger()

# Psychographic angles — each candidate must target a DIFFERENT one
NAME_ANGLES = [
    "authority",       # "The Expert" signal — credentialed, trusted voice
    "outcome",         # Direct result promise — "Retirement Clarity", "DebtFree Path"
    "community",       # Belonging / identity — "Retiree Nation", "50+ Investors"
    "simplicity",      # Anti-complexity — "Plain Money", "Simple Senior Finance"
    "challenge",       # Provocative / contrarian — "What Banks Hide", "Stop Losing"
    "guide",           # Companion / mentor role — "Your Retirement Guide", "Senior Advisor"
]

# Scoring dimensions weights for total_score
SCORE_WEIGHTS = {
    "audience_trust":    0.35,   # most critical for health/finance niches targeting 50+
    "memorability":      0.25,
    "searchability":     0.25,
    "differentiation":   0.15,
}

# Trust penalty applied to TAKEN handles during scoring
TAKEN_HANDLE_TRUST_PENALTY = 2.0   # -2.0 on audience_trust (0-10 scale)

# Handle check timeout — fail-safe: don't block debate if YouTube is slow
HANDLE_CHECK_TIMEOUT_SECS = 6.0


@dataclass
class NameCandidate:
    name: str
    channel_id: str             # snake_case, max 25 chars
    angle: str                  # which psychographic angle
    rationale: str              # why this name works for this audience
    audience_trust: float       # 0-10
    memorability: float         # 0-10
    searchability: float        # 0-10
    differentiation: float      # 0-10
    handle_available: bool | None = None    # None = not checked; True = available; False = taken
    total_score: float = field(init=False)
    handle: str = field(init=False)         # @CamelCase derived from name

    def __post_init__(self) -> None:
        self.handle = _to_youtube_handle(self.name)
        self.total_score = round(
            self.audience_trust    * SCORE_WEIGHTS["audience_trust"]
            + self.memorability    * SCORE_WEIGHTS["memorability"]
            + self.searchability   * SCORE_WEIGHTS["searchability"]
            + self.differentiation * SCORE_WEIGHTS["differentiation"],
            2,
        )


@dataclass
class DebateResult:
    winner: NameCandidate
    runner_up: NameCandidate | None
    all_candidates: list[NameCandidate]
    selection_reason: str


def _to_channel_id(name: str) -> str:
    """Convert display name → snake_case channel_id, max 25 chars."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:25].rstrip("_")


def _to_youtube_handle(name: str) -> str:
    """Convert display name → @CamelCase YouTube handle, max 30 chars.

    YouTube handle rules: letters, numbers, underscores, hyphens, periods.
    Max 30 chars. No leading/trailing special chars.

    Examples:
        "Retirement Clarity"       → "@RetirementClarity"
        "What Wall Street Hides"   → "@WhatWallStreetHides"
        "Senior Money & Life"      → "@SeniorMoneyLife"
    """
    # Strip everything except letters, numbers, spaces
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", name)
    words = clean.split()
    handle = "".join(w.capitalize() for w in words)
    handle = handle.strip("-.")[:30]
    return f"@{handle}" if handle else "@Channel"


class ChannelNameDebateAgent:
    """4-stage LLM debate (with handle availability check) to select optimal
    YouTube channel name for a niche."""

    def __init__(
        self,
        flash_llm: LLMClient,
        chat_llm: LLMClient,
        yt_api_key: str = "",
    ) -> None:
        self._flash = flash_llm
        self._chat = chat_llm
        self._yt_api_key = yt_api_key

    async def debate(
        self,
        niche: dict,
        n_candidates: int = 6,
    ) -> DebateResult:
        """Run full 4-stage debate. Returns DebateResult with winner + all candidates."""
        candidates = await self._stage1_generate(niche, n_candidates)
        if not candidates:
            fallback_name = niche.get("niche_name", "New Channel")
            fb = NameCandidate(
                name=fallback_name,
                channel_id=_to_channel_id(fallback_name),
                angle="outcome",
                rationale="Fallback: LLM generation failed",
                audience_trust=6.0,
                memorability=6.0,
                searchability=7.0,
                differentiation=5.0,
                handle_available=None,
            )
            return DebateResult(winner=fb, runner_up=None, all_candidates=[fb],
                                selection_reason="Fallback due to generation failure")

        # Stage 1.5: handle availability — parallel, non-blocking
        candidates = await self._stage1_5_check_handles(candidates)

        scored = await self._stage2_score(niche, candidates)
        winner, runner_up, reason = await self._stage3_select(niche, scored)
        return DebateResult(
            winner=winner,
            runner_up=runner_up,
            all_candidates=scored,
            selection_reason=reason,
        )

    # ── Stage 1: Generator ────────────────────────────────────────────────────

    async def _stage1_generate(
        self, niche: dict, n_candidates: int
    ) -> list[NameCandidate]:
        angles = NAME_ANGLES[:n_candidates]
        audience = niche.get("audience_description", "general adults")
        pain_summary = ", ".join(niche.get("pain_points", [])[:3])
        existing = ", ".join(niche.get("example_channels", [])[:4])

        prompt = textwrap.dedent(f"""
            You are a YouTube channel naming strategist.

            NICHE: {niche.get('niche_name')}
            CATEGORY: {niche.get('category')}
            TARGET AUDIENCE: {audience}
            PRIMARY PAIN POINTS: {pain_summary}
            EXISTING CHANNELS TO DIFFERENTIATE FROM: {existing or 'none listed'}

            Generate exactly {n_candidates} channel name candidates.
            Each MUST target a different psychographic angle from this list:
            {json.dumps(angles)}

            RULES:
            - Names must resonate with the EXACT target audience above (age, fears, language)
            - 2-4 words max. No generic names like "Tips & Tricks" or "Info Channel"
            - Avoid names already used by existing channels listed above
            - Do NOT add "TV", "YouTube", "Official" suffixes
            - Use vocabulary that matches how the audience TALKS about their problem

            Return JSON array only:
            [
              {{
                "name": "Display Name Here",
                "channel_id": "snake_case_max_25_chars",
                "angle": "{angles[0]}",
                "rationale": "1 sentence why this name resonates with this specific audience"
              }},
              ...
            ]
        """).strip()

        try:
            resp = await self._flash.complete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a channel naming expert. Respond in valid JSON only.",
                max_tokens=4000,
                temperature=0.7,
            )
            content = _strip_json_fences(resp.content)
            raw = json.loads(content)
            candidates = []
            for item in raw[:n_candidates]:
                c_id = item.get("channel_id") or _to_channel_id(item["name"])
                candidates.append(NameCandidate(
                    name=item["name"],
                    channel_id=c_id[:25],
                    angle=item.get("angle", "outcome"),
                    rationale=item.get("rationale", ""),
                    audience_trust=0.0,   # filled in stage 2
                    memorability=0.0,
                    searchability=0.0,
                    differentiation=0.0,
                    handle_available=None,
                ))
            logger.info("Stage 1 complete", candidates=len(candidates))
            return candidates
        except Exception as exc:
            import traceback as _tb
            logger.warning("Stage 1 failed", error=type(exc).__name__, detail=str(exc)[:200], traceback=_tb.format_exc()[-500:])
            return []

    # ── Stage 1.5: Handle Availability Check ─────────────────────────────────

    async def _stage1_5_check_handles(
        self, candidates: list[NameCandidate]
    ) -> list[NameCandidate]:
        """Check all handles in parallel. Marks handle_available on each candidate.

        Strategy:
          - If yt_api_key provided → YouTube Data API v3 (reliable, free quota)
          - Otherwise → HTTP HEAD to youtube.com/@Handle (no key, but rate-limited)
          - Timeout: HANDLE_CHECK_TIMEOUT_SECS per request (fail-safe: None = unknown)
        """
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not available, skipping handle check")
            return candidates

        async with httpx.AsyncClient(timeout=HANDLE_CHECK_TIMEOUT_SECS) as http:
            tasks = [self._check_one_handle(c.handle, http) for c in candidates]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        updated = []
        for cand, avail in zip(candidates, results):
            if isinstance(avail, Exception):
                availability = None   # unknown — don't penalize
            else:
                availability = avail

            available_str = (
                "[OK] available" if availability is True
                else "[X] TAKEN" if availability is False
                else "? unknown"
            )
            logger.info(
                "Handle check",
                handle=cand.handle,
                available=available_str,
            )
            # Rebuild candidate with handle_available set
            updated.append(NameCandidate(
                name=cand.name,
                channel_id=cand.channel_id,
                angle=cand.angle,
                rationale=cand.rationale,
                audience_trust=cand.audience_trust,
                memorability=cand.memorability,
                searchability=cand.searchability,
                differentiation=cand.differentiation,
                handle_available=availability,
            ))

        available_count = sum(1 for c in updated if c.handle_available is True)
        taken_count = sum(1 for c in updated if c.handle_available is False)
        logger.info("Stage 1.5 complete", available=available_count, taken=taken_count)
        return updated

    async def _check_one_handle(
        self, handle: str, http  # httpx.AsyncClient
    ) -> bool | None:
        """Returns True = available, False = taken, None = unknown."""
        h = handle.lstrip("@")
        if not h:
            return None

        if self._yt_api_key:
            return await self._check_via_api(h, http)
        else:
            return await self._check_via_http(h, http)

    async def _check_via_api(self, handle: str, http) -> bool | None:
        """YouTube Data API v3: channels?forHandle=X. Returns True if available."""
        try:
            resp = await http.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"key": self._yt_api_key, "forHandle": handle, "part": "id"},
            )
            if resp.status_code == 200:
                data = resp.json()
                # No items found → handle is available
                return len(data.get("items", [])) == 0
            elif resp.status_code == 403:
                logger.warning("YouTube API quota exceeded, falling back to HTTP check")
                return await self._check_via_http(handle, http)
            return None
        except Exception as exc:
            logger.warning("API handle check failed", handle=handle, error=str(exc))
            return None

    async def _check_via_http(self, handle: str, http) -> bool | None:
        """HTTP GET youtube.com/@Handle. 404 = available, 200 = taken."""
        try:
            resp = await http.get(
                f"https://www.youtube.com/@{handle}",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                },
                follow_redirects=True,
            )
            if resp.status_code == 404:
                return True   # available
            elif resp.status_code == 200:
                return False  # taken
            return None
        except Exception as exc:
            logger.warning("HTTP handle check failed", handle=handle, error=str(exc))
            return None

    # ── Stage 2: Critic (scorer) ──────────────────────────────────────────────

    async def _stage2_score(
        self, niche: dict, candidates: list[NameCandidate]
    ) -> list[NameCandidate]:
        audience = niche.get("audience_description", "general adults")
        pain_summary = ", ".join(niche.get("pain_points", [])[:3])
        names_json = json.dumps(
            [{"name": c.name, "angle": c.angle} for c in candidates], indent=2
        )

        prompt = textwrap.dedent(f"""
            You are a YouTube audience research expert scoring channel name candidates.

            TARGET AUDIENCE: {audience}
            CORE PAIN POINTS: {pain_summary}
            NICHE: {niche.get('niche_name')}

            Score each name candidate on 4 dimensions (0-10 scale) for THIS SPECIFIC audience:

            - audience_trust: Does this name trigger trust from someone with THIS pain profile?
              (e.g. "Advisor" / "Guide" / "Clear" scores high for anxious retirees;
               "Hacks" / "Secrets" scores low for the same audience)
            - memorability: Easy to remember, say aloud, find by search 3 months later?
            - searchability: Contains keywords a person with these pain points would type?
            - differentiation: Clearly distinct from generic/existing channels in this space?

            CANDIDATES:
            {names_json}

            Return JSON array with same order, adding scores:
            [
              {{
                "name": "...",
                "audience_trust": 8.5,
                "memorability": 7.0,
                "searchability": 8.0,
                "differentiation": 7.5
              }},
              ...
            ]
        """).strip()

        try:
            resp = await self._flash.complete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a scoring expert. Respond in valid JSON only.",
                max_tokens=4000,
                temperature=0.2,   # low temp → consistent scores
            )
            content = _strip_json_fences(resp.content)
            raw = json.loads(content)
            
            if isinstance(raw, dict):
                # If wrapped in an object like {"candidates": [...]}, extract it
                for val in raw.values():
                    if isinstance(val, list):
                        raw = val
                        break
            
            if not isinstance(raw, list):
                raise ValueError(f"Expected JSON list from Stage 2, got {type(raw)}")

            scored = []
            for cand, scores in zip(candidates, raw):
                trust = float(scores.get("audience_trust", 6.0))
                # Apply trust penalty for TAKEN handles — taken handle forces ugly
                # suffix (@Name7892) which immediately signals spam/clone to audience
                if cand.handle_available is False:
                    trust = max(0.0, trust - TAKEN_HANDLE_TRUST_PENALTY)
                    logger.info(
                        "Handle penalty applied",
                        name=cand.name,
                        handle=cand.handle,
                        penalty=TAKEN_HANDLE_TRUST_PENALTY,
                    )

                scored.append(NameCandidate(
                    name=cand.name,
                    channel_id=cand.channel_id,
                    angle=cand.angle,
                    rationale=cand.rationale,
                    audience_trust=trust,
                    memorability=float(scores.get("memorability", 6.0)),
                    searchability=float(scores.get("searchability", 6.0)),
                    differentiation=float(scores.get("differentiation", 6.0)),
                    handle_available=cand.handle_available,
                ))
            scored.sort(key=lambda c: c.total_score, reverse=True)
            logger.info("Stage 2 complete", top_score=scored[0].total_score if scored else 0)
            return scored
        except Exception as exc:
            logger.warning("Stage 2 failed", error=str(exc))
            return candidates

    # ── Stage 3: Selector ─────────────────────────────────────────────────────

    async def _stage3_select(
        self, niche: dict, scored: list[NameCandidate]
    ) -> tuple[NameCandidate, NameCandidate | None, str]:
        audience = niche.get("audience_description", "general adults")
        pain_summary = ", ".join(niche.get("pain_points", [])[:3])

        scored_json = json.dumps([
            {
                "name": c.name,
                "handle": c.handle,
                "handle_available": (
                    "AVAILABLE" if c.handle_available is True
                    else "TAKEN" if c.handle_available is False
                    else "UNKNOWN"
                ),
                "angle": c.angle,
                "total_score": c.total_score,
                "audience_trust": c.audience_trust,
                "memorability": c.memorability,
                "searchability": c.searchability,
                "differentiation": c.differentiation,
                "rationale": c.rationale,
            }
            for c in scored
        ], indent=2)

        prompt = textwrap.dedent(f"""
            You are the final judge selecting the best YouTube channel name.

            TARGET AUDIENCE: {audience}
            CORE PAIN POINTS: {pain_summary}
            NICHE: {niche.get('niche_name')}

            Here are the scored candidates (higher total_score = better overall):
            {scored_json}

            CRITICAL RULE: Strongly prefer candidates where handle_available = "AVAILABLE".
            A TAKEN handle forces ugly suffixes like @ChannelName7892 which signals
            spam/clone to the audience and destroys the trust you spent effort building.
            Only pick a TAKEN handle if ALL available alternatives score significantly worse.

            YOUR TASK:
            Select the WINNER — the name that a person experiencing these pain points
            would most likely CLICK on, SUBSCRIBE to, and RETURN to.

            Consider:
            1. Is the handle AVAILABLE? (highest priority)
            2. Does the name match the EXACT language this audience uses for their problem?
            3. Would someone trust a channel with this name during a vulnerable moment?

            Return JSON only:
            {{
              "winner_name": "exact name from candidates",
              "runner_up_name": "second choice or null",
              "reason": "2-3 sentences explaining why winner beats runner-up for this audience"
            }}
        """).strip()

        try:
            resp = await self._chat.complete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a channel selection expert. Respond in valid JSON only.",
                max_tokens=4000,
                temperature=0.3,
            )
            content = _strip_json_fences(resp.content)
            data = json.loads(content)

            winner_name = data.get("winner_name", scored[0].name)
            runner_up_name = data.get("runner_up_name")
            reason = data.get("reason", "Selected by score.")

            winner = next((c for c in scored if c.name == winner_name), scored[0])
            runner_up = next(
                (c for c in scored if c.name == runner_up_name), None
            ) if runner_up_name else (scored[1] if len(scored) > 1 else None)

            logger.info("Stage 3 complete", winner=winner.name,
                        handle=winner.handle, handle_ok=winner.handle_available)
            return winner, runner_up, reason
        except Exception as exc:
            logger.warning("Stage 3 failed", error=str(exc))
            # Prefer first AVAILABLE candidate, fallback to index 0
            available = [c for c in scored if c.handle_available is True]
            best = available[0] if available else scored[0]
            runner_up = next((c for c in scored if c is not best), None)
            return best, runner_up, "Selected by highest score among available handles."


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_json_fences(text: str) -> str:
    # Remove <think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    
    # Strip basic markdown fences
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    
    # Isolate JSON block by finding first [ or { and last ] or }
    text = text.strip()
    start_idx = -1
    for i, c in enumerate(text):
        if c in ("{", "["):
            start_idx = i
            break
            
    if start_idx != -1:
        end_idx = -1
        for i in range(len(text)-1, -1, -1):
            if text[i] in ("}", "]"):
                end_idx = i
                break
        if end_idx != -1 and end_idx >= start_idx:
            return text[start_idx:end_idx+1]
            
    return text


def render_debate_table(result: DebateResult) -> str:
    """Render ASCII table of debate results for CLI display.

    Format:
      #   Name                   Handle               Trust  Memo   SEO  Diff  Total  Handle
      ★1  Retirement Clarity     @RetirementClarity     9.0   8.5   8.0   7.5   8.58  ✅
       2  Senior Money Guide     @SeniorMoneyGuide      8.5   7.5   8.5   6.0   8.00  ❌ TAKEN
    """
    lines = []
    header = (
        f"  {'#':<3} {'Name':<26} {'Handle':<22}"
        f" {'Trust':>5} {'Memo':>5} {'SEO':>5} {'Diff':>5} {'Total':>6}  Handle"
    )
    sep = "  " + "─" * (len(header) - 2)
    lines.append(sep)
    lines.append(header)
    lines.append(sep)

    for i, c in enumerate(result.all_candidates, start=1):
        is_winner = c.name == result.winner.name
        star = "★" if is_winner else " "
        name_trunc = c.name[:25]
        handle_trunc = c.handle[:21]

        if c.handle_available is True:
            avail_str = "✅"
        elif c.handle_available is False:
            avail_str = "❌ TAKEN"
        else:
            avail_str = "?"

        row = (
            f"  {star}{i:<2} {name_trunc:<26} {handle_trunc:<22}"
            f" {c.audience_trust:>5.1f} {c.memorability:>5.1f}"
            f" {c.searchability:>5.1f} {c.differentiation:>5.1f}"
            f" {c.total_score:>6.2f}  {avail_str}"
        )
        lines.append(row)

    lines.append(sep)
    winner_avail = (
        "✅ handle available"
        if result.winner.handle_available is True
        else "❌ handle TAKEN — may need suffix"
        if result.winner.handle_available is False
        else "handle status unknown"
    )
    lines.append(
        f"  Winner: {result.winner.name}  "
        f"({result.winner.handle})  [{winner_avail}]"
    )
    lines.append(f"  Reason: {result.selection_reason}")
    lines.append(sep)
    return "\n".join(lines)
