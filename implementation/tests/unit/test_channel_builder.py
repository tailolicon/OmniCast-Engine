"""Tests for ChannelBuilderAgent — config generation, subreddit validation, new fields."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from omnicast.agents.channel_builder import (
    ChannelBuilderAgent,
    ChannelConfig,
    REDDIT_MIN_SUBSCRIBERS,
)
from omnicast.llm.client import LLMClient, LLMResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="deepseek-chat",
        input_tokens=500,
        output_tokens=300,
        cost_usd=0.001,
        stop_reason="end_turn",
    )


def _niche(
    name="Retirement Clarity",
    category="finance",
    audience="adults 55-70 anxious about retirement",
    pain_points=None,
    estimated_rpm=15,
) -> dict:
    return {
        "niche_name": name,
        "category": category,
        "audience_description": audience,
        "pain_points": pain_points or ["running out of money", "SS confusion", "inflation"],
        "content_triggers": ["401k loss", "retirement date", "SS benefits"],
        "example_channels": ["@RetirementTalk", "@SeniorFinance"],
        "estimated_rpm": estimated_rpm,
    }


def _full_llm_response(
    channel_id="retirement_clarity",
    name="Retirement Clarity",
    hook_format="You're losing $400/month in hidden 401k fees — here's how to stop it",
    brand_color="#0F172A",
    font_vibe="serif_classic",
    voice_persona="authoritative_50yo_male",
    subreddits=None,
    rss_feeds=None,
) -> str:
    return json.dumps({
        "channel_id": channel_id,
        "name": name,
        "sub_niche": "retirement",
        "brand_voice": "Authoritative but empathetic guide for anxious pre-retirees",
        "tone": "empathetic",
        "visual_style": "clean_educational",
        "hook_format": hook_format,
        "brand_color_hex": brand_color,
        "font_vibe": font_vibe,
        "voice_persona": voice_persona,
        "competitor_handles": ["@MoneyGuyShow", "@ErinTalksMoney"],
        "audience": {
            "age_range": "55-70",
            "pain_points": ["outliving savings", "SS confusion"],
            "content_triggers": ["401k loss", "retirement date"],
            "engagement_drivers": ["fear", "hope"],
        },
        "trends_keywords": ["retirement", "401k", "social security"],
        "subreddits": subreddits or ["personalfinance", "retirement"],
        "rss_feeds": rss_feeds or ["https://feeds.finance.yahoo.com/rss/2.0/headline"],
        "rpm_floor": 15,
        "target_duration_min": 12,
    })


@pytest.fixture
def llm():
    return AsyncMock(spec=LLMClient)


@pytest.fixture
def agent(llm):
    return ChannelBuilderAgent(llm=llm)


# ── ChannelConfig ─────────────────────────────────────────────────────────────

class TestChannelConfig:
    def _make_cfg(self, **kwargs) -> ChannelConfig:
        defaults = dict(
            channel_id="test_ch", name="Test", niche="finance", sub_niche="retirement",
            market="US", brand_voice="authoritative", tone="empathetic",
            visual_style="clean_educational", hook_format="Open with dollar loss hook",
            competitor_handles=["@Handle1"], audience={}, trends_keywords=["keyword"],
            rpm_floor=12.0, target_duration_min=10,
        )
        defaults.update(kwargs)
        return ChannelConfig(**defaults)

    def test_hook_format_in_to_dict(self):
        """hook_format must be present in to_dict() — was previously discarded."""
        cfg = self._make_cfg(hook_format="You're losing $400/month in hidden fees")
        d = cfg.to_dict()
        assert "hook_format" in d
        assert d["hook_format"] == "You're losing $400/month in hidden fees"

    def test_brand_color_hex_in_to_dict(self):
        cfg = self._make_cfg(brand_color_hex="#0F172A")
        d = cfg.to_dict()
        assert d["brand_color_hex"] == "#0F172A"

    def test_font_vibe_in_to_dict(self):
        cfg = self._make_cfg(font_vibe="serif_classic")
        d = cfg.to_dict()
        assert d["font_vibe"] == "serif_classic"

    def test_voice_persona_in_to_dict(self):
        cfg = self._make_cfg(voice_persona="authoritative_50yo_male")
        d = cfg.to_dict()
        assert d["voice_persona"] == "authoritative_50yo_male"

    def test_subreddits_in_to_dict(self):
        cfg = self._make_cfg(subreddits=["personalfinance", "retirement"])
        d = cfg.to_dict()
        assert d["subreddits"] == ["personalfinance", "retirement"]

    def test_rss_feeds_in_to_dict(self):
        cfg = self._make_cfg(rss_feeds=["https://feeds.example.com/rss"])
        d = cfg.to_dict()
        assert d["rss_feeds"] == ["https://feeds.example.com/rss"]

    def test_channel_created_at_null_in_to_dict(self):
        """channel_created_at must be present as null — operator fills after YT registration."""
        cfg = self._make_cfg()
        d = cfg.to_dict()
        assert "channel_created_at" in d
        assert d["channel_created_at"] is None

    def test_subreddits_default_empty_list(self):
        cfg = self._make_cfg()
        assert cfg.subreddits == []

    def test_rss_feeds_default_empty_list(self):
        cfg = self._make_cfg()
        assert cfg.rss_feeds == []


# ── ChannelBuilderAgent.build() ───────────────────────────────────────────────

class TestChannelBuilderBuild:
    async def test_build_extracts_hook_format(self, agent, llm):
        llm.complete.return_value = _resp(_full_llm_response(
            hook_format="You're losing $400/month in hidden 401k fees"
        ))
        agent._validate_subreddits = AsyncMock(return_value=["personalfinance"])

        cfg = await agent.build(_niche())
        assert cfg is not None
        assert cfg.hook_format == "You're losing $400/month in hidden 401k fees"

    async def test_build_extracts_brand_color(self, agent, llm):
        llm.complete.return_value = _resp(_full_llm_response(brand_color="#0F172A"))
        agent._validate_subreddits = AsyncMock(return_value=[])

        cfg = await agent.build(_niche())
        assert cfg.brand_color_hex == "#0F172A"

    async def test_build_extracts_font_vibe(self, agent, llm):
        llm.complete.return_value = _resp(_full_llm_response(font_vibe="serif_classic"))
        agent._validate_subreddits = AsyncMock(return_value=[])

        cfg = await agent.build(_niche())
        assert cfg.font_vibe == "serif_classic"

    async def test_build_extracts_voice_persona(self, agent, llm):
        llm.complete.return_value = _resp(_full_llm_response(
            voice_persona="authoritative_50yo_male"
        ))
        agent._validate_subreddits = AsyncMock(return_value=[])

        cfg = await agent.build(_niche())
        assert cfg.voice_persona == "authoritative_50yo_male"

    async def test_build_uses_validated_subreddits(self, agent, llm):
        """Subreddit list from LLM is passed through validator; only valid ones kept."""
        llm.complete.return_value = _resp(_full_llm_response(
            subreddits=["personalfinance", "retirement", "FakeSubThatDoesntExist"]
        ))
        # Validator rejects the fake one
        agent._validate_subreddits = AsyncMock(return_value=["personalfinance", "retirement"])

        cfg = await agent.build(_niche())
        assert cfg.subreddits == ["personalfinance", "retirement"]
        assert "FakeSubThatDoesntExist" not in cfg.subreddits

    async def test_build_approved_name_enforced(self, agent, llm):
        """Approved name from debate overrides LLM output."""
        llm.complete.return_value = _resp(_full_llm_response(
            channel_id="llm_generated_id",
            name="LLM Generated Name"
        ))
        agent._validate_subreddits = AsyncMock(return_value=[])

        cfg = await agent.build(_niche(), approved_name="Retirement Clarity",
                                 approved_channel_id="retirement_clarity")
        assert cfg.name == "Retirement Clarity"
        assert cfg.channel_id == "retirement_clarity"

    async def test_build_json_parse_failure_returns_none(self, agent, llm):
        llm.complete.return_value = _resp("not valid json at all")
        cfg = await agent.build(_niche())
        assert cfg is None

    async def test_build_runs_subreddit_validation(self, agent, llm):
        """_validate_subreddits must be called during build()."""
        llm.complete.return_value = _resp(_full_llm_response())
        agent._validate_subreddits = AsyncMock(return_value=["personalfinance"])

        await agent.build(_niche())
        agent._validate_subreddits.assert_called_once()

    async def test_to_dict_has_all_new_fields(self, agent, llm):
        """Final channel dict must contain all 6 fields that were missing before."""
        llm.complete.return_value = _resp(_full_llm_response())
        agent._validate_subreddits = AsyncMock(return_value=["personalfinance"])

        cfg = await agent.build(_niche())
        assert cfg is not None
        d = cfg.to_dict()

        # Previously missing/discarded
        assert "hook_format" in d and d["hook_format"]
        assert "brand_color_hex" in d
        assert "font_vibe" in d
        assert "voice_persona" in d
        assert "subreddits" in d
        assert "rss_feeds" in d
        assert "channel_created_at" in d


# ── Subreddit Validation ──────────────────────────────────────────────────────

class TestSubredditValidation:
    async def test_valid_subreddit_included(self, agent):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"subscribers": 15_000_000, "subreddit_type": "public"}
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_cls.return_value.__aexit__.return_value = None

            result = await agent._validate_subreddits(["personalfinance"])
        assert "personalfinance" in result

    async def test_nonexistent_subreddit_rejected(self, agent):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_cls.return_value.__aexit__.return_value = None

            result = await agent._validate_subreddits(["RetirementFinanceAdviceFake"])
        assert result == []

    async def test_dead_subreddit_rejected(self, agent):
        """Sub with < REDDIT_MIN_SUBSCRIBERS is rejected as dead."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"subscribers": 10, "subreddit_type": "public"}  # < 500
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_cls.return_value.__aexit__.return_value = None

            result = await agent._validate_subreddits(["TinyDeadSub"])
        assert result == []

    async def test_private_subreddit_rejected(self, agent):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"subscribers": 50_000, "subreddit_type": "private"}
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_cls.return_value.__aexit__.return_value = None

            result = await agent._validate_subreddits(["PrivateSub"])
        assert result == []

    async def test_network_error_fail_safe_includes(self, agent):
        """Network error during check → fail-safe: include sub (don't block crawler)."""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.side_effect = Exception("connection refused")
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_cls.return_value.__aexit__.return_value = None

            result = await agent._validate_subreddits(["personalfinance"])
        assert "personalfinance" in result  # fail-safe: include on error

    async def test_empty_list_returns_empty(self, agent):
        result = await agent._validate_subreddits([])
        assert result == []

    async def test_strips_r_prefix(self, agent):
        """LLM sometimes returns 'r/personalfinance' — strip the prefix."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"subscribers": 1_000_000, "subreddit_type": "public"}
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_cls.return_value.__aexit__.return_value = None

            result = await agent._validate_subreddits(["r/personalfinance"])
        assert len(result) == 1

    async def test_mixed_valid_invalid(self, agent):
        """Mix of valid + hallucinated → only valid returned."""
        call_results = {
            "personalfinance": True,
            "FakeSubXYZ123": False,
            "retirement": True,
        }

        async def fake_check(name, http):
            return call_results.get(name, False)

        with patch.object(agent, "_check_subreddit", side_effect=fake_check), \
             patch("httpx.AsyncClient"):
            result = await agent._validate_subreddits(
                ["personalfinance", "FakeSubXYZ123", "retirement"]
            )
        assert "personalfinance" in result
        assert "retirement" in result
        assert "FakeSubXYZ123" not in result


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_reddit_min_subscribers_reasonable(self):
        """Threshold must reject ghost subs but not overly restrict."""
        assert 100 <= REDDIT_MIN_SUBSCRIBERS <= 5000
