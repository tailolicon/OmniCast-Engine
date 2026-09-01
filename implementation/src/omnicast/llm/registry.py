"""LLM provider registry.

Decouples provider selection from LLMClient. Adding a new OpenAI-compatible
provider (Ollama, Groq, OpenAI, vLLM, LM Studio, ...) is a one-line factory
registration here — no edit to client.py.

A "backend" is any object implementing the LLMBackend protocol (complete /
complete_structured / total_cost). DeepSeek and the dry-run stub already
conform; the inline Anthropic path stays in LLMClient because it carries
rate-limit, circuit-breaker, and prompt-cache logic the test suite asserts on.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

import structlog

from omnicast.llm import LLMResponse
from omnicast.llm.cost import CostCalculator
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


@runtime_checkable
class LLMBackend(Protocol):
    """Structural contract every non-Anthropic backend must satisfy."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse: ...

    async def complete_structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        output_schema: type,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]: ...

    @property
    def total_cost(self) -> float: ...


class OpenAICompatClient:
    """Generic backend for any OpenAI-compatible chat endpoint.

    Ollama, Groq, OpenAI, vLLM, and LM Studio all speak the same
    /chat/completions API; only base_url, api_key, and model differ.
    Local providers (Ollama) report cost 0 because pricing tables don't
    cover them.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        max_tokens: int = 4096,
        provider_id: str = "openai_compat",
    ) -> None:
        self._api_key = api_key or "not-needed"  # Ollama ignores the key
        self._model = model
        self._base_url = base_url
        self._max_tokens = max_tokens
        self._provider_id = provider_id
        self._cost_calc = CostCalculator()
        self._client = None

    async def _get_client(self):
        if self._client is None:
            import httpx
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
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
        client = await self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens or self._max_tokens,
                temperature=temperature,
                messages=[{"role": "system", "content": system}, *messages],
            )
            content = response.choices[0].message.content or ""
            usage = response.usage
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0

            breakdown = self._cost_calc.calculate(self._model, input_tokens, output_tokens)
            self._cost_calc.accumulate(breakdown)

            logger.info(
                "LLM call completed",
                provider=self._provider_id,
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
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
            raise AgentError(f"{self._provider_id} API error: {exc}") from exc

    async def complete_structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        output_schema: type,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]:
        response = await self.complete(
            system=system, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        try:
            import orjson
            import re

            content = response.content
            match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
            if match:
                content = match.group(1).strip()
            parsed_data = orjson.loads(content.strip())
            parsed = output_schema.model_validate(parsed_data)
            return response, parsed
        except Exception as exc:
            raise AgentError(f"Failed to parse {self._provider_id} structured output: {exc}") from exc

    @property
    def total_cost(self) -> float:
        return self._cost_calc.total_cost


# === Registry ===

_LLM_BACKEND_FACTORIES: dict[str, Callable[..., LLMBackend]] = {}


def register_llm_backend(provider_id: str, factory: Callable[..., LLMBackend]) -> None:
    """Register a backend factory. Factory signature: (api_key, model, max_tokens) -> LLMBackend."""
    _LLM_BACKEND_FACTORIES[provider_id] = factory


def get_llm_backend(
    provider_id: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
) -> LLMBackend:
    """Instantiate a backend by provider id. Raises ValueError if unknown."""
    factory = _LLM_BACKEND_FACTORIES.get(provider_id)
    if factory is None:
        available = ", ".join(sorted(_LLM_BACKEND_FACTORIES)) or "(none)"
        raise ValueError(f"Unknown LLM provider: {provider_id}. Available: {available}")
    return factory(api_key=api_key, model=model, max_tokens=max_tokens)


def list_llm_providers() -> list[str]:
    """Registered provider ids (excludes inline 'anthropic' and 'dry_run')."""
    return sorted(_LLM_BACKEND_FACTORIES)


# === Built-in factories ===


def _deepseek_factory(*, api_key, model, max_tokens) -> LLMBackend:
    from omnicast.config.settings import get_settings
    from omnicast.llm.deepseek import DeepSeekClient

    s = get_settings()
    return DeepSeekClient(
        api_key=api_key or s.deepseek_api_key,
        model=model or s.deepseek_pro_model,
        max_tokens=max_tokens,
    )


def _ollama_factory(*, api_key, model, max_tokens) -> LLMBackend:
    from omnicast.config.settings import get_settings

    s = get_settings()
    return OpenAICompatClient(
        api_key=api_key or "ollama",
        model=model or s.ollama_model,
        base_url=s.ollama_base_url,
        max_tokens=max_tokens,
        provider_id="ollama",
    )


def _openai_factory(*, api_key, model, max_tokens) -> LLMBackend:
    from omnicast.config.settings import get_settings

    s = get_settings()
    return OpenAICompatClient(
        api_key=api_key or s.openai_api_key,
        model=model or s.openai_model,
        base_url="https://api.openai.com/v1",
        max_tokens=max_tokens,
        provider_id="openai",
    )


def _groq_factory(*, api_key, model, max_tokens) -> LLMBackend:
    from omnicast.config.settings import get_settings

    s = get_settings()
    return OpenAICompatClient(
        api_key=api_key or s.groq_api_key,
        model=model or s.groq_model,
        base_url="https://api.groq.com/openai/v1",
        max_tokens=max_tokens,
        provider_id="groq",
    )


def _chatgpt_web_factory(*, api_key, model, max_tokens) -> LLMBackend:
    from omnicast.config.settings import get_settings
    from omnicast.llm.chatgpt_web import ChatGPTWebClient

    s = get_settings()
    return ChatGPTWebClient(
        base_url=getattr(s, "chatgpt_web_base_url", ""),
        api_token=api_key or getattr(s, "chatgpt_web_api_token", ""),
        model=model or getattr(s, "chatgpt_web_model", ""),
        effort=getattr(s, "chatgpt_web_effort", ""),
        relay_env=getattr(s, "chatgpt_web_relay_env", ""),
        max_tokens=max_tokens,
    )


register_llm_backend("deepseek", _deepseek_factory)
register_llm_backend("chatgpt_web", _chatgpt_web_factory)
register_llm_backend("ollama", _ollama_factory)
register_llm_backend("openai", _openai_factory)
register_llm_backend("groq", _groq_factory)
