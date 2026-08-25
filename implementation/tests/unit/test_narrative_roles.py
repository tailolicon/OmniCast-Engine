"""Every door into the narrative pipeline must pin the same model tier.

This configuration has been lost twice, identically both times: it lived in one
launcher, someone entered through a different one, and the run quietly used a
model tier nobody chose.

  * 2026-07-19 — the overrides lived only in the launching shell. A relaunch
    without them ran an entire batch on Opus roles; it surfaced days later in
    an audit log. The fix pinned them inside `run_seq_batch.py`.
  * 2026-08-03 — a single run launched through `run_phase2_unit_first.py`,
    which never received that fix, put planner and writer on Opus at max
    effort and exhausted the session quota 37 minutes in, scoring 0/100.

A launcher that forgets is the defect these tests exist to catch.
"""

from __future__ import annotations

from pathlib import Path

from omnicast.config.narrative_roles import STANDARD_ROLE_ENV, apply_standard_roles

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
LAUNCHERS = ("run_seq_batch.py", "run_phase2_unit_first.py")


def test_the_standard_is_sonnet_not_opus():
    """The A/B chose Sonnet for planner and writer: -36% cost, best campaign
    score. Opus stays on the challenger, where cross-lineage adversarial
    judgement is the point."""
    assert STANDARD_ROLE_ENV["OMNICAST_NARRATIVE_PLANNER_MODEL"] == "claude-sonnet-5"
    assert STANDARD_ROLE_ENV["OMNICAST_NARRATIVE_WRITER_MODEL"] == "claude-sonnet-5"


def test_claude_only_is_off_by_default():
    """`CLAUDE_ONLY=1` forces every judge onto the Anthropic quota and roughly
    doubles the burn per run. It is a debugging switch, and launching in it is
    how one compilation consumed a whole window."""
    assert STANDARD_ROLE_ENV["OMNICAST_NARRATIVE_CLAUDE_ONLY"] == "0"


def test_an_explicit_operator_export_still_wins():
    """Pinning policy must not take the override away from a human who means
    it — setdefault, never assignment."""
    env = {"OMNICAST_NARRATIVE_WRITER_MODEL": "claude-opus-5"}
    apply_standard_roles(env)
    assert env["OMNICAST_NARRATIVE_WRITER_MODEL"] == "claude-opus-5"
    assert env["OMNICAST_NARRATIVE_PLANNER_MODEL"] == "claude-sonnet-5"


def test_applying_twice_changes_nothing():
    env: dict[str, str] = {}
    apply_standard_roles(env)
    once = dict(env)
    apply_standard_roles(env)
    assert env == once


def test_every_launcher_applies_the_standard():
    for name in LAUNCHERS:
        src = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "apply_standard_roles" in src, (
            f"{name} enters the narrative pipeline without pinning the model "
            "tier — this is exactly the bug that cost two quota windows")


def test_no_launcher_keeps_a_private_copy_of_the_table():
    """Two copies drift, and the drift is invisible until an audit log is read
    weeks later."""
    for name in LAUNCHERS:
        src = (SCRIPTS / name).read_text(encoding="utf-8")
        if "STANDARD_ROLE_ENV" in src:
            assert "from omnicast.config.narrative_roles import" in src, (
                f"{name} defines its own role table instead of importing the "
                "shared one")


def test_the_unit_first_launcher_pins_before_the_pipeline_is_imported():
    """Order matters: the pipeline reads these on import, so pinning after the
    import would look correct and do nothing."""
    src = (SCRIPTS / "run_phase2_unit_first.py").read_text(encoding="utf-8")
    assert src.index("apply_standard_roles(os.environ)") < src.index(
        "from omnicast.pipeline.steps import")
