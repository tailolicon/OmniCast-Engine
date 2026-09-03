"""One line an engine cannot read must not take the whole dub with it."""

import math
import struct
import wave

import pytest

from omnicast.reup.tts import pipeline as p
from omnicast.reup.tts.models import SynthesisResult, VoicePreset


def _write(path, ms=300, rate=16000):
    frames = bytearray()
    for i in range(int(rate * ms / 1000)):
        frames += struct.pack("<h", int(9000 * math.sin(2 * math.pi * 200 * i / rate)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


class _ChokesOnLongText:
    """Mirrors the real failure: VieNeu died on a 508-character line."""

    def __init__(self, limit=220):
        self.limit = limit
        self.seen = []

    def synthesize(self, *, text, output_path, preset):
        self.seen.append(text)
        if len(text) > self.limit:
            raise RuntimeError("VieNeu synth that bai, khong tao duoc wav output.")
        _write(output_path)
        return SynthesisResult(
            wav_path=output_path, duration_ms=300, sample_rate=16000, voice_id="v"
        )


def _job(tmp_path, text, engine):
    return p._PendingClip(
        slot=0,
        row={"segment_id": "s", "segment_index": 0, "start_ms": 0, "end_ms": 1},
        text=text,
        engine=engine,
        preset=VoicePreset(voice_preset_id="p", name="n", engine="vieneu", voice_id="v"),
        output_path=tmp_path / "clip.wav",
        clip_cache_dir=tmp_path,
        clip_manifest_path=tmp_path / "m.json",
        clip_hash="h",
        speaker_key=None,
    )


def test_a_line_too_long_is_split_and_still_spoken(tmp_path):
    # 547 of 719 clips were already rendered when one long line killed the run.
    engine = _ChokesOnLongText()
    long_line = " ".join(["Cau nay kha dai va co dau cham."] * 12)
    result = p._synthesize_resilient(_job(tmp_path, long_line, engine))
    assert result.duration_ms > 300, "pieces must be joined, not just the first"
    assert (tmp_path / "clip.wav").exists()
    assert not list(tmp_path.glob("*.part*.wav")), "temp pieces cleaned up"


def test_a_short_line_takes_the_direct_path(tmp_path):
    engine = _ChokesOnLongText()
    p._synthesize_resilient(_job(tmp_path, "Yen tam.", engine))
    assert engine.seen == ["Yen tam."], "no splitting when nothing went wrong"


def test_an_unsplittable_failure_still_raises(tmp_path):
    # A single sentence the engine simply cannot say is a real error; hiding it
    # behind silence would ship a video with a hole in the dialogue.
    class _AlwaysFails:
        def synthesize(self, **kwargs):
            raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        p._synthesize_resilient(_job(tmp_path, "Mot cau duy nhat", _AlwaysFails()))


def test_partial_success_keeps_what_was_spoken(tmp_path):
    class _FailsOnePiece:
        def __init__(self):
            self.calls = 0

        def synthesize(self, *, text, output_path, preset):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("whole line too long")
            if "hong" in text:
                raise RuntimeError("bad piece")
            _write(output_path)
            return SynthesisResult(
                wav_path=output_path, duration_ms=300, sample_rate=16000, voice_id="v"
            )

    text = "Cau dau tien on. Cau nay hong nhe. Cau thu ba cung on."
    result = p._synthesize_resilient(_job(tmp_path, text, _FailsOnePiece()))
    assert result.duration_ms >= 600, "the two good sentences survive"
