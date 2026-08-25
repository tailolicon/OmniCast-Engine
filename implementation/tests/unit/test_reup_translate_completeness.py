"""A partial translation must stop the job, not travel four stages downstream."""

import re


def _row(index, *, translated):
    """Mirrors the real schema: subtitle/tts are seeded with the source at ASR
    time, so they are never empty. Only `translated_text` tells the truth."""
    source = "那一年我刚从医学院毕业"
    return {
        "segment_index": index,
        "source_text": source,
        "translated_text": "Nam do toi vua tot nghiep" if translated else "",
        "subtitle_text": "Nam do toi vua tot nghiep" if translated else source,
        "tts_text": "Nam do toi vua tot nghiep" if translated else source,
    }


def _untranslated(rows):
    """The check the runner performs after the translate stage."""
    return [int(r["segment_index"]) for r in rows if not str(r["translated_text"] or "").strip()]


def test_a_tail_of_untranslated_lines_is_detected():
    # The observed shape: 554-718 of 719 never translated after a session-limit
    # kill, restored from cache on resume as though complete.
    rows = [_row(i, translated=i < 554) for i in range(719)]
    missing = _untranslated(rows)
    assert len(missing) == 165
    assert missing[0] == 554 and missing[-1] == 718


def test_seeded_source_text_does_not_look_translated():
    # This is why the check cannot use subtitle_text: it is never empty, it
    # just still holds Chinese.
    row = _row(0, translated=False)
    assert row["subtitle_text"] == row["source_text"]
    assert row["subtitle_text"], "non-empty, so an emptiness check on it finds nothing"
    assert _untranslated([row]) == [0]


def test_a_complete_translation_passes():
    rows = [_row(i, translated=True) for i in range(50)]
    assert _untranslated(rows) == []


def test_whitespace_only_counts_as_untranslated():
    row = _row(7, translated=True)
    row["translated_text"] = "   \n "
    assert _untranslated([row]) == [7]


def test_no_vietnamese_output_still_carries_han_characters():
    # Sanity on the fixture itself: the untranslated rows really are Chinese,
    # which is what reached a Vietnamese TTS engine and killed it.
    han = re.compile(r"[一-鿿]")
    assert han.search(_row(0, translated=False)["tts_text"])
    assert not han.search(_row(0, translated=True)["tts_text"])
