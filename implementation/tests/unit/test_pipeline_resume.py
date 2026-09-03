"""Regression tests for resuming a rejected Writer artifact."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from omnicast.agents.writer import WriterAgent
from omnicast.pipeline.steps import _load_resume_draft


def _make_product(root, *, channel: str, topic: str):
    product = root / channel / "20260728_1901_example"
    variants = product / "variants"
    variants.mkdir(parents=True)
    (product / "meta.json").write_text(
        json.dumps({"channel": channel, "topic": topic}),
        encoding="utf-8",
    )
    raw = (
        "HOOK:\nSCENES:\n"
        '[{"vo":"A verified opening.","visual":"SSA page","sfx":null}]\n'
        "SEGMENT 1 — THE MECHANISM:\nSCENES:\n"
        '[{"vo":"The segment survives current parsing.",'
        '"visual":"rule diagram","sfx":null}]\n'
        "OUTRO:\nSCENES:\n"
        '[{"vo":"Use the sharper mental model.",'
        '"visual":"end card","sfx":null}]\n'
    )
    raw_path = variants / "variant_claude_score34.raw.txt"
    raw_path.write_text(raw, encoding="utf-8")
    (variants / "variant_claude_score34.json").write_text(
        json.dumps({
            "variant_id": "claude",
            "editorial_angle": {"thesis": "Withholding is not disappearance"},
        }),
        encoding="utf-8",
    )
    return product


def test_resume_reparses_raw_variant_with_current_parser(tmp_path):
    channel = "senior_wealth_us"
    topic = "What happens to a withheld benefit later"
    product = _make_product(tmp_path, channel=channel, topic=topic)
    writer = WriterAgent(llm=AsyncMock())

    draft, raw_path = _load_resume_draft(
        writer,
        str(product),
        products_root=tmp_path / channel,
        channel_id=channel,
        topic=topic,
    )

    assert raw_path.name.endswith(".raw.txt")
    assert [segment.heading for segment in draft.segments] == ["THE MECHANISM"]
    assert draft.editorial_angle["thesis"] == "Withholding is not disappearance"


def test_resume_rejects_paths_outside_channel_products(tmp_path):
    channel = "senior_wealth_us"
    topic = "What happens to a withheld benefit later"
    outside = _make_product(tmp_path / "outside", channel=channel, topic=topic)
    writer = WriterAgent(llm=AsyncMock())

    with pytest.raises(ValueError, match="must stay inside"):
        _load_resume_draft(
            writer,
            str(outside),
            products_root=tmp_path / "products" / channel,
            channel_id=channel,
            topic=topic,
        )

