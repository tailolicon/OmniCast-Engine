"""Tests for BaseAgent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.shared.errors import AgentError


class ConcreteAgent(BaseAgent):
    """Concrete implementation for testing."""

    @property
    def name(self) -> str:
        return "test_agent"

    @property
    def system_prompt(self) -> str:
        return "You are a test agent."

    async def execute(self, input_text: str) -> str:
        response = await self.call_llm(
            [{"role": "user", "content": input_text}]
        )
        return response.content


class TestBaseAgent:
    @pytest.fixture
    def mock_llm(self) -> AsyncMock:
        llm = AsyncMock(spec=LLMClient)
        llm.complete.return_value = LLMResponse(
            content="test response",
            model="claude-sonnet-4-6",
            input_tokens=50,
            output_tokens=25,
            cost_usd=0.000525,
            stop_reason="end_turn",
        )
        llm.total_cost = 0.000525
        return llm

    @pytest.fixture
    def agent(self, mock_llm) -> ConcreteAgent:
        return ConcreteAgent(llm=mock_llm)

    async def test_call_llm_delegates(self, agent, mock_llm):
        response = await agent.call_llm(
            [{"role": "user", "content": "hello"}]
        )
        assert response.content == "test response"
        mock_llm.complete.assert_called_once()
        call_kwargs = mock_llm.complete.call_args
        assert call_kwargs.kwargs["system"] == "You are a test agent."

    async def test_call_count_increments(self, agent):
        assert agent.call_count == 0
        await agent.call_llm([{"role": "user", "content": "1"}])
        assert agent.call_count == 1
        await agent.call_llm([{"role": "user", "content": "2"}])
        assert agent.call_count == 2

    async def test_execute_uses_call_llm(self, agent):
        result = await agent.execute("test input")
        assert result == "test response"

    async def test_llm_error_raises_agent_error(self, mock_llm):
        mock_llm.complete.side_effect = AgentError("LLM failed")
        agent = ConcreteAgent(llm=mock_llm)
        with pytest.raises(AgentError, match="LLM failed"):
            await agent.call_llm([{"role": "user", "content": "fail"}])

    async def test_name_property(self, agent):
        assert agent.name == "test_agent"

    async def test_system_prompt_property(self, agent):
        assert "test agent" in agent.system_prompt

    async def test_call_llm_structured(self, mock_llm):
        from pydantic import BaseModel

        class Output(BaseModel):
            score: int = 5

        mock_llm.complete_structured.return_value = (
            LLMResponse(
                content="{}",
                model="claude-sonnet-4-6",
                input_tokens=50,
                output_tokens=25,
                cost_usd=0.0005,
                stop_reason="end_turn",
            ),
            Output(score=5),
        )
        agent = ConcreteAgent(llm=mock_llm)
        response, parsed = await agent.call_llm_structured(
            [{"role": "user", "content": "rate"}],
            output_schema=Output,
        )
        assert parsed.score == 5
