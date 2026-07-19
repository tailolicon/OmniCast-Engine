"""Channel Builder Agent — auto-generate channel config from a NicheOpportunity.

Flow:
1. Receive NicheOpportunity (from niche_discoverer)
2. LLM generates: channel name, brand voice, hook format, visual style,
   brand color, font vibe, voice persona, subreddits, rss_feeds
3. LLM suggests 6-8 competitor YouTube channels for this niche
4. YouTubeScanner resolves handles → validates they exist (parallel)
5. Reddit API validates subreddits → filters hallucinated subs
6. Returns complete channel config dict → saved as channels/{channel_id}.json

FIELDS SAVED (previously missing/discarded):
  hook_format       — was generated but NOT saved; now persisted
  brand_color_hex   — primary brand color (hex) matched to niche category
  font_vibe         — typography direction ("serif_classic", "sans_modern"…)
  voice_persona     — audience-matched voice descriptor for TTS routing
  subreddits        — LLM-suggested + existence-validated
  rss_feeds         — LLM-suggested real feeds for discovery crawler
  channel_created_at — null at creation, operator fills after YouTube registration
"""

from __future__ import annotations

import asyncio
import json
import re
import httpx
import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient

logger = structlog.get_logger()

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
REDDIT_ABOUT_URL = "https://www.reddit.com/r/{sub}/about.json"
REDDIT_MIN_SUBSCRIBERS = 500   # discard dead/empty subs below this

# Market detection: keywords → market code
_MARKET_KEYWORDS: list[tuple[str, str]] = [
    # Australia
    ("australia", "AU"), ("aussie", "AU"), ("aussies", "AU"),
    ("australian", "AU"), ("aus ", "AU"), ("(au)", "AU"),
    ("superannuation", "AU"), ("centrelink", "AU"), ("mygov", "AU"),
    # United Kingdom
    ("uk", "UK"), ("united kingdom", "UK"), ("british", "UK"), ("britain", "UK"),
    ("england", "UK"), ("scotland", "UK"), ("wales", "UK"),
    ("hmrc", "UK"), ("pension credit", "UK"), ("isa ", "UK"),
    # Canada
    ("canada", "CA"), ("canadian", "CA"), ("cra ", "CA"), ("rrsp", "CA"), ("tfsa", "CA"),
    # Germany
    ("germany", "DE"), ("german", "DE"), ("deutschland", "DE"),
    # France
    ("france", "FR"), ("french", "FR"), ("francais", "FR"),
    # India
    ("india", "IN"), ("indian", "IN"), ("rupee", "IN"), ("nifty", "IN"), ("sensex", "IN"),
    # Philippines
    ("philippines", "PH"), ("filipino", "PH"), ("pilipino", "PH"),
    # Indonesia
    ("indonesia", "ID"), ("indonesian", "ID"),
    # Vietnam
    ("vietnam", "VN"), ("vietnamese", "VN"),
]

# Voice selection lives in omnicast.media.voice_router (spec form
# 'provider:voice_id'). The old map pointed at Kokoro voices that don't exist
# (kokoro_de_v1, kokoro_vi_v1...) — replaced 2026-06-12. New channels rotate
# through the market voice pool so sibling channels don't share one voice.
_DEFAULT_VOICE_PROFILE = "kokoro:af_heart"


def _detect_market(niche: dict, fallback: str = "US") -> str:
    """Infer real market code from niche name + description.

    Overrides the stored market value when the niche clearly targets
    a non-US region. Comparison is case-insensitive.
    """
    haystack = " ".join([
        niche.get("niche_name", ""),
        niche.get("audience_description", ""),
        niche.get("why_opportunity", ""),
        niche.get("niche_id", ""),
    ]).lower()
    for keyword, code in _MARKET_KEYWORDS:
        if keyword in haystack:
            return code
    return fallback


def _voice_for_market(market: str) -> str:
    """Pick a voice spec for a new channel — least-used voice in the market
    pool, so channels in the same market get DIFFERENT voices (reduces the
    mass-produced footprint YouTube flags as inauthentic)."""
    from omnicast.media.voice_router import pick_voice_for_new_channel

    taken: set[str] = set()
    try:
        import json
        from pathlib import Path
        ch_dir = Path(__file__).resolve().parents[4] / "channels"
        for f in ch_dir.glob("*.json"):
            try:
                taken.add(json.loads(f.read_text(encoding="utf-8"))
                          .get("voice_profile", ""))
            except Exception:
                continue
    except Exception:
        pass
    try:
        return pick_voice_for_new_channel(market, taken)
    except Exception:
        return _DEFAULT_VOICE_PROFILE


class ChannelConfig:
    """Generated channel configuration ready to save as JSON."""

    def __init__(
        self,
        channel_id: str,
        name: str,
        niche: str,
        sub_niche: str,
        market: str,
        brand_voice: str,
        tone: str,
        visual_style: str,
        hook_format: str,
        competitor_handles: list[str],
        audience: dict,
        trends_keywords: list[str],
        rpm_floor: float,
        target_duration_min: int,
        voice_profile: str = "kokoro_en_us_v1",
        # NEW fields
        brand_color_hex: str = "#1A1A2E",
        font_vibe: str = "sans_modern",
        voice_persona: str = "neutral_adult",
        subreddits: list[str] | None = None,
        rss_feeds: list[str] | None = None,
    ) -> None:
        self.channel_id = channel_id
        self.name = name
        self.niche = niche
        self.sub_niche = sub_niche
        self.market = market
        self.brand_voice = brand_voice
        self.tone = tone
        self.visual_style = visual_style
        self.hook_format = hook_format
        self.competitor_handles = competitor_handles
        self.audience = audience
        self.trends_keywords = trends_keywords
        self.rpm_floor = rpm_floor
        self.target_duration_min = target_duration_min
        self.voice_profile = voice_profile
        self.brand_color_hex = brand_color_hex
        self.font_vibe = font_vibe
        self.voice_persona = voice_persona
        self.subreddits = subreddits or []
        self.rss_feeds = rss_feeds or []

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "name": self.name,
            "niche": self.niche,
            "sub_niche": self.sub_niche,
            "market": self.market,
            "visual_style": self.visual_style,
            "voice_profile": self.voice_profile,
            "voice_persona": self.voice_persona,          # NEW — TTS routing
            "brand_voice": self.brand_voice,
            "tone": self.tone,
            "hook_format": self.hook_format,              # FIX — was discarded
            "brand_color_hex": self.brand_color_hex,      # NEW — thumbnail/overlay
            "font_vibe": self.font_vibe,                  # NEW — typography
            "competitor_handles": self.competitor_handles,
            "audience": self.audience,
            "trends_keywords": self.trends_keywords,
            "rss_feeds": self.rss_feeds,                  # FIX — was always []
            "subreddits": self.subreddits,                # FIX — was always []
            "rpm_floor": self.rpm_floor,
            "target_duration_min": self.target_duration_min,
            "channel_created_at": None,   # operator fills after YouTube registration
            #                              ChannelGuard uses this for young/mature velocity
        }


class ChannelBuilderAgent(BaseAgent):
    """Generate a complete channel config from a niche description."""

    def __init__(self, llm: LLMClient, youtube_api_key: str = "") -> None:
        super().__init__(llm)
        self._yt_key = youtube_api_key

    @property
    def name(self) -> str:
        return "channel_builder"

    async def execute(self, *args, **kwargs):
        raise NotImplementedError("Use build() instead")

    @property
    def system_prompt(self) -> str:
        return (
            "You are a YouTube channel strategy expert. "
            "You design data-driven channel identities for specific audience niches. "
            "You think in terms of: what specific audience pain drives clicks, "
            "what brand voice earns trust from that audience, "
            "and which competitor channels dominate this niche. "
            "Always respond in valid JSON only."
        )

    async def build(
        self,
        niche: dict,
        market: str = "US",
        approved_name: str | None = None,
        approved_channel_id: str | None = None,
    ) -> ChannelConfig | None:
        """Generate channel config from niche dict.

        Args:
            niche: NicheOpportunity dict from vault/cache
            market: target market code (US, UK, AU…)
            approved_name: pre-selected name from ChannelNameDebateAgent.
                           If None, LLM generates name (legacy/fallback).
            approved_channel_id: pre-selected channel_id matching approved_name.
        """
        # Override stored market with detected market from niche content
        detected_market = _detect_market(niche, fallback=market)
        if detected_market != market:
            logger.info("Market overridden by niche content",
                        stored=market, detected=detected_market,
                        niche=niche.get("niche_name", ""))
        market = detected_market

        if approved_name:
            _cid = approved_channel_id or approved_name.lower().replace(" ", "_")[:25]
            name_fields = (
                f'  "channel_id": "{_cid}",\n'
                f'  "name": "{approved_name}",  // PRE-APPROVED — do not change'
            )
        else:
            name_fields = (
                '  "channel_id": "snake_case_max_25_chars (e.g. retirement_clarity_us)",\n'
                '  "name": "Channel Display Name",'
            )

        prompt = f"""Design a complete YouTube channel for this niche opportunity.

NICHE:
- Name: {niche.get('niche_name')}
- Category: {niche.get('category')}
- Audience: {niche.get('audience_description')}
- Pain points: {', '.join(niche.get('pain_points', [])[:3])}
- Content triggers: {', '.join(niche.get('content_triggers', [])[:3])}
- Estimated RPM: ${niche.get('estimated_rpm', 8)}
- Example channels in this space: {', '.join(niche.get('example_channels', [])[:4])}

TASK: Design a channel that will dominate this niche with a DIFFERENTIATED angle.
Do NOT copy the existing channels — find the gap they miss.

Return JSON only:
{{
{name_fields}
  "sub_niche": "specific sub-topic (max 20 chars)",
  "brand_voice": "one sentence describing the voice and angle (max 80 chars)",
  "tone": "empathetic|authoritative|provocative|educational|conversational",
  "visual_style": "dark_cinematic|clean_educational|documentary|high_energy",
  "hook_format": "one sentence opening for the first 15 seconds (max 90 chars)",
  "brand_color_hex": "#0F172A",
  "font_vibe": "sans_modern",
  "voice_persona": "authoritative_50yo_male",
  "competitor_handles": ["@Handle1", "@Handle2", "@Handle3", "@Handle4", "@Handle5"],
  "audience": {{
    "age_range": "e.g. 45-65",
    "pain_points": ["specific fear 1", "specific fear 2", "specific fear 3"],
    "content_triggers": ["trigger 1", "trigger 2", "trigger 3"],
    "engagement_drivers": ["driver 1", "driver 2"]
  }},
  "trends_keywords": ["keyword1", "keyword2", "keyword3", "keyword4"],
  "subreddits": ["personalfinance", "retirement"],
  "rss_feeds": ["https://feeds.example.com/rss"],
  "rpm_floor": {niche.get('estimated_rpm', 8)},
  "target_duration_min": 10
}}

CRITICAL JSON RULES:
1. brand_color_hex: Pick ONE valid #RRGGBB hex. Finance/trust → dark blues (#0F172A). Health → greens (#10B981). Tech → blues (#0EA5E9).
2. font_vibe: Must be exactly one of: sans_modern | serif_classic | slab_bold | handwritten_warm
3. voice_persona: Describe TTS voice persona in snake_case. Format: [tone]_[age]_[gender] (e.g. calm_female_doctor)
4. subreddits: Only suggest subreddits that DEFINITELY EXIST and are ACTIVE (10k+ members). Do NOT invent names.
5. rss_feeds: Only suggest feeds from major publishers that are known to be publicly accessible. Format must be a real feed URL.

RSS FEEDS RULES: Only suggest feeds from major publishers (Yahoo Finance, Reuters, BBC Health, etc.)
that are known to be publicly accessible. Format must be a real feed URL.
"""

        try:
            response = await self.call_llm(
                [{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0.4,
            )

            content = response.content.strip()
            # Remove <think> blocks
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
            
            # Find the first { and last }
            content = content.strip()
            start_idx = content.find("{")
            end_idx = content.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                content = content[start_idx:end_idx+1]
                
            data = json.loads(content)

            # Validate competitor handles in parallel (if API key available)
            raw_handles = data.get("competitor_handles", [])
            raw_subreddits = data.get("subreddits", [])

            # Run handle validation + subreddit validation in parallel
            async def _pass_handles():
                return raw_handles

            handle_task = (
                self._validate_handles(raw_handles)
                if self._yt_key
                else _pass_handles()   # no API key → skip validation, use as-is
            )
            sub_task = self._validate_subreddits(raw_subreddits)

            valid_handles, valid_subs = await asyncio.gather(
                handle_task, sub_task, return_exceptions=True
            )
            if isinstance(valid_handles, Exception):
                logger.warning("Handle validation failed", error=str(valid_handles))
                valid_handles = raw_handles
            if isinstance(valid_subs, Exception):
                logger.warning("Subreddit validation failed", error=str(valid_subs))
                valid_subs = []

            final_name = approved_name or data.get("name", "New Channel")
            final_channel_id = approved_channel_id or data.get("channel_id", "new_channel_us")

            cfg = ChannelConfig(
                channel_id=final_channel_id,
                name=final_name,
                niche=niche.get("category", "finance"),
                sub_niche=data.get("sub_niche", ""),
                market=market,                                     # FIX: detected market
                brand_voice=data.get("brand_voice", ""),
                tone=data.get("tone", "educational"),
                visual_style=data.get("visual_style", "clean_educational"),
                hook_format=data.get("hook_format", ""),
                competitor_handles=list(valid_handles)[:8],
                audience=data.get("audience", {}),
                trends_keywords=data.get("trends_keywords", []),
                rpm_floor=float(data.get("rpm_floor", niche.get("estimated_rpm", 8))),
                target_duration_min=int(data.get("target_duration_min", 10)),
                brand_color_hex=data.get("brand_color_hex", "#1A1A2E"),
                font_vibe=data.get("font_vibe", "sans_modern"),
                voice_persona=data.get("voice_persona", "neutral_adult"),
                voice_profile=_voice_for_market(market),          # FIX: locale-matched TTS
                subreddits=list(valid_subs),
                rss_feeds=data.get("rss_feeds", []),
            )

            logger.info(
                "Channel config generated",
                channel_id=cfg.channel_id,
                name=cfg.name,
                handles=len(cfg.competitor_handles),
                subreddits=len(cfg.subreddits),
                brand_color=cfg.brand_color_hex,
                voice_persona=cfg.voice_persona,
            )
            return cfg

        except json.JSONDecodeError as exc:
            logger.warning("Channel builder JSON parse failed", error=str(exc))
            return None
        except Exception as exc:
            logger.error("Channel builder failed", error=str(exc))
            return None

    # ── Validators ────────────────────────────────────────────────────────────

    async def _validate_handles(self, handles: list[str]) -> list[str]:
        """Check which @handles exist on YouTube. Runs sequentially (API quota)."""
        valid = []
        async with httpx.AsyncClient(timeout=15) as http:
            for handle in handles:
                h = handle.lstrip("@")
                try:
                    resp = await http.get(
                        f"{YOUTUBE_API_BASE}/channels",
                        params={"key": self._yt_key, "forHandle": h, "part": "id"},
                    )
                    data = resp.json()
                    if data.get("items"):
                        valid.append(handle)
                        logger.info("Handle valid", handle=handle)
                    else:
                        logger.warning("Handle not found", handle=handle)
                except Exception as exc:
                    logger.warning("Handle check failed", handle=handle, error=str(exc))
        return valid

    async def _validate_subreddits(self, subreddits: list[str]) -> list[str]:
        """Filter LLM-suggested subreddits to only existing, active communities.

        Checks reddit.com/r/{sub}/about.json:
          - 404 / redirect to search = hallucinated sub → discard
          - subscribers < REDDIT_MIN_SUBSCRIBERS = dead sub → discard
          - subscribers >= threshold = keep

        Fail-safe: network error → include the sub (don't block on connectivity issues).
        """
        if not subreddits:
            return []

        async with httpx.AsyncClient(
            timeout=8,
            headers={"User-Agent": "OmniCast-ChannelBuilder/1.0"},
        ) as http:
            tasks = [self._check_subreddit(sub, http) for sub in subreddits]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        valid = []
        for sub, result in zip(subreddits, results):
            if isinstance(result, Exception):
                # Network error: fail-safe, include sub
                logger.warning("Subreddit check error (included)", sub=sub, error=str(result))
                valid.append(sub)
            elif result is True:
                valid.append(sub)
                logger.info("Subreddit valid", sub=sub)
            else:
                logger.warning("Subreddit rejected (hallucinated or dead)", sub=sub)

        return valid

    async def _check_subreddit(self, name: str, http) -> bool:
        """Returns True if subreddit exists and has >= REDDIT_MIN_SUBSCRIBERS."""
        # Strip r/ prefix if operator included it
        name = name.strip().lstrip("r/").lstrip("/")
        try:
            resp = await http.get(
                REDDIT_ABOUT_URL.format(sub=name),
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return False  # 404 or redirect to search = doesn't exist
            body = resp.json()
            sub_data = body.get("data", {})
            subscribers = sub_data.get("subscribers", 0)
            sub_type = sub_data.get("subreddit_type", "")
            # Reject private or quarantined subs
            if sub_type in ("private", "restricted", "employees_only"):
                return False
            return subscribers >= REDDIT_MIN_SUBSCRIBERS
        except Exception as exc:
            logger.warning("Subreddit HTTP check failed", sub=name, error=str(exc))
            raise  # re-raise so gather() catches as Exception → fail-safe include
