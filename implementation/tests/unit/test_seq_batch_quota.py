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


def test_completed_verdict_is_not_retried_even_with_stray_limit_marker():
    """Live 2026-07-19 batch 1456: mall finished a full release-gate rejection
    (83/100) but a stray session-limit line elsewhere in its log matched the
    quota regex — the runner slept 190 minutes and re-ran a question the run
    had already answered."""
    verdict = "REJECTED/FAILED after 2311.9s: Script failed release gate (83/100); candidate saved"
    assert seq.should_retry(1, verdict, 190 * 60.0, 1) is False


def test_quota_killed_run_is_retried():
    quota_death = "REJECTED/FAILED after 32.8s: session limit reached at compliance stage"
    assert seq.should_retry(1, quota_death, 137 * 60.0, 1) is True
    # A run with no terminal line at all (killed mid-flight) also retries.
    assert seq.should_retry(1, "", 137 * 60.0, 1) is True
    assert seq.should_retry(1, "(log unreadable: boom)", 137 * 60.0, 1) is True


def test_retry_guards():
    quota_death = "session limit reached"
    assert seq.should_retry(0, quota_death, 60.0, 1) is False   # success
    assert seq.should_retry(1, quota_death, None, 1) is False   # no limit marker
    assert seq.should_retry(1, quota_death, 60.0, 3) is False   # tries exhausted


def test_standard_roles_pinned_but_operator_export_wins():
    """Batch 20260719_1456 silently reverted to Opus roles because the Sonnet
    standard lived only in the launching shell's environment. The runner now
    pins the standard itself; explicit exports still win."""
    env: dict[str, str] = {}
    seq.apply_standard_roles(env)
    assert env["OMNICAST_NARRATIVE_PLANNER_MODEL"] == "claude-sonnet-5"
    assert env["OMNICAST_NARRATIVE_WRITER_MODEL"] == "claude-sonnet-5"
    assert env["OMNICAST_NARRATIVE_PLANNER_EFFORT"] == "high"
    assert env["OMNICAST_NARRATIVE_WRITER_EFFORT"] == "high"

    operator = {"OMNICAST_NARRATIVE_WRITER_MODEL": "claude-opus-4-8"}
    seq.apply_standard_roles(operator)
    assert operator["OMNICAST_NARRATIVE_WRITER_MODEL"] == "claude-opus-4-8"
