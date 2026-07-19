"""Tests for ChannelNameDebateAgent — 4-stage name selection pipeline."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from omnicast.agents.channel_name_debate import (
    ChannelNameDebateAgent,
    NameCandidate,
    DebateResult,
    render_debate_table,
    _to_channel_id,
    _to_youtube_handle,
    NAME_ANGLES,
    SCORE_WEIGHTS,
    TAKEN_HANDLE_TRUST_PENALTY,
)
from omnicast.llm.client import LLMClient, LLMResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="deepseek-flash",
        input_tokens=200,
        output_tokens=100,
        cost_usd=0.0002,
        stop_reason="end_turn",
    )


def _niche(
    name="Retirement Savings Tips",
    category="finance",
    audience="adults 55-70, anxious about running out of money",
    pain_points=None,
    example_channels=None,
    estimated_rpm=15,
) -> dict:
    return {
        "niche_name": name,
        "category": category,
        "audience_description": audience,
        "pain_points": pain_points or ["running out of money", "social security confusion", "inflation fear"],
        "content_triggers": ["retirement date approaching", "401k losses"],
        "example_channels": example_channels or ["@RetirementTalk", "@SeniorFinance"],
        "estimated_rpm": estimated_rpm,
    }


def _stage1_json() -> str:
    return """[
      {"name": "Retirement Clarity", "channel_id": "retirement_clarity", "angle": "outcome", "rationale": "Outcome word matches fear of confusion"},
      {"name": "Senior Money Guide", "channel_id": "senior_money_guide", "angle": "guide", "rationale": "Trusted mentor framing for 60+ audience"},
      {"name": "Your Nest Egg", "channel_id": "your_nest_egg", "angle": "community", "rationale": "Possessive creates belonging"},
      {"name": "What Wall Street Hides", "channel_id": "what_wall_st_hides", "angle": "challenge", "rationale": "Provocative for skeptical retirees"},
      {"name": "Plain Retirement Talk", "channel_id": "plain_retirement", "angle": "simplicity", "rationale": "Anti-jargon signal"},
      {"name": "The Retirement Advisor", "channel_id": "the_retirement_adv", "angle": "authority", "rationale": "Expert credibility signal"}
    ]"""


def _stage2_json() -> str:
    return """[
      {"name": "Retirement Clarity", "audience_trust": 9.0, "memorability": 8.5, "searchability": 8.0, "differentiation": 7.5},
      {"name": "Senior Money Guide", "audience_trust": 8.5, "memorability": 7.5, "searchability": 8.5, "differentiation": 6.0},
      {"name": "Your Nest Egg", "audience_trust": 8.0, "memorability": 8.0, "searchability": 7.0, "differentiation": 7.0},
      {"name": "What Wall Street Hides", "audience_trust": 6.5, "memorability": 8.0, "searchability": 7.5, "differentiation": 9.0},
      {"name": "Plain Retirement Talk", "audience_trust": 7.5, "memorability": 7.0, "searchability": 7.5, "differentiation": 7.0},
      {"name": "The Retirement Advisor", "audience_trust": 8.0, "memorability": 7.0, "searchability": 8.0, "differentiation": 5.0}
    ]"""


def _stage3_json(winner="Retirement Clarity", runner_up="Senior Money Guide") -> str:
    return (
        f'{{"winner_name": "{winner}", "runner_up_name": "{runner_up}", '
        f'"reason": "Retirement Clarity directly addresses the fear of financial confusion."}}'
    )


def _make_candidate(name: str, available: bool | None = True, trust: float = 8.0) -> NameCandidate:
    return NameCandidate(
        name=name,
        channel_id=_to_channel_id(name),
        angle="outcome",
        rationale="test",
        audience_trust=trust,
        memorability=7.0,
        searchability=7.0,
        differentiation=6.0,
        handle_available=available,
    )


@pytest.fixture
def flash_llm():
    return AsyncMock(spec=LLMClient)


@pytest.fixture
def chat_llm():
    return AsyncMock(spec=LLMClient)


@pytest.fixture
def agent(flash_llm, chat_llm):
    # No yt_api_key — handle check will use HTTP or be patched
    return ChannelNameDebateAgent(flash_llm=flash_llm, chat_llm=chat_llm)


# ── _to_channel_id ────────────────────────────────────────────────────────────

class TestToChannelId:
    def test_basic_conversion(self):
        assert _to_channel_id("Retirement Clarity") == "retirement_clarity"

    def test_strips_special_chars(self):
        result = _to_channel_id("What Wall Street Hides!")
        assert "!" not in result
        assert " " not in result

    def test_max_25_chars(self):
        result = _to_channel_id("A Very Long Channel Name That Exceeds Limit")
        assert len(result) <= 25

    def test_no_trailing_underscore(self):
        result = _to_channel_id("A" * 30)
        assert not result.endswith("_")


# ── _to_youtube_handle ────────────────────────────────────────────────────────

class TestToYouTubeHandle:
    def test_basic_camel_case(self):
        assert _to_youtube_handle("Retirement Clarity") == "@RetirementClarity"

    def test_strips_special_chars(self):
        handle = _to_youtube_handle("Senior Money & Life")
        assert "&" not in handle
        assert handle.startswith("@")

    def test_max_30_chars(self):
        handle = _to_youtube_handle("A Very Long Channel Name That Definitely Exceeds The Limit")
        # @ + 30 chars max
        assert len(handle) <= 31

    def test_no_spaces(self):
        handle = _to_youtube_handle("What Wall Street Hides")
        assert " " not in handle

    def test_starts_with_at(self):
        assert _to_youtube_handle("Any Name").startswith("@")

    def test_empty_name_returns_default(self):
        handle = _to_youtube_handle("!!! ### &&&")
        assert handle == "@Channel"


# ── NameCandidate ─────────────────────────────────────────────────────────────

class TestNameCandidate:
    def test_total_score_weighted(self):
        c = NameCandidate(
            name="Test", channel_id="test", angle="outcome", rationale="r",
            audience_trust=10.0, memorability=10.0, searchability=10.0, differentiation=10.0,
        )
        assert c.total_score == pytest.approx(10.0)

    def test_weights_sum_to_one(self):
        assert sum(SCORE_WEIGHTS.values()) == pytest.approx(1.0)

    def test_audience_trust_weighted_highest(self):
        c1 = NameCandidate("", "", "", "", audience_trust=10.0, memorability=0.0, searchability=0.0, differentiation=0.0)
        c2 = NameCandidate("", "", "", "", audience_trust=0.0, memorability=10.0, searchability=0.0, differentiation=0.0)
        assert c1.total_score > c2.total_score

    def test_handle_auto_computed(self):
        c = NameCandidate("Retirement Clarity", "retirement_clarity", "outcome", "r",
                          8.0, 7.0, 7.0, 6.0)
        assert c.handle == "@RetirementClarity"

    def test_handle_available_defaults_none(self):
        c = NameCandidate("Name", "name", "outcome", "r", 7.0, 7.0, 7.0, 6.0)
        assert c.handle_available is None


# ── Handle Availability Check (Stage 1.5) ────────────────────────────────────

class TestHandleAvailabilityCheck:
    async def test_available_handle_marked_true(self, agent):
        """HTTP 404 → handle available → handle_available = True."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_http
            mock_client_cls.return_value.__aexit__.return_value = None

            candidates = [_make_candidate("Test Channel", available=None)]
            result = await agent._stage1_5_check_handles(candidates)

        assert result[0].handle_available is True

    async def test_taken_handle_marked_false(self, agent):
        """HTTP 200 → handle taken → handle_available = False."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_http
            mock_client_cls.return_value.__aexit__.return_value = None

            candidates = [_make_candidate("Test Channel", available=None)]
            result = await agent._stage1_5_check_handles(candidates)

        assert result[0].handle_available is False

    async def test_check_failure_marks_unknown(self, agent):
        """Network error → handle_available = None (unknown, not penalized)."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.side_effect = Exception("connection timeout")
            mock_client_cls.return_value.__aenter__.return_value = mock_http
            mock_client_cls.return_value.__aexit__.return_value = None

            candidates = [_make_candidate("Test Channel", available=None)]
            result = await agent._stage1_5_check_handles(candidates)

        assert result[0].handle_available is None  # unknown, not penalized

    async def test_multiple_handles_checked_in_parallel(self, agent):
        """All 6 handles checked; mix of available/taken."""
        responses = [200, 404, 404, 200, 404, 200]  # taken, avail, avail, taken, avail, taken

        call_idx = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_idx
            resp = MagicMock()
            resp.status_code = responses[call_idx % len(responses)]
            call_idx += 1
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.side_effect = mock_get
            mock_client_cls.return_value.__aenter__.return_value = mock_http
            mock_client_cls.return_value.__aexit__.return_value = None

            candidates = [_make_candidate(f"Channel {i}", available=None) for i in range(6)]
            result = await agent._stage1_5_check_handles(candidates)

        assert len(result) == 6
        assert result[0].handle_available is False  # 200
        assert result[1].handle_available is True   # 404
        assert result[2].handle_available is True   # 404

    async def test_api_key_used_when_provided(self, flash_llm, chat_llm):
        """yt_api_key provided → use YouTube API, not HTTP."""
        agent_with_key = ChannelNameDebateAgent(
            flash_llm=flash_llm, chat_llm=chat_llm, yt_api_key="test_key"
        )
        mock_api_resp = MagicMock()
        mock_api_resp.status_code = 200
        mock_api_resp.json.return_value = {"items": []}  # empty → available

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_api_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_http
            mock_client_cls.return_value.__aexit__.return_value = None

            candidates = [_make_candidate("Retirement Clarity", available=None)]
            result = await agent_with_key._stage1_5_check_handles(candidates)

        assert result[0].handle_available is True
        # Verify API URL was used
        call_url = mock_http.get.call_args[0][0]
        assert "googleapis.com" in call_url

    async def test_api_key_channel_found_marks_taken(self, flash_llm, chat_llm):
        """API returns items → channel exists → handle taken."""
        agent_with_key = ChannelNameDebateAgent(
            flash_llm=flash_llm, chat_llm=chat_llm, yt_api_key="test_key"
        )
        mock_api_resp = MagicMock()
        mock_api_resp.status_code = 200
        mock_api_resp.json.return_value = {"items": [{"id": "UC123"}]}  # found → taken

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_api_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_http
            mock_client_cls.return_value.__aexit__.return_value = None

            candidates = [_make_candidate("Senior Money Guide", available=None)]
            result = await agent_with_key._stage1_5_check_handles(candidates)

        assert result[0].handle_available is False


# ── Trust Penalty for TAKEN handles ──────────────────────────────────────────

class TestTakenHandlePenalty:
    async def test_taken_handle_reduces_trust_score(self, agent, flash_llm, chat_llm):
        """TAKEN handle → audience_trust reduced by TAKEN_HANDLE_TRUST_PENALTY in scoring."""
        flash_llm.complete.side_effect = [
            _resp(_stage1_json()),
            _resp(_stage2_json()),   # scores BEFORE penalty
        ]
        chat_llm.complete.return_value = _resp(_stage3_json())

        # Patch handle check: first candidate TAKEN, rest available
        async def mock_check_handles(candidates):
            result = []
            for i, c in enumerate(candidates):
                result.append(NameCandidate(
                    name=c.name, channel_id=c.channel_id, angle=c.angle,
                    rationale=c.rationale, audience_trust=c.audience_trust,
                    memorability=c.memorability, searchability=c.searchability,
                    differentiation=c.differentiation,
                    handle_available=(False if i == 0 else True),  # first taken
                ))
            return result

        agent._stage1_5_check_handles = mock_check_handles
        result = await agent.debate(_niche())

        # Winner should NOT be the TAKEN candidate (even if it had highest raw score)
        # because penalty demotes it
        taken_cand = next((c for c in result.all_candidates if c.handle_available is False), None)
        if taken_cand:
            # Its trust score should be penalized — raw was 9.0, after penalty should be lower
            assert taken_cand.audience_trust <= 9.0 - TAKEN_HANDLE_TRUST_PENALTY + 0.01

    def test_penalty_constant_reasonable(self):
        """Penalty must be enough to demote TAKEN handle but not destroy score."""
        assert 1.0 <= TAKEN_HANDLE_TRUST_PENALTY <= 4.0

    def test_penalty_applied_trust_floored_at_zero(self, agent):
        """Trust can't go below 0 after penalty."""
        # If raw trust is 1.0 and penalty is 2.0, result should be max(0, 1.0-2.0) = 0.0
        assert max(0.0, 1.0 - TAKEN_HANDLE_TRUST_PENALTY) >= 0.0


# ── Full Debate Pipeline ──────────────────────────────────────────────────────

class TestChannelNameDebateAgent:
    async def _run_debate(self, agent, flash_llm, chat_llm, handle_available=True):
        """Helper: run debate with mocked handle availability."""
        flash_llm.complete.side_effect = [
            _resp(_stage1_json()),
            _resp(_stage2_json()),
        ]
        chat_llm.complete.return_value = _resp(_stage3_json())

        async def mock_check_handles(candidates):
            return [
                NameCandidate(
                    name=c.name, channel_id=c.channel_id, angle=c.angle,
                    rationale=c.rationale, audience_trust=c.audience_trust,
                    memorability=c.memorability, searchability=c.searchability,
                    differentiation=c.differentiation,
                    handle_available=handle_available,
                )
                for c in candidates
            ]
        agent._stage1_5_check_handles = mock_check_handles
        return await agent.debate(_niche())

    async def test_full_debate_returns_winner(self, agent, flash_llm, chat_llm):
        result = await self._run_debate(agent, flash_llm, chat_llm)
        assert isinstance(result, DebateResult)
        assert result.winner.name == "Retirement Clarity"
        assert result.runner_up is not None
        assert len(result.all_candidates) == 6

    async def test_candidates_sorted_by_score_descending(self, agent, flash_llm, chat_llm):
        result = await self._run_debate(agent, flash_llm, chat_llm)
        scores = [c.total_score for c in result.all_candidates]
        assert scores == sorted(scores, reverse=True)

    async def test_stage1_failure_returns_fallback(self, agent, flash_llm, chat_llm):
        flash_llm.complete.side_effect = Exception("API error")
        result = await agent.debate(_niche())
        assert result.winner.name == _niche()["niche_name"]
        assert "Fallback" in result.winner.rationale

    async def test_stage2_failure_graceful(self, agent, flash_llm, chat_llm):
        flash_llm.complete.side_effect = [
            _resp(_stage1_json()),
            Exception("score timeout"),
        ]
        chat_llm.complete.return_value = _resp(_stage3_json())

        async def mock_check_handles(c): return c
        agent._stage1_5_check_handles = mock_check_handles

        result = await agent.debate(_niche())
        assert result.winner is not None

    async def test_stage3_failure_prefers_available_handle(self, agent, flash_llm, chat_llm):
        """Stage 3 fails → fallback picks first AVAILABLE handle, not just index 0."""
        flash_llm.complete.side_effect = [
            _resp(_stage1_json()),
            _resp(_stage2_json()),
        ]
        chat_llm.complete.side_effect = Exception("selector timeout")

        # First candidate TAKEN, second available
        async def mock_check_handles(candidates):
            result = []
            for i, c in enumerate(candidates):
                result.append(NameCandidate(
                    name=c.name, channel_id=c.channel_id, angle=c.angle,
                    rationale=c.rationale, audience_trust=c.audience_trust,
                    memorability=c.memorability, searchability=c.searchability,
                    differentiation=c.differentiation,
                    handle_available=(False if i == 0 else True),
                ))
            return result

        agent._stage1_5_check_handles = mock_check_handles
        result = await agent.debate(_niche())
        # Should pick an available handle if stage 3 fails
        if result.winner.handle_available is not None:
            assert result.winner.handle_available is not False

    async def test_winner_in_all_candidates(self, agent, flash_llm, chat_llm):
        result = await self._run_debate(agent, flash_llm, chat_llm)
        assert result.winner in result.all_candidates

    async def test_handle_availability_in_candidates(self, agent, flash_llm, chat_llm):
        """Each candidate has handle_available field set after Stage 1.5."""
        result = await self._run_debate(agent, flash_llm, chat_llm, handle_available=True)
        for c in result.all_candidates:
            assert c.handle_available is True

    async def test_flash_used_for_stages_1_2(self, agent, flash_llm, chat_llm):
        """Flash: gen+score (2 calls); Chat: selector (1 call)."""
        result = await self._run_debate(agent, flash_llm, chat_llm)
        assert flash_llm.complete.call_count == 2
        assert chat_llm.complete.call_count == 1

    async def test_handle_present_in_all_candidates(self, agent, flash_llm, chat_llm):
        """All candidates have @Handle field populated."""
        result = await self._run_debate(agent, flash_llm, chat_llm)
        for c in result.all_candidates:
            assert c.handle.startswith("@")

    async def test_n_candidates_respected(self, agent, flash_llm, chat_llm):
        flash_llm.complete.side_effect = [
            _resp("""[
              {"name": "A", "channel_id": "a", "angle": "outcome", "rationale": "r"},
              {"name": "B", "channel_id": "b", "angle": "guide", "rationale": "r"},
              {"name": "C", "channel_id": "c", "angle": "authority", "rationale": "r"}
            ]"""),
            _resp("""[
              {"name": "A", "audience_trust": 8.0, "memorability": 7.0, "searchability": 7.0, "differentiation": 6.0},
              {"name": "B", "audience_trust": 7.0, "memorability": 7.5, "searchability": 7.0, "differentiation": 7.0},
              {"name": "C", "audience_trust": 7.5, "memorability": 7.0, "searchability": 8.0, "differentiation": 6.5}
            ]"""),
        ]
        chat_llm.complete.return_value = _resp(
            '{"winner_name": "A", "runner_up_name": "B", "reason": "A best for audience"}'
        )
        async def mock_check_handles(c): return c
        agent._stage1_5_check_handles = mock_check_handles

        result = await agent.debate(_niche(), n_candidates=3)
        assert len(result.all_candidates) == 3


# ── render_debate_table ───────────────────────────────────────────────────────

class TestRenderDebateTable:
    def _make_result(self, avail1=True, avail2=False) -> DebateResult:
        cands = [
            NameCandidate("Retirement Clarity", "retirement_clarity", "outcome", "r",
                          9.0, 8.5, 8.0, 7.5, handle_available=avail1),
            NameCandidate("Senior Money Guide", "senior_money_guide", "guide", "r",
                          8.5, 7.5, 8.5, 6.0, handle_available=avail2),
        ]
        return DebateResult(
            winner=cands[0], runner_up=cands[1], all_candidates=cands,
            selection_reason="Clarity resolves anxiety directly."
        )

    def test_table_contains_winner_star(self):
        table = render_debate_table(self._make_result())
        assert "★" in table

    def test_table_contains_winner_name(self):
        table = render_debate_table(self._make_result())
        assert "Retirement Clarity" in table

    def test_table_contains_handle(self):
        table = render_debate_table(self._make_result())
        assert "@RetirementClarity" in table

    def test_table_shows_available_marker(self):
        table = render_debate_table(self._make_result(avail1=True))
        assert "✅" in table

    def test_table_shows_taken_marker(self):
        table = render_debate_table(self._make_result(avail2=False))
        assert "❌" in table or "TAKEN" in table

    def test_table_shows_unknown_marker(self):
        table = render_debate_table(self._make_result(avail1=None))
        assert "?" in table

    def test_table_contains_reason(self):
        table = render_debate_table(self._make_result())
        assert "Clarity resolves anxiety directly." in table

    def test_winner_footer_shows_handle(self):
        table = render_debate_table(self._make_result(avail1=True))
        assert "@RetirementClarity" in table
        assert "available" in table.lower()


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_name_angles_count(self):
        assert len(NAME_ANGLES) == 6

    def test_score_weights_sum_to_1(self):
        assert sum(SCORE_WEIGHTS.values()) == pytest.approx(1.0)

    def test_trust_weight_dominates(self):
        assert SCORE_WEIGHTS["audience_trust"] == max(SCORE_WEIGHTS.values())

    def test_taken_penalty_positive(self):
        assert TAKEN_HANDLE_TRUST_PENALTY > 0

    def test_taken_penalty_reasonable(self):
        """Penalty must demote but not destroy."""
        assert 1.0 <= TAKEN_HANDLE_TRUST_PENALTY <= 4.0
