"""Base agent class for all OmniCast agents."""

from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base for all agents.

    Lifecycle: __init__ → execute() → result logged via structlog

    Subclasses implement:
    - name property (agent identifier)
    - system_prompt property (system message for LLM)
    - execute() method (main logic)
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._call_count: int = 0

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier for logging/metrics."""
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt sent to LLM."""
        ...

    async def call_llm(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Call LLM with agent's system prompt."""
        self._call_count += 1
        logger.info(
            "Agent LLM call started",
            agent=self.name,
            message_count=len(messages),
        )

        # Callers (Writer.execute/_ensure_length) often prepend a custom
        # {"role": "system"} message. DeepSeek tolerates system-in-messages but
        # the Anthropic API 400s on it (broke the Claude polish expand pass) —
        # hoist it into the top-level `system` param and send only chat turns.
        system = self.system_prompt
        chat_msgs: list[dict[str, str]] = []
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content") or system
            else:
                chat_msgs.append(m)

        try:
            response = await self._llm.complete(
                system=system,
                messages=chat_msgs or messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            logger.info(
                "Agent LLM call completed",
                agent=self.name,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.cost_usd,
            )

            return response
        except AgentError as exc:
            logger.error(
                "Agent LLM call failed",
                agent=self.name,
                error=str(exc),
            )
            raise

    async def call_llm_structured(
        self,
        messages: list[dict[str, str]],
        output_schema: type,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]:
        """Call LLM expecting structured output."""
        self._call_count += 1
        logger.info(
            "Agent structured LLM call started",
            agent=self.name,
            output_schema=output_schema.__name__,
        )

        try:
            response, parsed = await self._llm.complete_structured(
                system=self.system_prompt,
                messages=messages,
                output_schema=output_schema,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            logger.info(
                "Agent structured LLM call completed",
                agent=self.name,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.cost_usd,
            )

            return response, parsed
        except AgentError as exc:
            logger.error(
                "Agent structured LLM call failed",
                agent=self.name,
                error=str(exc),
            )
            raise

    @abstractmethod
    async def execute(self, *args, **kwargs):
        """Main agent logic. Subclasses implement this."""
        ...

    @property
    def cost(self) -> float:
        """Total LLM cost for this agent instance."""
        return self._llm.total_cost

    @property
    def call_count(self) -> int:
        return self._call_count
