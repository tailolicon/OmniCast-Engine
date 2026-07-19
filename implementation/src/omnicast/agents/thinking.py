"""Thinking Agent — self-critique before Critic review."""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class ThinkingAgent(BaseAgent):
    """Internal self-critique. Output = thinking_notes (private, Critic doesn't see).

    Uses Haiku model (cheap) for fast self-review.
    """

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    @property
    def name(self) -> str:
        return "thinking"

    @property
    def system_prompt(self) -> str:
        """Prompt: find logical gaps, weak evidence, rhetorical issues."""
        return (
            "You are a self-critique assistant. "
            "Analyze the script for: logical gaps, weak evidence, "
            "rhetorical issues, and areas that could be stronger. "
            "Return concise thinking notes (bullet points)."
        )

    async def execute(self, draft: ScriptDraft) -> str:
        """Analyze draft and return thinking notes."""
        full_text = f"HOOK: {draft.hook}\n\n"
        for seg in draft.segments:
            full_text += f"{seg.heading}: {seg.content}\n\n"
        full_text += f"OUTRO: {draft.outro}"

        prompt = f"Analyze this script for self-critique:\n\n{full_text}"

        try:
            response = await self.call_llm([{"role": "user", "content": prompt}], temperature=0.3)
            logger.info("Thinking agent completed", variant_id=draft.variant_id)
            return response.content
        except Exception as exc:
            raise AgentError(f"Thinking agent failed: {exc}") from exc
