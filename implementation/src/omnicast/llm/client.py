"""Claude/DeepSeek LLM client with rate limiting, circuit breaking, cost tracking, and prompt caching."""

from __future__ import annotations

import os
from contextvars import ContextVar

import structlog

from omnicast.cache.rate_limiter import claude_api_limiter
from omnicast.cache.circuit_breaker import CircuitBreaker
from omnicast.config.settings import get_settings
from omnicast.llm.cost import CostCalculator
from omnicast.llm.fallback import DryRunClient
from omnicast.llm import LLMResponse
from omnicast.shared.errors import AgentError, CacheError

logger = structlog.get_logger()


def _is_claude5(model: str) -> bool:
    """Claude 5 family rejects `temperature` (400 'deprecated')."""
    m = (model or "").lower()
    return any(k in m for k in ("claude-sonnet-5", "claude-opus-5", "claude-haiku-5",
                                "claude-fable", "claude-mythos", "claude-5"))


def _make_cached_system(system: str) -> list[dict]:
    """Wrap system prompt as cached content block (ephemeral, 5-min TTL).

    Anthropic requires >= 1024 tokens to cache. API silently ignores
    cache_control when block is too short.
    """
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


# Job-local spend accumulator. Context propagation deliberately shares the same
# mutable state with child tasks (parallel story calls) while concurrent top-level
# jobs that call reset_session_cost() receive independent accumulators.
_SESSION_COST: ContextVar[dict | None] = ContextVar("omnicast_session_cost", default=None)


def _cost_state() -> dict:
    state = _SESSION_COST.get()
    if state is None:
        state = {"total": 0.0, "calls": 0, "by_model": {}}
        _SESSION_COST.set(state)
    return state


def record_cost(model: str, usd: float) -> None:
    if not usd:
        return
    state = _cost_state()
    state["total"] += usd
    state["calls"] += 1
    bm = state["by_model"]
    bm[model or "unknown"] = round(bm.get(model or "unknown", 0.0) + usd, 6)


def get_session_cost() -> dict:
    state = _cost_state()
    return {"total": round(state["total"], 4),
            "calls": state["calls"],
            "by_model": dict(state["by_model"])}


def reset_session_cost() -> None:
    _SESSION_COST.set({"total": 0.0, "calls": 0, "by_model": {}})


class LLMClient:
    """Unified async LLM client.

    Provider selected at construction. Anthropic runs inline (rate limit +
    circuit breaker + prompt caching). Every other provider is resolved from
    the registry as a delegate backend, so adding one (Ollama, OpenAI, Groq,
    ...) needs no edit here — see omnicast.llm.registry. dry_run mode always
    uses DryRunClient regardless of provider.

    Features:
    - Rate limiting + circuit breaker (Anthropic only)
    - Prompt caching via cache_control (Anthropic only)
    - Accurate cost tracking per call
    - Structured output support
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        provider: str = "anthropic",  # "anthropic" | "deepseek" | "ollama" | "openai" | "groq" | ...
        cli_effort: str | None = None,
        role: str = "",
    ) -> None:
        """cli_effort/role are immutable per client and only reach the Claude CLI
        delegate, which is the one backend with an --effort flag. They are set once
        per role-client rather than per call so concurrent channels cannot race
        each other's reasoning depth. Validated eagerly: the CLI ignores an unknown
        --effort with a warning, which would cost minutes per call and surface
        nowhere."""
        from omnicast.llm.claude_cli import CLI_EFFORT_LEVELS
        if cli_effort is not None and cli_effort not in CLI_EFFORT_LEVELS:
            raise ValueError(
                f"unsupported claude CLI effort {cli_effort!r}; allowed: "
                f"{', '.join(CLI_EFFORT_LEVELS)}"
            )
        settings = get_settings()
        self._provider = provider
        self._cli_effort = cli_effort
        self._role = role
        self._max_tokens = max_tokens
        self._cost_calc = CostCalculator()
        # Non-Anthropic providers run through a delegate backend; None means inline Anthropic.
        self._delegate = None
        self._anthropic = None
        self._limiter = None
        self._circuit_breaker = None

        if settings.is_dry_run:
            self._delegate = DryRunClient()
            self._model = model or settings.claude_model
        elif provider == "anthropic" and (
                os.environ.get("OMNICAST_CLAUDE_BACKEND", "").strip().lower()
                or getattr(settings, "omnicast_claude_backend", "").strip().lower()
        ) == "cli":
            # Claude Code CLI headless (`claude -p`) — bills the operator's
            # SUBSCRIPTION instead of API credits (script gen ≈ $0 marginal).
            from omnicast.llm.claude_cli import ClaudeCLIClient
            self._model = model or settings.claude_model
            self._delegate = ClaudeCLIClient(
                model=self._model, effort=cli_effort, role=role,
            )
        elif provider == "anthropic":
            self._model = model or settings.claude_model
            self._api_key = api_key or settings.claude_api_key
            self._anthropic = None  # lazy init
            self._limiter = claude_api_limiter()
            self._circuit_breaker = CircuitBreaker("claude_api")
        else:
            from omnicast.llm.registry import get_llm_backend
            self._delegate = get_llm_backend(
                provider, api_key=api_key, model=model, max_tokens=max_tokens,
            )
            self._model = getattr(self._delegate, "_model", model or "")

    async def _get_anthropic(self):
        """Lazy init Anthropic async client."""
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._anthropic

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send completion request. Routes to correct backend."""
        if self._delegate is not None:
            _r = await self._delegate.complete(
                system=system, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
            )
            record_cost(getattr(_r, "model", None) or self._model, getattr(_r, "cost_usd", 0.0) or 0.0)
            return _r

        # Anthropic path with rate limiting + circuit breaker + prompt caching
        try:
            if not await self._limiter.acquire():
                raise AgentError("Rate limit exceeded for Claude API")
        except CacheError:
            logger.warning("Rate limiter unavailable (Redis not connected), proceeding without rate limit")

        async with self._circuit_breaker:
            try:
                anthropic = await self._get_anthropic()
                _mt = max_tokens or self._max_tokens
                # Claude 5 family: rejects `temperature` (400 "deprecated") AND
                # enables extended thinking by default — thinking tokens bill as
                # OUTPUT ($15/M) and eat the max_tokens budget (measured: one
                # script run $1.37 with a truncated 56-point draft). This is a
                # deterministic emit-JSON workload: disable thinking.
                _kw: dict = {}
                if _is_claude5(self._model):
                    _kw["thinking"] = {"type": "disabled"}
                else:
                    _kw["temperature"] = temperature
                if _mt and _mt > 8192:
                    # SDK refuses non-streaming requests that could exceed 10
                    # minutes (large max_tokens, e.g. the 22k full-script draft).
                    # get_final_message() returns the same Message object.
                    async with anthropic.messages.stream(
                        model=self._model,
                        max_tokens=_mt,
                        system=_make_cached_system(system),
                        messages=messages,
                        **_kw,
                    ) as _stream:
                        response = await _stream.get_final_message()
                else:
                    response = await anthropic.messages.create(
                        model=self._model,
                        max_tokens=_mt,
                        system=_make_cached_system(system),
                        messages=messages,
                        **_kw,
                    )

                # Claude 5 prepends ThinkingBlock(s); take the first text block.
                content = next(
                    (b.text for b in response.content
                     if getattr(b, "type", "") == "text"),
                    "")
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                stop_reason = response.stop_reason
                cache_write_tokens = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
                cache_read_tokens = getattr(response.usage, "cache_read_input_tokens", 0) or 0

                breakdown = self._cost_calc.calculate(
                    self._model, input_tokens, output_tokens,
                    cache_write_tokens=cache_write_tokens,
                    cache_read_tokens=cache_read_tokens,
                )
                self._cost_calc.accumulate(breakdown)
                record_cost(self._model, breakdown.total_cost)

                logger.info(
                    "LLM call completed",
                    provider="anthropic",
                    model=self._model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_write_tokens=cache_write_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cost_usd=breakdown.total_cost,
                )

                return LLMResponse(
                    content=content,
                    model=self._model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=breakdown.total_cost,
                    stop_reason=stop_reason,
                )
            except Exception as exc:
                raise AgentError(f"Claude API error: {exc}") from exc

    async def complete_structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        output_schema: type,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]:
        """Return structured output. Delegate backends + dry-run handle their own; Anthropic parses JSON."""
        if self._delegate is not None:
            _resp, _parsed = await self._delegate.complete_structured(
                system=system, messages=messages,
                output_schema=output_schema,
                max_tokens=max_tokens, temperature=temperature,
            )
            record_cost(getattr(_resp, "model", None) or self._model, getattr(_resp, "cost_usd", 0.0) or 0.0)
            return _resp, _parsed

        # Anthropic — use complete() (inherits prompt caching)
        response = await self.complete(
            system=system, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        try:
            from omnicast.llm.json_utils import parse_json_payload
            parsed_data = parse_json_payload(response.content)
            parsed = output_schema.model_validate(parsed_data)
            return response, parsed
        except Exception as exc:
            raise AgentError(f"Failed to parse structured output: {exc}") from exc

    @property
    def total_cost(self) -> float:
        """Accumulated cost across all calls."""
        if self._delegate is not None:
            return getattr(self._delegate, "total_cost", self._cost_calc.total_cost)
        return self._cost_calc.total_cost

    @property
    def total_tokens(self) -> int:
        return self._cost_calc.total_input_tokens + self._cost_calc.total_output_tokens

    @property
    def cache_stats(self) -> dict[str, int]:
        return {
            "cache_write_tokens": self._cost_calc.total_cache_write_tokens,
            "cache_read_tokens": self._cost_calc.total_cache_read_tokens,
        }
