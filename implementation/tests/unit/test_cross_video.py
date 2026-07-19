"""Cross-video repetition guard tests."""
import tempfile
from pathlib import Path

from omnicast.agents import cross_video as xv


def test_fingerprint_extracts_recurring_names_and_motifs():
    # names must appear MID-sentence (preceded by lowercase) to count as proper nouns
    text = ("I worked the graveyard shift. I asked Denise about the logbook, and "
            "later Denise warned me. The figure was tall and standing perfectly still.")
    fp = xv.fingerprint(text)
    assert "Denise" in fp["names"]          # recurs mid-sentence → captured
    assert "I" not in fp["names"]           # stopword
    assert "graveyard shift" in fp["motifs"]
    assert "tall and still" in fp["motifs"]
    assert "old logbook" in fp["motifs"]


def test_reuse_flagged_across_videos():
    with tempfile.TemporaryDirectory() as d:
        store = Path(d) / "fp.json"
        ch = "true_dread_files_us"
        # 3 prior videos all used the tall-still motif + name Biscuit (mid-sentence)
        for _ in range(3):
            xv.check_and_record(ch, "I had a dog named Biscuit. The thing was tall and standing perfectly still, and Biscuit ran.", store)
        flags = xv.check_and_record(
            ch, "There was Biscuit again. Something tall and completely still watched, and Biscuit whined.", store)
        joined = " ".join(flags)
        assert "Biscuit" in joined                 # reused name flagged
        assert "tall and still" in joined          # over-used motif flagged


def test_no_flags_on_first_video():
    with tempfile.TemporaryDirectory() as d:
        store = Path(d) / "fp.json"
        assert xv.check_and_record("ch", "A fresh story with Marcus and a payphone.", store) == []
