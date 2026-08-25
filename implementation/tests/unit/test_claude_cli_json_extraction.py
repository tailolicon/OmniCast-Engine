"""A model that returns the right JSON wrapped in a sentence is not a schema error.

The narrative planner has logged planner=4 / planner_schema_retry=4 for weeks:
every first attempt failing, planner quota spent twice on every plan. Because
the caller labels any exception "schema or provider error", it read as though
the planner kept returning the wrong FIELDS.

Three explanations were measured and eliminated before touching this:

  * the prompt enumerates all 16 schema-required story fields;
  * 345 real continuity_ledger entries top out at 21 words against a 24 limit;
  * real plans run 2,100-2,350 tokens against a 3,200 output cap.

What was left is the wrapper. The old parser accepted a bare document or a
```json fence and nothing else, so "Here is the plan: {...}" raised — and the
contract retry succeeds because its text is forceful enough to suppress the
preamble.
"""

from __future__ import annotations

import orjson
import pytest

from omnicast.llm.claude_cli import extract_json

DOC = '{"topic": "t", "stories": [{"story_id": "story_1"}]}'


def _roundtrip(raw: str) -> dict:
    return orjson.loads(extract_json(raw))


def test_a_bare_document_still_works():
    assert _roundtrip(DOC)["topic"] == "t"


def test_a_fenced_document_still_works():
    assert _roundtrip(f"```json\n{DOC}\n```")["topic"] == "t"


def test_an_unlabelled_fence_still_works():
    assert _roundtrip(f"```\n{DOC}\n```")["topic"] == "t"


def test_a_preamble_no_longer_breaks_it():
    """The shape that was costing a planner call on every generation."""
    assert _roundtrip(f"Here is the compilation plan:\n\n{DOC}")["topic"] == "t"


def test_a_trailing_remark_no_longer_breaks_it():
    assert _roundtrip(f"{DOC}\n\nLet me know if you want changes.")["topic"] == "t"


def test_a_preamble_and_a_trailing_remark_together():
    assert _roundtrip(
        f"Sure — here it is.\n{DOC}\nHappy to revise.")["topic"] == "t"


def test_nested_braces_survive_the_outermost_scan():
    doc = ('{"a": {"b": {"c": 1}}, "list": [{"d": 2}]}')
    assert _roundtrip(f"note\n{doc}\nend")["a"]["b"]["c"] == 1


def test_a_fence_wins_over_stray_braces_in_the_prose():
    """A preamble that itself mentions braces must not confuse the scan when a
    real fenced block is present."""
    raw = f"I considered {{other shapes}} first.\n```json\n{DOC}\n```"
    assert _roundtrip(raw)["topic"] == "t"


def test_a_reply_with_no_object_still_fails_at_the_caller():
    """This helper must not invent success. A refusal or an empty reply has to
    surface, not be smoothed into something parseable."""
    with pytest.raises(Exception):
        _roundtrip("I cannot produce that plan.")


def test_the_structured_call_uses_the_helper():
    import inspect

    from omnicast.llm.claude_cli import ClaudeCLIClient

    src = inspect.getsource(ClaudeCLIClient.complete_structured)
    assert "extract_json(" in src
