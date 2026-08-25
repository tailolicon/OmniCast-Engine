"""TTS padding must not be counted as speech."""

import math
import struct
import wave

from omnicast.reup.audio.trim_silence import trim_silence


def _wav(path, *, lead_ms=0, speech_ms=500, tail_ms=0, rate=16000):
    frames = bytearray()
    for _ in range(int(rate * lead_ms / 1000)):
        frames += struct.pack("<h", 0)
    for i in range(int(rate * speech_ms / 1000)):
        frames += struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * i / rate)))
    for _ in range(int(rate * tail_ms / 1000)):
        frames += struct.pack("<h", 0)
    with wave.open(str(path), "wb") as h:
        h.setnchannels(1); h.setsampwidth(2); h.setframerate(rate)
        h.writeframes(bytes(frames))
    return path


def _duration_ms(path):
    with wave.open(str(path), "rb") as h:
        return int(h.getnframes() / h.getframerate() * 1000)


def test_padding_at_both_ends_is_removed(tmp_path):
    # An engine that pads 600ms front and back turns a 500ms line into 1.7s;
    # the planner then treats all of it as speech and speeds the line up to
    # make room for silence.
    clip = _wav(tmp_path / "a.wav", lead_ms=600, speech_ms=500, tail_ms=600)
    assert _duration_ms(clip) == 1700
    new_ms = trim_silence(clip)
    assert new_ms < 1100, f"still {new_ms}ms of padding"
    assert new_ms >= 500, "the speech itself must survive"


def test_the_tail_keeps_more_room_than_the_head(tmp_path):
    # Trailing vowels ring on; pyvideotrans keeps 80ms head vs 200ms tail.
    clip = _wav(tmp_path / "b.wav", lead_ms=800, speech_ms=400, tail_ms=800)
    trim_silence(clip)
    assert 600 <= _duration_ms(clip) <= 800


def test_a_clip_with_no_padding_is_left_alone(tmp_path):
    clip = _wav(tmp_path / "c.wav", speech_ms=700)
    before = _duration_ms(clip)
    trim_silence(clip)
    assert _duration_ms(clip) == before


def test_a_silent_clip_is_never_shortened_to_nothing(tmp_path):
    # It is still holding a slot; collapsing it would shift every later line.
    clip = _wav(tmp_path / "d.wav", lead_ms=400, speech_ms=0, tail_ms=400)
    before = _duration_ms(clip)
    assert trim_silence(clip) == 0
    assert _duration_ms(clip) == before


def test_a_corrupt_file_is_reported_not_raised(tmp_path):
    bad = tmp_path / "e.wav"
    bad.write_bytes(b"not a wav at all")
    assert trim_silence(bad) == 0
    assert bad.read_bytes() == b"not a wav at all"


def test_stereo_clips_survive_the_round_trip(tmp_path):
    path = tmp_path / "f.wav"
    rate = 16000
    frames = bytearray()
    for _ in range(int(rate * 0.4)):
        frames += struct.pack("<hh", 0, 0)
    for i in range(int(rate * 0.5)):
        v = int(12000 * math.sin(2 * math.pi * 220 * i / rate))
        frames += struct.pack("<hh", v, v)
    with wave.open(str(path), "wb") as h:
        h.setnchannels(2); h.setsampwidth(2); h.setframerate(rate)
        h.writeframes(bytes(frames))
    trim_silence(path)
    with wave.open(str(path), "rb") as h:
        assert h.getnchannels() == 2 and h.getframerate() == rate
