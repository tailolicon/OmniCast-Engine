"""DeepSeek API client — OpenAI-compatible endpoint."""

from __future__ import annotations

import structlog

from omnicast.llm import LLMResponse
from omnicast.llm.cost import CostCalculator
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class DeepSeekClient:
    """Async DeepSeek client using OpenAI-compatible SDK.

    Supports both deepseek-v4-pro and deepseek-v4-flash.
    Prompt caching not yet supported by DeepSeek API — omitted.
    """

    def __init__(self, api_key: str, model: str, max_tokens: int = 4096) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._cost_calc = CostCalculator()
        self._client = None

    async def _get_client(self):
        if self._client is None:
            import httpx
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url="https://api.deepseek.com",
                timeout=httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=10.0),
                max_retries=2,
            )
        return self._client

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send completion request to DeepSeek API."""
        client = await self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens or self._max_tokens,
                temperature=temperature,
                # V4 enables thinking by default. Routine judging/annotation is a
                # bounded JSON task; hidden reasoning only adds cost and latency.
                extra_body={"thinking": {"type": "disabled"}},
                messages=[
                    {"role": "system", "content": system},
                    *messages,
                ],
            )
            raw_content = response.choices[0].message.content or ""
            # Strip <think>…</think> reasoning blocks (DeepSeek Flash/Reasoner)
            content = _strip_reasoning_tags(raw_content)
            usage = response.usage
            input_tokens  = usage.prompt_tokens
            output_tokens = usage.completion_tokens
            # Reasoning tokens are included in completion_tokens for DeepSeek reasoner models.
            # Extract them for accurate cost calculation (reasoning tokens billed at output rate).
            completion_details = getattr(usage, "completion_tokens_details", None)
            reasoning_tokens = getattr(completion_details, "reasoning_tokens", 0) or 0
            # DeepSeek automatic caching — tracked via these fields
            cache_hit_tokens  = getattr(usage, "prompt_cache_hit_tokens",  0) or 0
            cache_miss_tokens = getattr(usage, "prompt_cache_miss_tokens", 0) or 0

            # prompt_tokens is the total; hit/miss tokens partition that total.
            # Billing all three would double-count cached prompt input.
            uncategorized_input = max(0, input_tokens - cache_miss_tokens - cache_hit_tokens)
            breakdown = self._cost_calc.calculate(
                self._model, uncategorized_input, output_tokens,
                cache_write_tokens=cache_miss_tokens,  # miss = charged at miss price
                cache_read_tokens=cache_hit_tokens,    # hit  = charged at hit price
            )
            self._cost_calc.accumulate(breakdown)

            logger.info(
                "DeepSeek call completed",
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
                cache_hit_tokens=cache_hit_tokens,
                cache_miss_tokens=cache_miss_tokens,
                cost_usd=breakdown.total_cost,
            )

            return LLMResponse(
                content=content,
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=breakdown.total_cost,
                stop_reason=response.choices[0].finish_reason or "stop",
            )
        except Exception as exc:
            raise AgentError(f"DeepSeek API error: {exc}") from exc

    async def complete_structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        output_schema: type,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]:
        """Return structured output parsed from JSON response."""
        response = await self.complete(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            from omnicast.llm.json_utils import (
                coerce_object_schema_payload,
                parse_json_payload,
            )
            parsed_data = parse_json_payload(_strip_json_fences(response.content))
            parsed_data = coerce_object_schema_payload(
                parsed_data, output_schema)
            # Clamp total_score to 100 — LLM sometimes returns >100 when weights sum oddly
            if (
                isinstance(parsed_data, dict)
                and "total_score" in parsed_data
                and isinstance(parsed_data["total_score"], (int, float))
            ):
                parsed_data["total_score"] = min(int(parsed_data["total_score"]), 100)
            parsed = output_schema.model_validate(parsed_data)
            return response, parsed
        except Exception as exc:
            raise AgentError(f"Failed to parse DeepSeek structured output: {exc}") from exc


    @property
    def total_cost(self) -> float:
        return self._cost_calc.total_cost


def _strip_reasoning_tags(text: str) -> str:
    """Strip <think>...</think> reasoning blocks emitted by DeepSeek Flash/Reasoner."""
    import re
    # Remove everything inside <think>…</think> (greedy-safe, DOTALL)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences and reasoning tags from LLM JSON responses."""
    import re
    # 1. Remove <think>…</think> reasoning blocks first
    text = _strip_reasoning_tags(text)
    # 2. Strip ```json … ``` or ``` … ``` fences
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text.strip()
