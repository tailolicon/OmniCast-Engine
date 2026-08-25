"""One numeric coercion, used everywhere.

WHY THIS EXISTS: by the third review round, `_num` had been reimplemented in
seven modules with four different behaviours. That divergence is not a style
problem — it is where the defects came from. `like_count` was hardened against
`"n/a"` and `reply_count`, six lines away, was not. `scorer._num` rejected NaN
and infinity; `schedule._num` rejected NaN only, so `views="1e400"` produced an
infinite median views/day in the report that recommends when to publish.

RULES, IDENTICAL FOR EVERY CALLER:

  * `None`, `bool`, unparseable text, NaN and ±infinity are NOT numbers.
    `bool` is excluded on purpose: `True` is not a count of 1, and every place
    it slipped through produced a confident wrong answer rather than an error.
  * A number that cannot exist is not a number either. `rate()` rejects values
    outside 0-1, because an "AVD of 25" is a percentage in a field documented as
    a fraction, and silently accepting it recommended scaling a channel whose
    real retention was 25%, below its own 30% bar.
  * Nothing here raises. The caller decides what an absent value means; that
    decision must not be pre-empted by an exception thrown three frames down.
"""

from __future__ import annotations

_INFINITIES = (float("inf"), float("-inf"))


def num(value) -> float | None:
    """A finite float, or None. Never raises, never accepts a bool."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if result != result or result in _INFINITIES:
        return None
    return result


def count(value, *, minimum: int = 0) -> int | None:
    """A non-negative integer count, or None."""
    result = num(value)
    if result is None or result < minimum:
        return None
    return int(result)


def rate(value, *, low: float = 0.0, high: float = 1.0) -> float | None:
    """A fraction inside [low, high], or None when it cannot be one.

    Out of range is None, NOT clamped. Clamping an AVD of `25` to `1.0` would
    turn a unit mistake into a perfect score; returning None makes the gate say
    "this input is not a rate" and stay unmeasured, which is the truth."""
    result = num(value)
    if result is None or not (low <= result <= high):
        return None
    return result


def ratio(numerator, denominator, *, high: float | None = None) -> float | None:
    """`numerator / denominator`, or None if the result cannot be trusted.

    Guards the division itself, not just its inputs: both sides can be finite
    while the quotient overflows to infinity, which is how a `views_per_viewer`
    of `inf` reached the API as a MEASURED metric — and broke strict JSON on the
    way out."""
    top, bottom = num(numerator), num(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    result = num(top / bottom) if bottom else None
    if result is None or result < 0:
        return None
    if high is not None and result > high:
        return None
    return result


_FALSEY_TEXT = frozenset({"", "0", "no", "false", "off", "none", "null", "n"})


def flag(value) -> bool:
    """Truthiness that does not call the string "no" true.

    `bool("no")` is True, and config, CSV round-trips and query strings all
    produce exactly these words. It passed a safety gate on `compliance_passed
    = "false"` and published a benchmark headline on
    `blind_human_comparison = "no"`."""
    if isinstance(value, str):
        return value.strip().lower() not in _FALSEY_TEXT
    return bool(value)
