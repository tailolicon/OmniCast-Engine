"""Every structured schema in this codebase is a JSON OBJECT; a stray array in
the model's preamble must never win over the review object that follows it
(observed live 2026-07-17: DeepSeek emitted ["story_1","story_2","story_3"]
before the FinalCompilationReview object and blocked a 92/100 compilation)."""

from __future__ import annotations

import pytest

from omnicast.llm.json_utils import parse_json_payload


def test_plain_object_parses():
    assert parse_json_payload('{"approved": true}') == {"approved": True}


def test_fenced_object_parses():
    assert parse_json_payload('```json\n{"a": 1}\n```') == {"a": 1}


def test_stray_array_before_the_object_does_not_win():
    text = '["story_1", "story_2", "story_3"]\n{"approved": false, "summary": "s"}'
    assert parse_json_payload(text) == {"approved": False, "summary": "s"}


def test_prose_preamble_then_object():
    text = 'Here is my review as requested.\n{"approved": true, "issues": []}'
    assert parse_json_payload(text) == {"approved": True, "issues": []}


def test_object_then_trailing_prose_and_array():
    text = '{"approved": true} That covers stories ["story_1"].'
    assert parse_json_payload(text) == {"approved": True}


def test_array_only_payload_still_returns_the_array():
    # Nothing object-shaped to salvage — the schema validator rejects it and
    # the caller's contract retry handles the rest.
    assert parse_json_payload('[1, 2, 3]') == [1, 2, 3]


def test_no_json_at_all_raises():
    with pytest.raises(Exception):
        parse_json_payload("no json here at all")
