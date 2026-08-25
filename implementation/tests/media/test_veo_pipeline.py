"""Tests for omnicast.media.veo_pipeline — pure helpers + fallback behaviour.

No network, no browser, no ffmpeg: providers are fakes injected into the
pipeline's cache, and carry-forward is disabled (its ffmpeg step is exercised
separately and is non-fatal by design)."""

from __future__ import annotations

from pathlib import Path

import pytest

from omnicast.media.veo_pipeline import (
    VeoClipSpec,
    VeoScenePipeline,
    build_motion_prompt,
    clamp_duration,
    preflight_duration,
)


# ── pure helpers ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seconds,expected", [
    (0.5, 4), (4.0, 4), (4.1, 6), (6.0, 6), (7.9, 8), (8.0, 8), (30.0, 8),
])
def test_clamp_duration(seconds, expected):
    assert clamp_duration(seconds) == expected


def test_preflight_duration_reference_image_forces_8s():
    assert preflight_duration(4, has_image=True) == 8


def test_preflight_duration_high_res_forces_8s():
    assert preflight_duration(6, has_image=False, resolution="1080p") == 8


def test_preflight_duration_repairs_illegal_value():
    assert preflight_duration(5, has_image=False) == 6


def test_build_motion_prompt_appends_negative_tail():
    text = build_motion_prompt("Slow pan across a kitchen table.", seeded=False)
    assert text.startswith("Slow pan across a kitchen table.")
    assert "watermark" in text


def test_build_motion_prompt_seeded_empty_gets_default_motion():
    text = build_motion_prompt("", seeded=True)
    assert "motion" in text.lower()


# ── fallback behaviour with fake providers ────────────────────────────────────

class _FakeProvider:
    def __init__(self, fail_message: str = "", accepts_wait_s: bool = False):
        self.fail_message = fail_message
        self.accepts_wait_s = accepts_wait_s
        self.calls: list[dict] = []

    async def convert(self, image_path, prompt, *, duration, output_path, **kw):
        self.calls.append(dict(image=image_path, prompt=prompt,
                               duration=duration, out=output_path, **kw))
        if self.fail_message:
            raise RuntimeError(self.fail_message)
        Path(output_path).write_bytes(b"clip")
        return output_path

    def close(self):
        pass


def _pipeline(tmp_path, providers: dict) -> VeoScenePipeline:
    p = VeoScenePipeline(
        provider_order=tuple(providers), carry_forward=False,
        work_dir=tmp_path)
    p._providers.update(providers)   # bypass the registry
    return p


@pytest.mark.asyncio
async def test_flow_success_never_touches_fallback(tmp_path):
    flow, gemini = _FakeProvider(), _FakeProvider()
    pipe = _pipeline(tmp_path, {"flow": flow, "gemini": gemini})
    report = await pipe.generate(
        [VeoClipSpec(index=0, motion_prompt="pan"),
         VeoClipSpec(index=1, motion_prompt="tilt")])
    assert report.ok_count == 2
    assert report.by_provider() == {"flow": 2}
    assert gemini.calls == []


@pytest.mark.asyncio
async def test_credit_failure_demotes_flow_for_rest_of_run(tmp_path):
    flow = _FakeProvider(fail_message="Flow credit balance exhausted")
    gemini = _FakeProvider()
    pipe = _pipeline(tmp_path, {"flow": flow, "gemini": gemini})
    report = await pipe.generate(
        [VeoClipSpec(index=i, motion_prompt="pan") for i in range(3)])
    assert report.ok_count == 3
    assert report.by_provider() == {"gemini": 3}
    assert report.demoted_from == "flow"
    # Sticky: flow was tried exactly once, not once per clip.
    assert len(flow.calls) == 1


@pytest.mark.asyncio
async def test_transient_failure_keeps_provider_in_rotation(tmp_path):
    flow = _FakeProvider(fail_message="timeout waiting for selector")
    gemini = _FakeProvider()
    pipe = _pipeline(tmp_path, {"flow": flow, "gemini": gemini})
    report = await pipe.generate(
        [VeoClipSpec(index=i, motion_prompt="pan") for i in range(2)])
    assert report.ok_count == 2
    assert report.by_provider() == {"gemini": 2}
    assert report.demoted_from == ""
    # Non-sticky: flow got a fresh chance on every clip.
    assert len(flow.calls) == 2


@pytest.mark.asyncio
async def test_all_providers_dead_stops_early(tmp_path):
    flow = _FakeProvider(fail_message="FlowBlocked: login required")
    gemini = _FakeProvider(fail_message="GOOGLE_API_KEY not configured")
    pipe = _pipeline(tmp_path, {"flow": flow, "gemini": gemini})
    report = await pipe.generate(
        [VeoClipSpec(index=i, motion_prompt="pan") for i in range(5)])
    assert report.ok_count == 0
    # Both demoted on clip 0 -> loop stops instead of failing 5 times.
    assert len(report.clips) == 1
    assert len(flow.calls) == 1 and len(gemini.calls) == 1


@pytest.mark.asyncio
async def test_flow_gets_wait_s_but_no_image(tmp_path):
    flow = _FakeProvider()
    pipe = _pipeline(tmp_path, {"flow": flow})
    await pipe.generate(
        [VeoClipSpec(index=0, motion_prompt="pan", seed_image="seed.jpg")])
    call = flow.calls[0]
    assert call["wait_s"] == 600
    # FlowProvider ignores image_path today; the pipeline must not pretend
    # a seed was applied (duration would silently jump to 8s).
    assert call["image"] == ""
