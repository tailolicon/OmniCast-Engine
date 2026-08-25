"""Text conditioning: what reaches the voice, and how long it will take."""

from __future__ import annotations

import pytest

from omnicast.media.tts_normalize import (
    chunk_for_tts,
    count_syllables,
    detect_lang,
    estimate_duration,
    normalize_for_tts,
    split_sentences,
)


class TestNormalize:
    def test_strips_stage_directions(self):
        assert normalize_for_tts("She paused (softly) and left [SFX: door]") == (
            "She paused and left"
        )

    def test_spells_out_symbols(self):
        out = normalize_for_tts("Sales & profit up 30% over 12km")
        assert "&" not in out and "%" not in out
        assert "and" in out and "percent" in out and "kilometers" in out

    def test_drops_emoji_keeps_currency(self):
        assert normalize_for_tts("Costs $5 🎉 today") == "Costs $5 today"

    def test_keeps_vietnamese_diacritics(self):
        text = "Chào bạn, hôm nay trời đẹp quá!"
        assert normalize_for_tts(text) == text

    def test_collapses_punctuation_runs(self):
        assert normalize_for_tts("Wait!!! Really....") == "Wait! Really."

    def test_keeps_doubled_word_but_drops_triples(self):
        # Vietnamese reduplication is meaningful — a triple is a merge artefact.
        assert normalize_for_tts("trời xanh xanh") == "trời xanh xanh"
        assert normalize_for_tts("the the the end") == "the end"

    def test_idempotent(self):
        once = normalize_for_tts("Hi (there) & welcome!!!")
        assert normalize_for_tts(once) == once

    def test_empty_input(self):
        assert normalize_for_tts("") == ""
        assert normalize_for_tts("   ") == ""


class TestSentenceSplit:
    def test_keeps_terminator_with_its_sentence(self):
        assert split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]

    def test_cjk_and_devanagari_terminators(self):
        assert split_sentences("你好。再见！") == ["你好。", "再见！"]
        assert len(split_sentences("नमस्ते। धन्यवाद।")) == 2

    def test_unterminated_tail_survives(self):
        assert split_sentences("Done. Almost") == ["Done.", "Almost"]

    def test_no_punctuation_splits_on_lines(self):
        assert split_sentences("line one\nline two") == ["line one", "line two"]

    def test_decimal_is_not_a_sentence_break(self):
        # No whitespace after the dot, so 3.5 stays whole.
        assert split_sentences("It grew 3.5 percent today.") == [
            "It grew 3.5 percent today."
        ]


class TestChunking:
    def test_short_text_is_one_chunk(self):
        assert chunk_for_tts("Hello there.") == ["Hello there."]

    def test_splits_near_token_budget(self):
        text = " ".join(["word"] * 30 + ["."] * 0) + ". " + " ".join(["other"] * 90) + "."
        chunks = chunk_for_tts(text)
        assert len(chunks) > 1

    def test_runt_tail_merges_back(self):
        sentences = " ".join(f"{'w ' * 30}sentence{i}." for i in range(3)) + " Ok."
        chunks = chunk_for_tts(sentences)
        assert all(len(c.split()) > 3 for c in chunks), chunks

    def test_no_text_lost(self):
        text = "First one here. Second one there. Third and last one."
        assert "".join(chunk_for_tts(text)).replace(" ", "") == text.replace(" ", "")

    def test_empty(self):
        assert chunk_for_tts("") == []


class TestDuration:
    def test_english_syllables(self):
        assert count_syllables("hello world") == 3
        assert count_syllables("cat") == 1
        assert count_syllables("make") == 1  # silent e

    def test_cjk_counts_every_character(self):
        assert count_syllables("你好世界") == 4

    def test_korean_counts_blocks(self):
        assert count_syllables("안녕하세요") == 5

    def test_mixed_script_counts_both_halves(self):
        assert count_syllables("你好 world") == 2 + 1

    def test_cjk_no_longer_underestimated(self):
        """The bug this replaced: word-count made CJK ~10x too short."""
        cjk = "今天天气很好我们一起去公园散步吧"
        old_estimate = len(cjk.split()) * 0.4  # one "word" → 0.4s
        assert estimate_duration(cjk) > old_estimate * 5

    def test_english_estimate_is_plausible(self):
        # ~14 syllables of speech sits in the 2.5–4.5s band for a normal read.
        seconds = estimate_duration(
            "The quick brown fox jumps over the lazy dog today."
        )
        assert 2.0 < seconds < 5.0

    def test_punctuation_adds_pause(self):
        assert estimate_duration("one two three.") > estimate_duration("one two three")

    def test_empty_is_zero(self):
        assert estimate_duration("") == 0.0

    @pytest.mark.parametrize(
        "text,expected",
        [("hello", "en"), ("你好", "zh"), ("こんにちは", "ja"), ("안녕", "ko")],
    )
    def test_language_detection(self, text, expected):
        assert detect_lang(text) == expected
