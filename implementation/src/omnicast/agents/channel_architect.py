"""Channel Architect Agent — analyze YouTube outliers to find best topic opportunities.

Flow:
1. Receive raw outlier videos from YouTubeScanner (title + metrics)
2. LLM clusters them by sub-niche + audience segment
3. Filters for relevance to THIS channel's identity + audience
4. Scores each topic: demand × audience_fit × content_opportunity
5. Returns ranked TopicOpportunity list

This replaces naive "pick top scored outlier" with audience-aware selection.
"""

from __future__ import annotations

import json
import structlog

from omnicast.agents.base import BaseAgent
from omnicast.config.channel import ChannelProfile
from omnicast.config.niches import NicheConfig
from omnicast.discovery.models import TopicRawData
from omnicast.llm.client import LLMClient
from omnicast.models.script import TopicBrief
from omnicast.models.enums import Niche, TopicSource
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class TopicOpportunity:
    """A topic candidate with full audience + opportunity analysis."""

    def __init__(
        self,
        title: str,
        sub_niche: str,
        audience_segment: str,
        pain_point: str,
        content_angle: str,
        demand_score: int,       # 0-40: based on outlier metrics
        audience_fit: int,       # 0-40: how well it matches channel audience
        opportunity: int,        # 0-20: gap / freshness / uniqueness
        total_score: int,
        source_video_url: str = "",
        outlier_ratio: float = 0.0,
        views: int = 0,
    ) -> None:
        self.title = title
        self.sub_niche = sub_niche
        self.audience_segment = audience_segment
        self.pain_point = pain_point
        self.content_angle = content_angle
        self.demand_score = demand_score
        self.audience_fit = audience_fit
        self.opportunity = opportunity
        self.total_score = total_score
        self.source_video_url = source_video_url
        self.outlier_ratio = outlier_ratio
        self.views = views

    def to_brief(self, channel: ChannelProfile) -> TopicBrief:
        return TopicBrief(
            title=self.title,
            niche=channel.niche,
            sub_niche=channel.sub_niche or self.sub_niche,
            market=channel.market,
            source=TopicSource.YOUTUBE_COMPETITOR,
            target_audience=self.audience_segment,
            pain_point=self.pain_point,
            content_angle=self.content_angle,
            source_urls=[self.source_video_url] if self.source_video_url else [],
            competitor_intel_required=bool(
                getattr(channel, "competitor_intel_required", False)),
            # §4.2 scope — without these the writer cannot rebuild the key the
            # learner wrote under, and silently borrows the niche-wide playbook.
            **TopicBrief.scope_fields_from_channel(
                channel, title=self.title, description=self.content_angle or ""),
        )


class ChannelArchitectAgent(BaseAgent):
    """Analyze YouTube outliers → find best topic for a specific channel + audience."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    @property
    def name(self) -> str:
        return "channel_architect"

    async def execute(self, *args, **kwargs):
        """Not used — call analyze() directly."""
        raise NotImplementedError("Use analyze() instead of execute()")

    @property
    def system_prompt(self) -> str:
        return (
            "You are a YouTube channel strategy expert. "
            "You analyze high-performing competitor videos and identify the best content opportunities "
            "for a specific channel and its target audience. "
            "You think in terms of: who is watching, what pain do they have, why did this video win, "
            "and how can we make a better version for our specific audience. "
            "Always respond in valid JSON only."
        )

    async def analyze(
        self,
        outliers: list[TopicRawData],
        channel: ChannelProfile,
        niche_cfg: NicheConfig,
        top_n: int = 5,
    ) -> list[TopicOpportunity]:
        """Analyze outlier videos → return ranked topic opportunities for this channel."""
        if not outliers:
            return []

        # Build compact outlier summary for LLM (avoid token bloat)
        outlier_items = []
        for i, topic in enumerate(outliers[:20]):  # max 20 candidates (token budget)
            m = topic.raw_metrics or {}
            outlier_items.append({
                "id": i,
                "title": topic.title,
                "views": m.get("views", 0),
                "outlier_ratio": round(m.get("outlier_ratio", 0), 1),
                "engagement_rate": m.get("engagement_rate", 0),
                "duration_min": m.get("duration_minutes", 0),
                "title_patterns": m.get("title_patterns", []),
                "audience_signal": m.get("audience_signal", ""),
                "url": topic.source_url or "",
            })

        # Build audience context
        audience = channel.audience or {}
        pain_points = audience.get("pain_points", [])
        triggers = audience.get("content_triggers", [])
        age_range = audience.get("age_range", "unknown")
        engagement_drivers = audience.get("engagement_drivers", [])

        prompt = f"""Analyze these YouTube outlier videos (videos that got 2.5x+ their channel's median views).

CHANNEL: {channel.name}
NICHE: {channel.niche.value}.{channel.sub_niche}
BRAND VOICE: {channel.brand_voice}
INSIDER ANGLE: {niche_cfg.insider_angle}

TARGET AUDIENCE:
- Age: {age_range}
- Pain points: {', '.join(pain_points[:4])}
- Content triggers: {', '.join(triggers[:4])}
- Engagement drivers: {', '.join(engagement_drivers[:3])}

OUTLIER VIDEOS FROM COMPETITORS:
{json.dumps(outlier_items, indent=2)}

TASK:
1. For each video, assess: does this topic serve our target audience's pain points?
2. Filter OUT topics that don't fit our channel identity or audience
3. For the best {top_n} opportunities, provide:
   - Our own fresh title (not a copy — inspired by the topic but our angle)
   - Which audience pain point it addresses
   - Why this will work for our specific audience
   - Content angle (how WE would cover it differently/better)

Respond with JSON only:
{{
  "opportunities": [
    {{
      "title": "our fresh title for this topic",
      "sub_niche": "specific sub-topic area",
      "audience_segment": "specific viewer description (age + situation + pain)",
      "pain_point": "the exact fear or desire this addresses",
      "content_angle": "how our channel covers this differently from competitors",
      "demand_score": 0-40,
      "audience_fit": 0-40,
      "opportunity": 0-20,
      "total_score": 0-100,
      "source_video_url": "url of the inspiring outlier",
      "outlier_ratio": float,
      "views": int
    }}
  ],
  "discarded_reason": "brief note on what you filtered out and why"
}}
"""

        try:
            response = await self.call_llm(
                [{"role": "user", "content": prompt}],
                max_tokens=4500,
                temperature=0.3,
            )

            # Parse JSON response
            import re
            content = response.content.strip()
            # Strip markdown fences if present
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
            content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)

            data = json.loads(content)
            raw_opportunities = data.get("opportunities", [])
            discarded = data.get("discarded_reason", "")

            if discarded:
                logger.info("Channel architect filtered topics", reason=discarded[:100])

            opportunities = []
            for item in raw_opportunities:
                opp = TopicOpportunity(
                    title=item.get("title", ""),
                    sub_niche=item.get("sub_niche", ""),
                    audience_segment=item.get("audience_segment", ""),
                    pain_point=item.get("pain_point", ""),
                    content_angle=item.get("content_angle", ""),
                    demand_score=int(item.get("demand_score", 0)),
                    audience_fit=int(item.get("audience_fit", 0)),
                    opportunity=int(item.get("opportunity", 0)),
                    total_score=min(int(item.get("total_score", 0)), 100),
                    source_video_url=item.get("source_video_url", ""),
                    outlier_ratio=float(item.get("outlier_ratio", 0)),
                    views=int(item.get("views", 0)),
                )
                if opp.title:
                    opportunities.append(opp)

            # Sort by total_score desc
            opportunities.sort(key=lambda o: o.total_score, reverse=True)

            logger.info(
                "Channel architect completed",
                channel=channel.channel_id,
                candidates_in=len(outliers),
                opportunities_out=len(opportunities),
                top_topic=opportunities[0].title if opportunities else "none",
            )

            return opportunities

        except json.JSONDecodeError as exc:
            logger.warning("Channel architect JSON parse failed", error=str(exc))
            return []
        except Exception as exc:
            raise AgentError(f"Channel architect failed: {exc}") from exc
