from __future__ import annotations

import pytest

from omnicast.media.visual_match_runner import run_visual_match_qc


@pytest.mark.asyncio
async def test_visual_qc_does_not_spawn_when_channel_does_not_require_it(
    tmp_path, monkeypatch
):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("visual QC must be opt-in per channel")

    monkeypatch.setattr(
        "omnicast.media.visual_match_runner.asyncio.create_subprocess_exec",
        forbidden,
    )
    result = await run_visual_match_qc(
        tmp_path, tmp_path / "video.mp4", {}, tmp_path / "visual_match_qc.py")
    assert result == {"required": False, "ran": False}


@pytest.mark.asyncio
async def test_required_visual_qc_runs_before_release_and_must_validate(
    tmp_path, monkeypatch
):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"render")
    script = tmp_path / "visual_match_qc.py"
    script.write_text("# qc", encoding="utf-8")
    calls = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"visual match complete", b""

    async def fake_spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setattr(
        "omnicast.media.visual_match_runner.asyncio.create_subprocess_exec",
        fake_spawn,
    )
    monkeypatch.setattr(
        "omnicast.media.visual_match_runner.OutputQualityAuditor.inspect_visual_match",
        lambda *_args, **_kwargs: {"required": True, "passed": True},
    )

    result = await run_visual_match_qc(
        tmp_path,
        video,
        {"visual_match_qc_required": True, "visual_match_qc_threshold": 6},
        script,
    )

    assert result["ran"] is True
    assert result["passed"] is True
    argv = calls[0][0]
    assert str(script) in argv
    assert "--threshold" in argv
    assert "6" in argv


@pytest.mark.asyncio
async def test_required_visual_qc_fails_closed_on_weak_frames(
    tmp_path, monkeypatch
):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"render")
    script = tmp_path / "visual_match_qc.py"
    script.write_text("# qc", encoding="utf-8")

    class Process:
        returncode = 1

        async def communicate(self):
            return b"avg 4.2", b""

    async def fake_spawn(*_args, **_kwargs):
        return Process()

    monkeypatch.setattr(
        "omnicast.media.visual_match_runner.asyncio.create_subprocess_exec",
        fake_spawn,
    )
    with pytest.raises(RuntimeError, match="visual match QC failed"):
        await run_visual_match_qc(
            tmp_path,
            video,
            {"visual_match_qc_required": True},
            script,
        )


def test_frame_timeline_uses_rendered_clip_durations_not_word_totals(
    tmp_path, monkeypatch
):
    """Pauses/padding live in scene_NN.mp4, not the word sidecar. Summing word
    durations creates cumulative drift and makes QC judge the wrong shot."""
    import json
    import visual_match_qc as vmq

    assets = tmp_path / "_assets"
    assets.mkdir()
    for idx in (0, 1):
        (assets / f"scene_{idx:02d}.mp4").write_bytes(b"clip")
        (assets / f"scene_{idx:02d}.words.json").write_text(
            json.dumps([
                {"start": 0.2, "end": 0.8, "text": "one"},
                {"start": 0.8, "end": 2.0, "text": "two"},
            ]),
            encoding="utf-8",
        )
    durations = {"scene_00.mp4": 5.0, "scene_01.mp4": 4.0}
    monkeypatch.setattr(
        vmq, "_probe_clip_duration", lambda p: durations[p.name])

    shots = vmq._shot_timeline(tmp_path)

    assert shots[0]["start"] == 0.0
    assert shots[1]["start"] == 5.0
    assert shots[1]["mid"] == pytest.approx(6.1)
    assert shots[-1]["timeline_end"] == 9.0
