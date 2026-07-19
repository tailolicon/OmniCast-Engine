"""Pure helpers added to qa_check by the Orkas-VideoStudio port:
blank-frame heuristic, freezedetect parsing, motion-ratio delivery guard."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # implementation/

from qa_check import assess_motion, freeze_spans_from_stderr, is_blank_frame


# ── is_blank_frame ────────────────────────────────────────────────────────────

def test_blank_near_black():
    assert is_blank_frame({"brightness": 1.2, "contrast": 30.0})


def test_blank_near_white():
    assert is_blank_frame({"brightness": 253.0, "contrast": 30.0})


def test_blank_flat_gray():
    assert is_blank_frame({"brightness": 128.0, "contrast": 0.5})


def test_normal_frame_not_blank():
    assert not is_blank_frame({"brightness": 120.0, "contrast": 80.0})


def test_missing_stats_is_blank():
    assert is_blank_frame(None)


# ── freeze_spans_from_stderr ──────────────────────────────────────────────────

_FFMPEG_FREEZE_LOG = """
[freezedetect @ 0x55] lavfi.freezedetect.freeze_start: 12.5
[freezedetect @ 0x55] lavfi.freezedetect.freeze_duration: 9.25
[freezedetect @ 0x55] lavfi.freezedetect.freeze_end: 21.75
frame= 1000 fps=250 q=-0.0 size=N/A
[freezedetect @ 0x55] lavfi.freezedetect.freeze_start: 100.0
"""


def test_freeze_parse_pairs_and_eof_run():
    spans = freeze_spans_from_stderr(_FFMPEG_FREEZE_LOG)
    assert spans == [(12.5, 9.25), (100.0, -1.0)]  # -1 = runs to EOF


def test_freeze_parse_clean_log():
    assert freeze_spans_from_stderr("frame= 500 fps=100 ...") == []


# ── assess_motion ─────────────────────────────────────────────────────────────

def test_motion_report_only_always_passes():
    m = assess_motion(0.0, 300.0, min_ratio=0.0)
    assert m["pass"] and m["motion_ratio"] == 0.0


def test_motion_floor_pass():
    m = assess_motion(120.0, 300.0, min_ratio=0.3)  # 40% >= 30%
    assert m["pass"]


def test_motion_floor_fail_borderline():
    m = assess_motion(75.0, 300.0, min_ratio=0.3)  # 25%, within 10pt of floor
    assert not m["pass"] and m["borderline"]


def test_motion_floor_fail_hard():
    m = assess_motion(30.0, 300.0, min_ratio=0.3)  # 10%, a slideshow
    assert not m["pass"] and not m["borderline"]


def test_motion_zero_duration_safe():
    m = assess_motion(10.0, 0.0, min_ratio=0.3)
    assert m["motion_ratio"] == 0.0
