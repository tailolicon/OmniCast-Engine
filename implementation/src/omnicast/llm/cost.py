"""Token counting and cost calculation for Claude models."""

from __future__ import annotations

from dataclasses import dataclass, field

# Model pricing (per million tokens)
# Tuple: (input, output, cache_write, cache_read)
# DeepSeek: no prompt caching API yet → cache_write/read = 0
MODEL_PRICING: dict[str, tuple[float, float, float, float]] = {
    # Claude
    # Introductory Sonnet 5 pricing through 2026-08-31. Change to $3/$15
    # when Anthropic's published standard pricing takes effect.
    "claude-sonnet-5":           (2.00,  10.00,  2.50,  0.20),
    "claude-sonnet-4-6":         (3.00,  15.00,  3.75,  0.30),
    "claude-haiku-4-5":          (0.80,   4.00,  1.00,  0.08),
    "claude-haiku-4-5-20251001": (0.80,   4.00,  1.00,  0.08),
    "claude-opus-4-5":           (15.00, 75.00, 18.75,  1.50),
    "claude-opus-4-7":           (15.00, 75.00, 18.75,  1.50),
    # DeepSeek — EFFECTIVE prices (the 75%-off promo became the official 1/4 price
    # after 2026-05-31). Tuple: (cache-miss input, output, cache-write, cached input).
    # Cached-input (cache_read) is ~100x cheaper than cache-miss — must NOT equal input
    # or every cache hit is massively over-billed. Verified vs the DeepSeek invoice.
    "deepseek-chat":             (0.27,   1.10,  0.27,  0.014),     # V3 non-reasoning
    "deepseek-v4-pro":           (0.435,  0.87,  0.435, 0.003625),  # std 1.74/3.48 → 1/4
    "deepseek-v4-flash":         (0.14,   0.28,  0.14,   0.0028),
    # Gemini
    "gemini-2.5-pro":            (1.25,  10.00,  0.00,  0.00),
    "gemini-2.5-flash":          (0.30,   2.50,  0.00,  0.00),
    "gemini-2.0-flash":          (0.10,   0.40,  0.00,  0.00),
    "gemini-2.0-flash-lite":     (0.075,  0.30,  0.00,  0.00),
    # OpenAI
    "gpt-4o":                    (2.50,  10.00,  0.00,  0.00),
    "gpt-4o-mini":               (0.15,   0.60,  0.00,  0.00),
    "o3-mini":                   (1.10,   4.40,  0.00,  0.00),
    # Groq (inference only — cost ~same as upstream model)
    "llama-3.3-70b-versatile":   (0.59,   0.79,  0.00,  0.00),
    "llama-3.1-8b-instant":      (0.05,   0.08,  0.00,  0.00),
    "mixtral-8x7b-32768":        (0.24,   0.24,  0.00,  0.00),
    # OpenRouter passthrough (approximate)
    "meta-llama/llama-3.3-70b-instruct":  (0.12,  0.20, 0.00, 0.00),
    "google/gemini-2.0-flash-001":        (0.10,  0.40, 0.00, 0.00),
    "mistralai/mistral-large-2411":       (2.00,  6.00, 0.00, 0.00),
}


@dataclass(frozen=True)
class CostBreakdown:
    """Immutable cost breakdown for a single LLM call."""
    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    input_cost: float
    output_cost: float
    cache_write_cost: float
    cache_read_cost: float
    total_cost: float


class CostCalculator:
    """Calculate and accumulate LLM costs."""

    def __init__(self) -> None:
        self._total_cost: float = 0.0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cache_write_tokens: int = 0
        self._total_cache_read_tokens: int = 0
        self._per_model: dict[str, float] = {}

    def calculate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> CostBreakdown:
        """Calculate cost for a single call. Unknown models default to sonnet pricing."""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
        inp_price, out_price, cw_price, cr_price = pricing

        input_cost       = (input_tokens       * inp_price) / 1_000_000
        output_cost      = (output_tokens       * out_price) / 1_000_000
        cache_write_cost = (cache_write_tokens  * cw_price)  / 1_000_000
        cache_read_cost  = (cache_read_tokens   * cr_price)  / 1_000_000
        total_cost       = input_cost + output_cost + cache_write_cost + cache_read_cost

        return CostBreakdown(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_read_tokens=cache_read_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            cache_write_cost=cache_write_cost,
            cache_read_cost=cache_read_cost,
            total_cost=total_cost,
        )

    def accumulate(self, breakdown: CostBreakdown) -> None:
        """Add to running total."""
        self._total_cost                += breakdown.total_cost
        self._total_input_tokens        += breakdown.input_tokens
        self._total_output_tokens       += breakdown.output_tokens
        self._total_cache_write_tokens  += breakdown.cache_write_tokens
        self._total_cache_read_tokens   += breakdown.cache_read_tokens
        self._per_model[breakdown.model] = (
            self._per_model.get(breakdown.model, 0.0) + breakdown.total_cost
        )

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def total_input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._total_output_tokens

    @property
    def total_cache_write_tokens(self) -> int:
        return self._total_cache_write_tokens

    @property
    def total_cache_read_tokens(self) -> int:
        return self._total_cache_read_tokens

    def summary(self) -> dict[str, float]:
        """Return per-model cost breakdown."""
        return self._per_model.copy()
