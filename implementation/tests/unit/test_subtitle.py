"""Caption packing and the source ladder — including the refusal to fake it."""

from __future__ import annotations

import json

import pytest

from omnicast.media.models import SubtitleRequest
from omnicast.media.subtitle import SubtitleModule, pack_captions
from omnicast.shared.errors import MediaError


def _words(pairs, step=0.5):
    """Build word timings from (text, start) pairs with a fixed duration."""
    return [{"start": s, "end": s + step, "text": t} for t, s in pairs]


class TestPackCaptions:
    def test_packs_words_into_a_cue(self):
        cues = pack_captions(_words([("Hello", 0.0), ("there", 0.6)]))
        assert len(cues) == 1
        assert cues[0]["text"] == "Hello there"
        assert cues[0]["start"] == 0.0

    def test_breaks_on_line_width(self):
        words = _words([(f"word{i}", i * 0.5) for i in range(12)])
        cues = pack_captions(words, max_line_chars=20)
        assert len(cues) > 1
        assert all(len(c["text"]) <= 20 for c in cues)

    def test_breaks_after_sentence_terminator(self):
        words = _words([("Done.", 0.0), ("Next", 0.6), ("line", 1.2)])
        cues = pack_captions(words, min_cue_seconds=0.0)
        assert cues[0]["text"] == "Done."

    def test_breaks_on_long_silence(self):
        words = [
            {"start": 0.0, "end": 0.5, "text": "before"},
            {"start": 4.0, "end": 4.5, "text": "after"},
        ]
        cues = pack_captions(words, gap_split_seconds=0.7, min_cue_seconds=0.0)
        assert len(cues) == 2

    def test_cue_never_outstays_max_seconds(self):
        words = [{"start": i * 1.0, "end": i * 1.0 + 0.9, "text": "a"} for i in range(12)]
        cues = pack_captions(words, max_cue_seconds=4.0, max_line_chars=999)
        assert all(c["end"] - c["start"] <= 4.5 for c in cues)

    def test_flash_cue_merges_forward(self):
        words = [
            {"start": 0.0, "end": 2.0, "text": "Long enough here."},
            {"start": 2.0, "end": 2.2, "text": "Hi."},
        ]
        cues = pack_captions(words, min_cue_seconds=1.0, max_line_chars=999)
        assert len(cues) == 1
        assert cues[0]["text"].endswith("Hi.")

    def test_cjk_defaults_to_narrow_lines(self):
        # 9 + 9 characters: fits the 40-char latin budget, breaks the 15-char
        # CJK one, so the script-aware default is what decides here.
        words = _words([("你好世界很好天气晴", 0.0), ("今天天气不错真好啊", 0.6)])
        cues = pack_captions(words, min_cue_seconds=0.0)
        assert len(cues) == 2

    def test_cjk_joins_without_spaces(self):
        cues = pack_captions(_words([("你好", 0.0), ("世界", 0.6)]), min_cue_seconds=0.0)
        assert cues[0]["text"] == "你好世界"

    def test_hard_char_cap_respected(self):
        words = _words([("x" * 60, i * 0.5) for i in range(6)])
        cues = pack_captions(words, max_line_chars=999, hard_cue_chars=150)
        assert all(len(c["text"]) <= 150 for c in cues)

    def test_empty_input(self):
        assert pack_captions([]) == []


class TestSourceLadder:
    @pytest.mark.asyncio
    async def test_prefers_word_sidecar(self, tmp_path):
        audio = tmp_path / "vo.wav"
        audio.write_bytes(b"RIFF")
        audio.with_suffix(".words.json").write_text(
            json.dumps(_words([("Real", 0.0), ("timings", 0.6)])), encoding="utf-8"
        )
        out = tmp_path / "vo.srt"

        result = await SubtitleModule()._process(
            SubtitleRequest(audio_path=str(audio), output_path=str(out))
        )

        assert result.timing_source == "word_boundaries"
        assert "Real timings" in out.read_text(encoding="utf-8")
        assert "Hello world" not in out.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_refuses_to_invent_captions(self, tmp_path):
        """No sidecar, no WhisperX, no script → raise, never a placeholder."""
        audio = tmp_path / "silent.wav"
        audio.write_bytes(b"RIFF")

        with pytest.raises(MediaError, match="No caption timings"):
            await SubtitleModule()._process(
                SubtitleRequest(audio_path=str(audio),
                                output_path=str(tmp_path / "x.srt"))
            )

    @pytest.mark.asyncio
    async def test_corrupt_sidecar_falls_through(self, tmp_path):
        audio = tmp_path / "vo.wav"
        audio.write_bytes(b"RIFF")
        audio.with_suffix(".words.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(MediaError):
            await SubtitleModule()._process(
                SubtitleRequest(audio_path=str(audio),
                                output_path=str(tmp_path / "x.srt"))
            )

    @pytest.mark.asyncio
    async def test_non_monotonic_sidecar_rejected(self, tmp_path):
        audio = tmp_path / "vo.wav"
        audio.write_bytes(b"RIFF")
        audio.with_suffix(".words.json").write_text(
            json.dumps([
                {"start": 5.0, "end": 5.5, "text": "late"},
                {"start": 0.0, "end": 0.5, "text": "early"},
            ]), encoding="utf-8",
        )

        with pytest.raises(MediaError):
            await SubtitleModule()._process(
                SubtitleRequest(audio_path=str(audio),
                                output_path=str(tmp_path / "x.srt"))
            )


class TestSrtFormat:
    def test_timestamp_format(self):
        assert SubtitleModule._format_time(3661.5) == "01:01:01,500"
        assert SubtitleModule._format_time(0.0) == "00:00:00,000"

    def test_millisecond_rounding_carries(self):
        assert SubtitleModule._format_time(1.9999) == "00:00:02,000"

    def test_srt_structure(self, tmp_path):
        out = tmp_path / "a.srt"
        count = SubtitleModule()._write_srt(
            [{"start": 0.0, "end": 1.0, "text": "two words"}], str(out)
        )
        body = out.read_text(encoding="utf-8")
        assert body.startswith("1\n00:00:00,000 --> 00:00:01,000\ntwo words")
        assert count == 2
