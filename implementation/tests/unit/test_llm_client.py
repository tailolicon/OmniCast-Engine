"""Tests for LLM client wrapper."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.llm.fallback import DryRunClient
from omnicast.llm.cost import CostCalculator, CostBreakdown, MODEL_PRICING
from omnicast.shared.errors import AgentError


# === CostCalculator Tests ===


class TestCostCalculator:
    def test_calculate_sonnet(self):
        calc = CostCalculator()
        result = calc.calculate("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
        assert isinstance(result, CostBreakdown)
        assert result.model == "claude-sonnet-4-6"
        assert result.input_tokens == 1000
        assert result.output_tokens == 500
        # 1000 * 3.0 / 1_000_000 = 0.003
        assert result.input_cost == pytest.approx(0.003, abs=1e-6)
        # 500 * 15.0 / 1_000_000 = 0.0075
        assert result.output_cost == pytest.approx(0.0075, abs=1e-6)
        assert result.total_cost == pytest.approx(0.0105, abs=1e-6)

    def test_calculate_haiku(self):
        calc = CostCalculator()
        result = calc.calculate("claude-haiku-4-5", input_tokens=2000, output_tokens=1000)
        # 2000 * 0.80 / 1M = 0.0016, 1000 * 4.0 / 1M = 0.004
        assert result.input_cost == pytest.approx(0.0016, abs=1e-6)
        assert result.output_cost == pytest.approx(0.004, abs=1e-6)

    def test_calculate_unknown_model_defaults_sonnet(self):
        calc = CostCalculator()
        result = calc.calculate("claude-unknown-99", input_tokens=1000, output_tokens=500)
        # Should use sonnet pricing as fallback
        assert result.input_cost == pytest.approx(0.003, abs=1e-6)

    def test_accumulate(self):
        calc = CostCalculator()
        b1 = calc.calculate("claude-sonnet-4-6", 1000, 500)
        b2 = calc.calculate("claude-haiku-4-5", 2000, 1000)
        calc.accumulate(b1)
        calc.accumulate(b2)
        assert calc.total_cost == pytest.approx(b1.total_cost + b2.total_cost, abs=1e-6)
        assert calc.total_input_tokens == 3000
        assert calc.total_output_tokens == 1500

    def test_summary_per_model(self):
        calc = CostCalculator()
        calc.accumulate(calc.calculate("claude-sonnet-4-6", 1000, 500))
        calc.accumulate(calc.calculate("claude-haiku-4-5", 2000, 1000))
        summary = calc.summary()
        assert "claude-sonnet-4-6" in summary
        assert "claude-haiku-4-5" in summary


# === DryRunClient Tests ===


class TestDryRunClient:
    async def test_complete_returns_mock(self):
        client = DryRunClient()
        response = await client.complete(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert isinstance(response, LLMResponse)
        assert "[DRY RUN]" in response.content
        assert response.cost_usd == 0.0
        assert response.input_tokens == 0
        assert response.output_tokens == 0

    async def test_complete_structured_returns_defaults(self):
        from pydantic import BaseModel

        class TestOutput(BaseModel):
            score: int = 0
            feedback: str = ""

        client = DryRunClient()
        response, parsed = await client.complete_structured(
            system="Judge.",
            messages=[{"role": "user", "content": "Rate this."}],
            output_schema=TestOutput,
        )
        assert isinstance(response, LLMResponse)
        assert isinstance(parsed, TestOutput)
        assert parsed.score == 0


# === LLMClient Tests ===


class TestLLMClient:
    @pytest.fixture
    def mock_settings(self, monkeypatch):
        """Mock settings for LLMClient."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        monkeypatch.setenv("CLAUDE_API_KEY", "sk-test-key")
        monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        monkeypatch.setenv("OMNICAST_CLAUDE_BACKEND", "api")
        monkeypatch.setenv("OMNICAST_MODE", "staging")
        from omnicast.config.settings import reset_settings
        reset_settings()

    @pytest.fixture
    def mock_rate_limiter(self):
        limiter = AsyncMock()
        limiter.acquire.return_value = True
        return limiter

    @pytest.fixture
    def mock_anthropic_response(self):
        """Mock anthropic.types.Message."""
        msg = MagicMock()
        msg.content = [MagicMock(text="Hello from Claude", type="text")]
        msg.model = "claude-sonnet-4-6"
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 50
        msg.usage.cache_creation_input_tokens = 0
        msg.usage.cache_read_input_tokens = 0
        msg.stop_reason = "end_turn"
        return msg

    async def test_complete_success(
        self, mock_settings, mock_rate_limiter, mock_anthropic_response
    ):
        with patch("omnicast.llm.client.claude_api_limiter", return_value=mock_rate_limiter):
            with patch("omnicast.llm.client.CircuitBreaker") as MockCB:
                cb_instance = AsyncMock()
                cb_instance.__aenter__ = AsyncMock(return_value=cb_instance)
                cb_instance.__aexit__ = AsyncMock(return_value=False)
                MockCB.return_value = cb_instance

                client = LLMClient(api_key="sk-test")
                # Mock the internal anthropic client
                client._anthropic = AsyncMock()
                client._anthropic.messages.create = AsyncMock(
                    return_value=mock_anthropic_response
                )

                response = await client.complete(
                    system="You are helpful.",
                    messages=[{"role": "user", "content": "Hello"}],
                )
                assert isinstance(response, LLMResponse)
                assert response.content == "Hello from Claude"
                assert response.input_tokens == 100
                assert response.output_tokens == 50
                assert response.cost_usd > 0

    async def test_complete_rate_limited(self, mock_settings):
        mock_limiter = AsyncMock()
        mock_limiter.acquire.return_value = False
        with patch("omnicast.llm.client.claude_api_limiter", return_value=mock_limiter):
            client = LLMClient(api_key="sk-test")
            with pytest.raises(AgentError, match="Rate limit"):
                await client.complete(
                    system="test",
                    messages=[{"role": "user", "content": "hi"}],
                )

    async def test_dry_run_mode(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
        monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
        monkeypatch.setenv("OMNICAST_MODE", "dry_run")
        from omnicast.config.settings import reset_settings
        reset_settings()

        client = LLMClient()
        response = await client.complete(
            system="test",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert "[DRY RUN]" in response.content
        assert response.cost_usd == 0.0

    async def test_total_cost_accumulates(self, mock_settings, mock_anthropic_response):
        mock_limiter = AsyncMock()
        mock_limiter.acquire.return_value = True
        with patch("omnicast.llm.client.claude_api_limiter", return_value=mock_limiter):
            with patch("omnicast.llm.client.CircuitBreaker") as MockCB:
                cb = AsyncMock()
                cb.__aenter__ = AsyncMock(return_value=cb)
                cb.__aexit__ = AsyncMock(return_value=False)
                MockCB.return_value = cb

                client = LLMClient(api_key="sk-test")
                client._anthropic = AsyncMock()
                client._anthropic.messages.create = AsyncMock(
                    return_value=mock_anthropic_response
                )

                await client.complete(
                    system="test", messages=[{"role": "user", "content": "1"}]
                )
                await client.complete(
                    system="test", messages=[{"role": "user", "content": "2"}]
                )
                assert client.total_cost > 0
                assert client.total_tokens == 300  # (100+50) * 2
