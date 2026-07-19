"""Niche Discoverer Agent — find underserved niches from YouTube channel data.

Hallucination fix (per Gemini):
- Assign C{i}_V{j} IDs to all videos before sending to LLM
- LLM returns only evidence_ids (list of C{i}_V{j})
- Python maps IDs back to real channel names + real titles
- LLM cannot invent titles it never saw
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.agents.rpm_estimator import RpmEstimatorAgent
from omnicast.discovery.niche_scanner import NicheChannelData
from omnicast.llm.client import LLMClient

logger = structlog.get_logger()

# ── Unicorn thresholds ──────────────────────────────────────────────────────
# A channel qualifies as "unicorn" if it has a massive viral breakout with no
# peer channel. LLM grouping logic would drop it — Python must protect it.
#
# Three qualifying rules (ANY one is sufficient):
#   Rule 1: outlier >= 50x alone          → extreme viral proof
#   Rule 2: outlier >= 20x AND vpd >= 5k  → strong viral + still active
#   Rule 3: vpd >= 30k AND outlier >= 10x → velocity anomaly (e.g. geo-specific finance)
UNICORN_OUTLIER_HIGH = 50.0   # Rule 1 standalone threshold
UNICORN_OUTLIER_MIN  = 20.0   # Rule 2 outlier floor
UNICORN_VPD_MIN      = 5_000  # Rule 2 vpd floor
UNICORN_VPD_HIGH     = 30_000 # Rule 3 velocity anomaly threshold
UNICORN_OUTLIER_VPD  = 10.0   # Rule 3 outlier floor (paired with high vpd)

# Keep backward compat name for prompt string
_UNICORN_PROMPT_THRESHOLD = f"outlier_x >= {UNICORN_OUTLIER_HIGH} OR " \
                            f"(outlier_x >= {UNICORN_OUTLIER_MIN} AND vpd >= {UNICORN_VPD_MIN}) OR " \
                            f"(vpd >= {UNICORN_VPD_HIGH} AND outlier_x >= {UNICORN_OUTLIER_VPD})"

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "finance": ["finance", "money", "invest", "stock", "dividend", "wealth",
                "retirement", "tax", "debt", "crypto", "budget", "smsf", "isa"],
    "health":  ["health", "fitness", "weight", "diet", "nutrition", "muscle",
                "sleep", "hormone", "gut", "autoimmune", "carnivore", "longevity"],
    "psychology": ["psychology", "narcissist", "adhd", "trauma", "anxiety",
                   "stoic", "behavior", "emotional", "brain", "intelligence", "iq"],
    "history": ["history", "ancient", "war", "civilization", "roman", "medieval",
                "cold war", "general", "warrior", "untold", "dark history"],
    "tech":    ["ai", "tech", "quantum", "nuclear", "study", "learn", "dopamine",
                "calculus", "math", "science", "focus", "productivity"],
    "lifestyle": ["homestead", "van life", "expat", "minimalism", "prepper",
                  "parenting", "child", "baby", "marriage"],
}
_RPM_SCORE: dict[str, int]   = {"finance": 19, "health": 13, "psychology": 11,
                                  "history": 7,  "tech": 11,  "lifestyle": 6}
_RPM_VALUE: dict[str, float] = {"finance": 19.0, "health": 13.0, "psychology": 11.0,
                                  "history": 7.0,  "tech": 11.0,  "lifestyle": 6.0}

# Common Spanish stop-words — if titles are dense with these, channel is Spanish-language.
# Latin script passes _is_english_content() so we need a separate check here.
_SPANISH_STOP_WORDS = frozenset({
    "eres", "del", "que", "una", "este", "para", "con", "pero", "como",
    "los", "las", "sus", "por", "más", "sin", "ser", "fue", "hay",
    "todo", "esta", "cuando", "después", "también", "desde", "sobre",
    "entre", "cada", "otro", "durante", "aunque", "siempre", "nunca",
    "pov", "cómo", "qué", "así",
})
_SPANISH_THRESHOLD = 0.25  # >25% of words are Spanish stop-words → Spanish channel


def _is_spanish_channel(titles: list[str]) -> bool:
    """Heuristic: return True if video titles are predominantly Spanish."""
    if not titles:
        return False
    words: list[str] = []
    for t in titles:
        words.extend(w.strip(".,!?;:\"'()[]").lower() for w in t.split())
    if not words:
        return False
    spanish_count = sum(1 for w in words if w in _SPANISH_STOP_WORDS)
    return spanish_count / len(words) > _SPANISH_THRESHOLD


def _infer_category(seed_query: str) -> str:
    q = seed_query.lower()
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if any(kw in q for kw in kws):
            return cat
    return "lifestyle"


class NicheOpportunity:
    def __init__(
        self,
        niche_id: str,
        niche_name: str,
        category: str,
        audience_description: str,
        pain_points: list[str],
        content_triggers: list[str],
        demand_score: int,
        gap_score: int,
        rpm_score: int,
        specificity_score: int,
        total_score: int,
        estimated_rpm: float,
        example_channels: list[str],
        breakout_titles: list[str],
        why_opportunity: str,
        evidence: list[dict] | None = None,
    ) -> None:
        self.niche_id = niche_id
        self.niche_name = niche_name
        self.category = category
        self.audience_description = audience_description
        self.pain_points = pain_points
        self.content_triggers = content_triggers
        self.demand_score = demand_score
        self.gap_score = gap_score
        self.rpm_score = rpm_score
        self.specificity_score = specificity_score
        self.total_score = total_score
        self.estimated_rpm = estimated_rpm
        self.example_channels = example_channels
        self.breakout_titles = breakout_titles
        self.why_opportunity = why_opportunity
        self.evidence = evidence or []

    def display(self, rank: int) -> str:
        lines = [
            f"  #{rank} [{self.total_score}/100] {self.niche_name}",
            f"       Category   : {self.category}",
            f"       Audience   : {self.audience_description}",
            f"       Pain points: {' | '.join(self.pain_points[:2])}",
            f"       Est. RPM   : ${self.estimated_rpm:.0f}",
            f"       Gap signal : {self.why_opportunity[:90]}",
            f"       Score      : demand={self.demand_score} gap={self.gap_score} rpm={self.rpm_score} spec={self.specificity_score}",
        ]
        if self.evidence:
            lines.append("       Evidence (verified from API data):")
            for ev in self.evidence[:3]:
                ch = ev.get("channel", "")
                title = ev.get("title", "")[:65]
                views = ev.get("views", 0)
                vpd = ev.get("views_per_day", 0)
                ox = ev.get("outlier_x", 0)
                lines.append(f"         [{ch}] {title}")
                lines.append(f"           {views:,} views | {vpd:,.0f}/day | {ox}x median")
        if self.breakout_titles:
            lines.append("       Breakout titles (verified):")
            for t in self.breakout_titles[:2]:
                lines.append(f"         * {t[:80]}")
        return "\n".join(lines)

    def to_channel_seed(self) -> dict:
        return {
            "niche_id": self.niche_id,
            "niche_name": self.niche_name,
            "category": self.category,
            "audience_description": self.audience_description,
            "pain_points": self.pain_points,
            "content_triggers": self.content_triggers,
            "estimated_rpm": self.estimated_rpm,
            "example_channels": self.example_channels,
            "evidence": self.evidence,
        }


class NicheDiscovererAgent(BaseAgent):
    def __init__(self, llm: LLMClient, flash_llm: LLMClient | None = None) -> None:
        super().__init__(llm)
        # flash_llm used for cheap batch RPM estimation (optional)
        # If not provided, falls back to category table
        self._flash_llm = flash_llm

    @property
    def name(self) -> str:
        return "niche_discoverer"

    async def execute(self, *args, **kwargs):
        raise NotImplementedError("Use discover()")

    @property
    def system_prompt(self) -> str:
        return (
            "You are a YouTube niche analyst finding UNDERSERVED opportunities. "
            "You use only the data provided. You never invent channel names or video titles. "
            "You reference videos by their assigned ID only (C0_V0, C1_V2, etc). "
            "Always respond in valid JSON only. No markdown."
        )

    def _build_unicorn_niche(
        self,
        ch: NicheChannelData,
        ch_idx: int,
        video_lookup: dict,
    ) -> NicheOpportunity:
        """Python-only fallback for unicorn channels LLM might drop.

        Called when: outlier_x >= UNICORN_OUTLIER_MIN AND best vpd >= UNICORN_VPD_MIN
        but LLM failed to include the channel in any returned niche.
        """
        best_video = max(ch.top_videos, key=lambda v: v["views"]) if ch.top_videos else {}
        best_vpd   = best_video.get("views_per_day", 0)
        best_title = best_video.get("title", "")

        cat       = _infer_category(ch.seed_query)
        rpm_score = _RPM_SCORE.get(cat, 6)
        est_rpm   = _RPM_VALUE.get(cat, 6.0)

        demand_score     = 40 if best_vpd > 20_000 else 38
        gap_score        = 28   # no comparable channel = maximum gap
        specificity_score = 8
        total = min(100, demand_score + gap_score + rpm_score + specificity_score)

        ch_id = f"C{ch_idx}"
        evidence = [
            video_lookup[vk]
            for j in range(min(3, len(ch.top_videos)))
            if (vk := f"{ch_id}_V{j}") in video_lookup
        ]
        breakout_titles = [evidence[0]["title"]] if evidence else (
            [best_title] if best_title else []
        )

        niche_slug = re.sub(r"[^a-z0-9]+", "_", ch.channel_name.lower()).strip("_")

        return NicheOpportunity(
            niche_id=f"unicorn_{niche_slug}",
            niche_name=f"[Unicorn] {ch.channel_name}",
            category=cat,
            audience_description=f"Standalone viral niche — via seed: {ch.seed_query[:60]}",
            pain_points=["No comparable channel exists", "Unique format/angle untapped"],
            content_triggers=[best_title[:40] if best_title else "Standalone viral format"],
            demand_score=demand_score,
            gap_score=gap_score,
            rpm_score=rpm_score,
            specificity_score=specificity_score,
            total_score=total,
            estimated_rpm=est_rpm,
            example_channels=[f"{ch.channel_name} ({ch.top_outlier_ratio}x)"],
            breakout_titles=breakout_titles,
            why_opportunity=(
                f"UNICORN: {ch.top_outlier_ratio}x outlier, {best_vpd:,.0f} vpd. "
                f"No peer channel = max gap. LLM cannot group → Python rescued."
            ),
            evidence=evidence,
        )

    @staticmethod
    def _enforce_category_diversity(
        opportunities: list[NicheOpportunity],
        max_per_category: int = 2,
        total_cap: int = 15,
    ) -> list[NicheOpportunity]:
        """Post-processing: cap niches per category, keep top by score.

        Prevents 5× health niches from dominating the list.
        Niches are already sorted by total_score descending before this call.
        """
        seen: dict[str, int] = {}
        kept: list[NicheOpportunity] = []
        for opp in opportunities:
            cat = opp.category
            count = seen.get(cat, 0)
            if count < max_per_category:
                kept.append(opp)
                seen[cat] = count + 1
            if len(kept) >= total_cap:
                break
        return kept

    async def discover(
        self,
        channels: list[NicheChannelData],
        top_n: int = 15,
        progress_cb: Callable[[dict], None] | None = None,
    ) -> list[NicheOpportunity]:
        def _p(event: dict) -> None:
            if progress_cb:
                try:
                    progress_cb(event)
                except Exception:
                    pass

        if not channels:
            return []

        t0 = time.monotonic()

        # Sort: supernova first, then viral, then by outlier
        sorted_channels = sorted(
            channels,
            key=lambda c: (c.is_supernova, c.has_viral_proof, c.top_outlier_ratio),
            reverse=True,
        )[:60]
        _p({"type": "niche_cluster", "agent": "scorer",
            "channels": len(sorted_channels),
            "elapsed_s": round(time.monotonic() - t0, 1)})

        # ── Build video_lookup for ALL sorted channels (hallucination fix) ──
        # Assign C{i}_V{j} to every video. LLM returns IDs, Python maps back.
        video_lookup: dict[str, dict] = {}
        all_channel_items: list[dict[str, Any]] = []

        for i, ch in enumerate(sorted_channels):
            ch_id = f"C{i}"
            videos_for_prompt: list[dict] = []

            for j, v in enumerate(ch.top_videos[:3]):
                vid_id = f"{ch_id}_V{j}"
                _vid = v.get("video_id", "")
                video_lookup[vid_id] = {
                    "channel": ch.channel_name,
                    # Source-channel identity so the operator can study the
                    # micro-channel that triggered this niche (e.g. 1K subs, 1M views).
                    "channel_id": ch.channel_id,
                    "channel_url": (f"https://www.youtube.com/channel/{ch.channel_id}"
                                    if ch.channel_id else ""),
                    "subs_k": round(ch.subscribers / 1000, 1),
                    "channel_outlier_x": ch.top_outlier_ratio,
                    "median_views": int(ch.median_views),
                    "title": v["title"],
                    "views": v["views"],
                    "views_per_day": v.get("views_per_day", 0),
                    "outlier_x": v["outlier_x"],
                    "video_id": _vid,
                    "video_url": f"https://www.youtube.com/watch?v={_vid}" if _vid else "",
                }
                videos_for_prompt.append({
                    "vid_id": vid_id,
                    "title": v["title"],
                    "views": v["views"],
                    "vpd": v.get("views_per_day", 0),
                    "outlier_x": v["outlier_x"],
                })

            all_channel_items.append({
                "ch_id": ch_id,
                "name": ch.channel_name,
                "subs_k": round(ch.subscribers / 1000, 1),
                "med_views": int(ch.median_views),
                "outlier_x": ch.top_outlier_ratio,
                "comment_rate": round(ch.comment_view_ratio, 4),
                "emerging": ch.is_emerging,
                "supernova": ch.is_supernova,
                "breakout_tier": getattr(ch, "breakout_tier", 0),  # 1/2/3 tiered signal
                "viral": ch.has_viral_proof,
                "query": ch.seed_query[:50],
                "videos": videos_for_prompt,
            })

        # ── Detect unicorns ──────────────────────────────────────────────────
        unicorn_ch_indices: set[int] = set()
        for i, ch in enumerate(sorted_channels):
            outlier = ch.top_outlier_ratio
            best_vpd = max(
                (v.get("views_per_day", 0) for v in ch.top_videos),
                default=0,
            )
            rule1 = outlier >= UNICORN_OUTLIER_HIGH
            rule2 = outlier >= UNICORN_OUTLIER_MIN and best_vpd >= UNICORN_VPD_MIN
            rule3 = best_vpd >= UNICORN_VPD_HIGH and outlier >= UNICORN_OUTLIER_VPD
            rule4 = getattr(ch, "is_breakout", False) and getattr(ch, "breakout_tier", 0) >= 2
            if not (rule1 or rule2 or rule3 or rule4):
                continue

            # Quality filter: skip non-English unicorns that passed scanner
            # (scanner catches non-Latin scripts & country codes, but misses
            # Spanish (Latin script) and Indian-rupee channels without country set)
            titles = [v.get("title", "") for v in ch.top_videos]
            if _is_spanish_channel(titles):
                logger.debug(
                    "Skipping Spanish unicorn", channel=ch.channel_name, outlier=outlier
                )
                continue

            unicorn_ch_indices.add(i)

        # ── Split: non-unicorn channels → LLM call 1 (grouping) ─────────────
        grouped_items = [
            item for item in all_channel_items
            if int(item["ch_id"][1:]) not in unicorn_ch_indices
        ]
        unicorn_pairs = [
            (i, sorted_channels[i]) for i in sorted(unicorn_ch_indices)
        ]

        supernova_count = sum(1 for c in sorted_channels if c.is_supernova)
        viral_count = sum(1 for c in sorted_channels if c.has_viral_proof)

        grouped_prompt = f"""Analyze {len(grouped_items)} YouTube channels. Find UNDERSERVED niches by grouping channels with shared topic.

DATA DEFINITIONS:
- outlier_x: best_video_views / channel_median_views
- vpd: views per day (velocity — most important signal)
- supernova: subs < 10k, outlier > 10x → untapped niche
- emerging: subs < 300k → no dominant channel yet
- comment_rate: high = audience has real pain

SCORING RULES:
demand_score (0-40): supernova=+35 | viral+emerging=+25 | viral=+15 | vpd>10k=+5
gap_score (0-30): all_subs<300k=25-30 | mix=15-20 | any>1M_dominant=max10
rpm_score (0-20): finance/retirement=18-20 | health=12-15 | psychology=10-12 | history=6-8 | tech=10-12 | lifestyle=5-7
specificity (0-10): "55-65yo outliving savings"=9-10 | "personal finance"=1-2

MERGE RULE (CRITICAL — apply before scoring):
If 2+ topics share the SAME TARGET AUDIENCE and could coexist on ONE YouTube channel without audience confusion, you MUST MERGE them into one broader niche.
Examples:
  - "Dog health warning signs" + "Dog psychology/behavior" → MERGE → "Dog Care, Health & Behavior"
  - "Visceral fat foods" + "Seated belly exercises" + "Fat loss form" + "Japanese fat loss habits" → MERGE → "Belly Fat Loss for Middle-Aged Adults (50+)"
  - "Maladaptive daydreaming psychology" + "Hyperawareness psychology" → MERGE → "Deep Psychology: Unusual Mental States"
RULE: Same viewer would watch ALL merged videos on the same channel → it is ONE niche.

CATEGORY CAP: Return at most 2 niches per category. If health has 5 candidates, score them and keep top 2.

EVIDENCE RULE: reference videos by vid_id only (e.g. "C3_V0"). Python maps IDs to titles.

STATS: supernova={supernova_count} | viral={viral_count} | total_for_grouping={len(grouped_items)}

DATA:
{json.dumps(grouped_items, indent=1)}

Return top {min(top_n, 15)} grouped niches (score >= 50), max 2 per category. JSON only:
{{
  "niches": [
    {{
      "niche_id": "snake_case_slug",
      "niche_name": "Specific Descriptive Name",
      "category": "finance|health|psychology|history|tech|lifestyle",
      "audience": "specific age + situation (max 70 chars)",
      "pain_points": ["max 45 chars", "max 45 chars"],
      "content_triggers": ["max 40 chars", "max 40 chars"],
      "supporting_ch_ids": ["C3", "C7"],
      "evidence_ids": ["C3_V0", "C7_V1"],
      "breakout_vid_ids": ["C3_V0"],
      "demand": 0-40, "gap": 0-30, "rpm": 0-20, "specificity": 0-10,
      "total": 0-100, "est_rpm": 15.0,
      "opportunity": "data-driven reason (max 100 chars)"
    }}
  ]
}}"""

        content = ""
        try:
            # ── LLM Call 1: Group regular channels into niches ───────────────
            resp = await self.call_llm(
                [{"role": "user", "content": grouped_prompt}],
                max_tokens=8192,
                temperature=0.2,
            )
            content = resp.content.strip()
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
            content = re.sub(r"\s*```\s*$", "", content, flags=re.MULTILINE)
            data = json.loads(content)
            raw_niches = data.get("niches", [])

            opportunities: list[NicheOpportunity] = []
            for item in raw_niches:
                if not item.get("niche_name"):
                    continue
                total = min(int(item.get("total", 0)), 100)
                if total < 50:
                    continue

                # Hard RPM filter: drop pure entertainment/lifestyle niches (est RPM < $7)
                # Threshold = 8 (not 10): allows history (rpm 7-8) through.
                # Lifestyle/gaming = 5-6 → drop. Health/psych/tech/finance = 11-20 → pass.
                rpm_score_val = int(item.get("rpm", 0))
                if rpm_score_val < 7:
                    logger.debug(
                        "Dropped low-RPM niche",
                        niche=item.get("niche_name", "?"),
                        rpm_score=rpm_score_val,
                    )
                    continue

                evidence_ids = item.get("evidence_ids", [])
                evidence = [video_lookup[eid] for eid in evidence_ids if eid in video_lookup]

                breakout_ids = item.get("breakout_vid_ids", [])
                breakout_titles = [
                    video_lookup[bid]["title"] for bid in breakout_ids if bid in video_lookup
                ]

                supporting_ch_ids = item.get("supporting_ch_ids", [])
                example_channels = []
                for ch_id_str in supporting_ch_ids:
                    try:
                        idx = int(ch_id_str.lstrip("C"))
                        if 0 <= idx < len(sorted_channels):
                            ch = sorted_channels[idx]
                            example_channels.append(f"{ch.channel_name} ({ch.top_outlier_ratio}x)")
                    except ValueError:
                        pass

                opportunities.append(NicheOpportunity(
                    niche_id=item.get("niche_id", "unknown"),
                    niche_name=item.get("niche_name", ""),
                    category=item.get("category", ""),
                    audience_description=item.get("audience", ""),
                    pain_points=item.get("pain_points", []),
                    content_triggers=item.get("content_triggers", []),
                    demand_score=int(item.get("demand", 0)),
                    gap_score=int(item.get("gap", 0)),
                    rpm_score=int(item.get("rpm", 0)),
                    specificity_score=int(item.get("specificity", 0)),
                    total_score=total,
                    estimated_rpm=float(item.get("est_rpm", 5.0)),
                    example_channels=example_channels,
                    breakout_titles=breakout_titles,
                    why_opportunity=item.get("opportunity", ""),
                    evidence=evidence,
                ))
                _p({"type": "niche_scored", "agent": "scorer",
                    "name": item.get("niche_name", ""),
                    "category": item.get("category", ""),
                    "demand": int(item.get("demand", 0)),
                    "gap": int(item.get("gap", 0)),
                    "rpm": int(item.get("rpm", 0)),
                    "est_rpm": float(item.get("est_rpm", 5.0)),
                    "total": total, "n": len(opportunities),
                    "elapsed_s": round(time.monotonic() - t0, 1)})

            # ── LLM Call 2: Name unicorn channels (dedicated prompt) ─────────
            unicorn_niches = await self._name_unicorn_channels(unicorn_pairs, video_lookup)
            opportunities.extend(unicorn_niches)

            # ── LLM Call 3: RPM estimation (Flash, batch, cheap) ────────────
            if self._flash_llm and opportunities:
                try:
                    rpm_agent = RpmEstimatorAgent(self._flash_llm)
                    niche_dicts = [
                        {
                            "niche_id":            o.niche_id,
                            "niche_name":          o.niche_name,
                            "category":            o.category,
                            "audience_description": o.audience_description,
                            "pain_points":         o.pain_points,
                            "market":              "US",  # default; market detector in builder overrides later
                        }
                        for o in opportunities
                    ]
                    rpm_map = await rpm_agent.estimate_batch(niche_dicts)
                    for opp in opportunities:
                        est = rpm_map.get(opp.niche_id)
                        if est:
                            opp.estimated_rpm = est.final_rpm
                            logger.debug(
                                "RPM updated",
                                niche=opp.niche_id,
                                rpm=est.final_rpm,
                                confidence=est.confidence,
                                reason=est.reasoning[:60],
                            )
                except Exception as exc:
                    logger.warning("RPM estimation skipped", error=str(exc))

            opportunities.sort(key=lambda o: o.total_score, reverse=True)
            # Python-enforced diversity: max 2 per category regardless of LLM output
            opportunities = self._enforce_category_diversity(
                opportunities, max_per_category=2, total_cap=top_n
            )

            logger.info(
                "Niche discovery complete",
                channels_in=len(channels),
                supernova=supernova_count,
                unicorns_detected=len(unicorn_ch_indices),
                grouped_niches=len(raw_niches),
                unicorn_niches=len(unicorn_niches),
                niches_out=len(opportunities),
                top=opportunities[0].niche_name if opportunities else "none",
                top_score=opportunities[0].total_score if opportunities else 0,
            )
            return opportunities

        except json.JSONDecodeError as exc:
            logger.warning("JSON parse failed", error=str(exc), tail=content[-400:] if content else "")
            return []
        except Exception as exc:
            from omnicast.shared.errors import AgentError
            raise AgentError(f"Niche discoverer failed: {exc}") from exc

    async def _name_unicorn_channels(
        self,
        unicorn_pairs: list[tuple[int, NicheChannelData]],
        video_lookup: dict,
    ) -> list[NicheOpportunity]:
        """LLM Call 2: Dedicated prompt to name and categorize unicorn channels.

        Each unicorn gets a proper topic-based niche name derived from its
        top video titles — not the channel name.
        """
        if not unicorn_pairs:
            return []

        unicorn_items = []
        for orig_idx, ch in unicorn_pairs:
            ch_id = f"C{orig_idx}"
            best_video = max(ch.top_videos, key=lambda v: v["views"]) if ch.top_videos else {}
            unicorn_items.append({
                "ch_id": ch_id,
                "channel_name": ch.channel_name,
                "subs_k": round(ch.subscribers / 1000, 1),
                "outlier_x": ch.top_outlier_ratio,
                "best_vpd": best_video.get("views_per_day", 0),
                "seed_query": ch.seed_query[:50],
                "top_titles": [v["title"] for v in ch.top_videos[:3]],
            })

        unicorn_prompt = f"""You have {len(unicorn_items)} YouTube channels. Each had ONE viral breakout video.
Identify the CONTENT NICHE each channel represents — name the TOPIC, not the channel.

CRITICAL: Look at top_titles to understand what content exploded. Name the niche based on the TOPIC ANGLE.
BAD niche_name: "[Unicorn] Alex Carter" or "Alex Carter Finance"
GOOD niche_name: "AI-Powered Personal Finance Automation" or "Geo-Specific Dividend Investing (Australia)"

Categories: finance|health|psychology|history|tech|lifestyle
RPM: finance=18-20 | health=12-15 | psychology=10-12 | history=6-8 | tech=10-12 | lifestyle=5-7
NOTE: est_rpm must be a NUMBER like 18.5 — NOT a string like "$18.5"

DATA:
{json.dumps(unicorn_items, indent=1)}

Return one entry per channel. JSON only:
{{
  "unicorns": [
    {{
      "ch_id": "C3",
      "niche_id": "snake_case_topic_not_channel_name",
      "niche_name": "Descriptive Topic Name (not channel name, max 60 chars)",
      "category": "finance|health|psychology|history|tech|lifestyle",
      "audience": "specific demographic + pain (max 70 chars)",
      "pain_points": ["pain 1 (max 45 chars)", "pain 2 (max 45 chars)"],
      "content_triggers": ["trigger 1 (max 40 chars)", "trigger 2"],
      "demand": 35-40,
      "gap": 25-30,
      "rpm": based_on_category,
      "specificity": 7-9,
      "total": sum_of_above,
      "est_rpm": dollar_amount,
      "opportunity": "why this content angle is underserved (max 100 chars)"
    }}
  ]
}}"""

        ch_id_map = {f"C{orig_idx}": (orig_idx, ch) for orig_idx, ch in unicorn_pairs}
        covered: set[str] = set()
        results: list[NicheOpportunity] = []

        # Chunk unicorns — 5 per LLM call (DeepSeek Flash uses reasoning tokens
        # which eat into max_tokens; 5 × ~200 output tokens = ~1000 tokens safe margin)
        CHUNK_SIZE = 5
        for chunk_start in range(0, len(unicorn_items), CHUNK_SIZE):
            chunk = unicorn_items[chunk_start:chunk_start + CHUNK_SIZE]
            chunk_prompt = unicorn_prompt.replace(
                f"You have {len(unicorn_items)} YouTube channels",
                f"You have {len(chunk)} YouTube channels",
            ).replace(
                json.dumps(unicorn_items, indent=1),
                json.dumps(chunk, indent=1),
            )

            content = ""
            try:
                resp = await self.call_llm(
                    [{"role": "user", "content": chunk_prompt}],
                    max_tokens=4096,
                    temperature=0.2,
                )
                content = resp.content.strip()
                content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
                content = re.sub(r"\s*```\s*$", "", content, flags=re.MULTILINE)
                data = json.loads(content)

                for item in data.get("unicorns", []):
                    ch_id = item.get("ch_id", "")
                    if ch_id not in ch_id_map or ch_id in covered:
                        continue
                    orig_idx, ch = ch_id_map[ch_id]
                    covered.add(ch_id)

                    evidence = [
                        video_lookup[vk]
                        for j in range(min(3, len(ch.top_videos)))
                        if (vk := f"{ch_id}_V{j}") in video_lookup
                    ]
                    breakout_titles = [evidence[0]["title"]] if evidence else []

                    total = min(100, int(item.get("total", 0)))
                    if total < 50:
                        total = min(100,
                            int(item.get("demand", 38)) + int(item.get("gap", 28)) +
                            int(item.get("rpm", 10)) + int(item.get("specificity", 8))
                        )

                    # Defensive est_rpm parse — LLM sometimes returns "$11.00"
                    est_rpm_raw = item.get("est_rpm", 10.0)
                    try:
                        est_rpm_val = float(
                            str(est_rpm_raw).replace("$", "").replace(",", "").strip()
                        )
                    except (ValueError, TypeError):
                        est_rpm_val = _RPM_VALUE.get(item.get("category", "lifestyle"), 6.0)

                    results.append(NicheOpportunity(
                        niche_id=item.get("niche_id", f"unicorn_c{orig_idx}"),
                        niche_name=item.get("niche_name", f"[Unicorn] {ch.channel_name}"),
                        category=item.get("category", "lifestyle"),
                        audience_description=item.get("audience", ""),
                        pain_points=item.get("pain_points", []),
                        content_triggers=item.get("content_triggers", []),
                        demand_score=int(item.get("demand", 38)),
                        gap_score=int(item.get("gap", 28)),
                        rpm_score=int(item.get("rpm", 10)),
                        specificity_score=int(item.get("specificity", 8)),
                        total_score=total,
                        estimated_rpm=est_rpm_val,
                        example_channels=[f"{ch.channel_name} ({ch.top_outlier_ratio}x)"],
                        breakout_titles=breakout_titles,
                        why_opportunity=item.get("opportunity", ""),
                        evidence=evidence,
                    ))

            except (json.JSONDecodeError, Exception) as exc:
                logger.warning(
                    "Unicorn naming chunk failed — Python fallback for this chunk",
                    chunk_start=chunk_start,
                    chunk_size=len(chunk),
                    error=str(exc)[:80],
                )
                # Fallback only for this chunk's channels
                for u_item in chunk:
                    ch_id = u_item["ch_id"]
                    if ch_id in ch_id_map and ch_id not in covered:
                        orig_idx, ch = ch_id_map[ch_id]
                        results.append(self._build_unicorn_niche(ch, orig_idx, video_lookup))
                        covered.add(ch_id)

        # Final safety fallback — any unicorn still uncovered
        for ch_id, (orig_idx, ch) in ch_id_map.items():
            if ch_id not in covered:
                results.append(self._build_unicorn_niche(ch, orig_idx, video_lookup))
                logger.warning("Unicorn naming missed", channel=ch.channel_name)

        logger.info(
            "Unicorn naming complete",
            unicorns_in=len(unicorn_pairs),
            named=len(covered),
            llm_chunks=max(1, (len(unicorn_pairs) + CHUNK_SIZE - 1) // CHUNK_SIZE),
        )
        return results
