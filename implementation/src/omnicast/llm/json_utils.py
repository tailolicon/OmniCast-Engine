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


def coerce_object_schema_payload(payload, output_schema: type):
    """Recover the narrow object-as-root-list error seen from JSON judges.

    DeepSeek occasionally emits the requested ``dimensions`` array as the
    entire response, dropping the enclosing CriticFeedback object.  The scores
    are still complete and CriticAgent independently recomputes/caps every
    subtotal, so wrapping that one recognisable shape is safer than discarding
    a full pipeline run. Other root lists remain untouched and fail validation.
    """
    fields = getattr(output_schema, "model_fields", {})
    if (
        isinstance(payload, list)
        and payload
        and {"dimensions", "total_score"}.issubset(fields)
        and all(
            isinstance(item, dict)
            and "name" in item
            and "score" in item
            for item in payload
        )
    ):
        total = sum(
            max(0, int(item.get("score", 0) or 0))
            for item in payload
        )
        return {
            "total_score": min(total, 100),
            "dimensions": payload,
            "approved": False,
            "rejection_reasons": [
                "Judge returned dimensions without its outer object; "
                "scores were recovered and canonical gates re-applied."
            ],
        }
    return payload
