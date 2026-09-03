"""Concurrency and slotting for the dub stage."""

import pytest


def test_network_engines_get_a_pool_and_local_ones_do_not():
    # Measured: a thread pool over VieNeu is 1.14x (the model already fills the
    # CPU), while CapCut/Volcengine calls are mostly waiting on the network.
    from omnicast.reup.tts.pipeline import tts_workers

    assert tts_workers("capcut") > 1
    assert tts_workers("volcengine") > 1
    assert tts_workers("vieneu") == 1
    assert tts_workers("kokoro") == 1


def test_worker_count_is_overridable(monkeypatch):
    from omnicast.reup.tts.pipeline import tts_workers

    monkeypatch.setenv("OMNICAST_REUP_TTS_WORKERS", "9")
    assert tts_workers("vieneu") == 9
    monkeypatch.setenv("OMNICAST_REUP_TTS_WORKERS", "nonsense")
    assert tts_workers("capcut") == 4


def test_network_pool_stays_modest():
    # Edge-TTS has rate-limited this pipeline mid-job even running serially
    # (died at clip 255), so the default must not be aggressive.
    from omnicast.reup.tts.pipeline import tts_workers

    assert tts_workers("edge") <= 4


class _SleepyEngine:
    """Stands in for a network TTS: slow, but not because of the CPU."""

    def __init__(self, delay=0.2):
        self.delay = delay

    def synthesize(self, *, text, output_path, preset):
        import time as _time
        import wave as _wave

        _time.sleep(self.delay)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with _wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(48000)
            handle.writeframes(b"\0\0" * 4800)
        from omnicast.reup.tts.models import SynthesisResult

        return SynthesisResult(
            wav_path=output_path, duration_ms=100, sample_rate=48000, voice_id="stub"
        )


def _pending(tmp_path, preset, count, delay=0.2):
    from omnicast.reup.tts.pipeline import _PendingClip

    engine = _SleepyEngine(delay)
    return [
        _PendingClip(
            slot=i,
            row={"segment_id": f"s{i}", "segment_index": i, "start_ms": i * 100, "end_ms": i * 100 + 90},
            text=f"line {i}",
            engine=engine,
            preset=preset,
            output_path=tmp_path / f"clip{i}" / "clip.wav",
            clip_cache_dir=tmp_path / f"clip{i}",
            clip_manifest_path=tmp_path / f"clip{i}" / "manifest.json",
            clip_hash=f"h{i}",
            speaker_key=None,
        )
        for i in range(count)
    ]


def _ctx():
    from omnicast.reup.core.jobs import CancellationToken, JobContext

    return JobContext(
        job_id="t", logger_name="t",
        cancellation_token=CancellationToken(),
        progress_callback=lambda value, message: None,
    )


def test_pending_clips_land_in_their_own_slots(tmp_path, monkeypatch):
    # Out-of-order completion is the whole point of a pool; if results were
    # appended instead of slotted, the dub would play in finishing order.
    from omnicast.reup.tts.models import VoicePreset
    from omnicast.reup.tts.pipeline import _synthesize_pending

    monkeypatch.setenv("OMNICAST_REUP_TTS_WORKERS", "4")
    preset = VoicePreset(voice_preset_id="p", name="stub", engine="capcut", voice_id="v")
    jobs = _pending(tmp_path, preset, 6, delay=0.05)
    artifacts = [None] * 6
    _synthesize_pending(_ctx(), jobs, artifacts, total=6)
    assert [a.segment_index for a in artifacts] == list(range(6))
    assert all(a.text == f"line {i}" for i, a in enumerate(artifacts))


def test_the_pool_actually_overlaps_calls(tmp_path, monkeypatch):
    import time

    from omnicast.reup.tts.models import VoicePreset
    from omnicast.reup.tts.pipeline import _synthesize_pending

    preset = VoicePreset(voice_preset_id="p", name="stub", engine="capcut", voice_id="v")
    monkeypatch.setenv("OMNICAST_REUP_TTS_WORKERS", "4")
    t0 = time.perf_counter()
    _synthesize_pending(_ctx(), _pending(tmp_path, preset, 8, 0.15), [None] * 8, total=8)
    pooled = time.perf_counter() - t0
    # Serial would be 8 x 0.15 = 1.2s; four at a time should be near half that.
    assert pooled < 0.9, f"pool took {pooled:.2f}s — calls are not overlapping"


def test_a_failing_clip_surfaces_instead_of_leaving_a_hole(tmp_path, monkeypatch):
    from omnicast.reup.tts.models import VoicePreset
    from omnicast.reup.tts.pipeline import _synthesize_pending

    monkeypatch.setenv("OMNICAST_REUP_TTS_WORKERS", "3")
    preset = VoicePreset(voice_preset_id="p", name="stub", engine="capcut", voice_id="v")
    jobs = _pending(tmp_path, preset, 4, 0.01)

    class _Boom:
        def synthesize(self, **kwargs):
            raise RuntimeError("provider said no")

    jobs[2].engine = _Boom()
    with pytest.raises(RuntimeError, match="provider said no"):
        _synthesize_pending(_ctx(), jobs, [None] * 4, total=4)
