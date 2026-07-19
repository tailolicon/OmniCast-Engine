"""Quota-aware batch loop: a run killed by the subscription window boundary is
retried after the window resets instead of dying while nobody is awake."""

from __future__ import annotations

import datetime
import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "run_seq_batch",
    pathlib.Path(__file__).resolve().parents[2] / "scripts" / "run_seq_batch.py",
)
seq = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seq)


def _now(h: int, m: int) -> datetime.datetime:
    return datetime.datetime(2026, 7, 18, h, m, 0)


def test_parses_pm_reset_later_today():
    text = "claude -p failed deterministically: You've hit your session limit � resets 6:20pm (Asia/Saigon)"
    wait = seq.seconds_until_reset(text, _now(15, 0))
    # 15:00 -> 18:20 = 200 min, plus the 5-minute cushion.
    assert wait == 200 * 60 + 300


def test_reset_time_already_past_rolls_to_tomorrow():
    text = "session limit · resets 5:40am (Asia/Saigon)"
    wait = seq.seconds_until_reset(text, _now(9, 0))
    assert wait == (20 * 60 + 40) * 60 + 300  # 09:00 -> 05:40 next day


def test_midnight_and_noon_edge_cases():
    assert seq.seconds_until_reset("session limit resets 12:30am x", _now(23, 0)) == 90 * 60 + 300
    assert seq.seconds_until_reset("session limit resets 12:10pm x", _now(11, 0)) == 70 * 60 + 300


def test_no_limit_marker_returns_none():
    assert seq.seconds_until_reset("REJECTED: Script failed release gate (85/100)", _now(12, 0)) is None
    assert seq.seconds_until_reset("", _now(12, 0)) is None
