"""Small tolerant JSON extractor for structured LLM responses."""

from __future__ import annotations

import json
import re


def parse_json_payload(text: str):
    """Parse a JSON value, tolerating fences or a short model preamble/trailer.

    Every structured schema in this codebase is a JSON OBJECT, so when the
    response mixes several JSON values the first decodable OBJECT wins — a
    stray array in a preamble (observed live: ["story_1", ...] emitted before
    the review object) must never shadow the payload that follows it."""
    content = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content, re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as first_error:
        decoder = json.JSONDecoder()
        values = []
        index = 0
        while index < len(content):
            starts = [
                pos for pos in (content.find("{", index), content.find("[", index))
                if pos >= 0
            ]
            if not starts:
                break
            start = min(starts)
            try:
                value, end = decoder.raw_decode(content[start:])
            except json.JSONDecodeError:
                index = start + 1
                continue
            if isinstance(value, dict):
                return value
            values.append(value)
            index = start + end
        if values:
            return values[0]
        raise first_error
