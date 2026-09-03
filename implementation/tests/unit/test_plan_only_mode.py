"""Judging a premise must not cost a whole run — and must not change one.

Nine live runs produced no releasable compilation and the last four died on
the quality of the PREMISE, not on plumbing. Planning is one planner call plus
one audit; discovering a bad premise by running the full pipeline costs
twenty-five minutes and most of a quota window, which is why only nine
premises had been looked at at all.

The danger in a diagnostic mode is that it leaks into production. These tests
pin both halves: it works when asked for, and it is invisible when not.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import omnicast.agents.narrative_pipeline as np

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def test_the_flag_is_off_unless_explicitly_set():
    assert os.environ.get("OMNICAST_NARRATIVE_PLAN_ONLY") in (None, "", "0")


def test_plan_only_is_not_reported_as_a_failure_type():
    """It subclasses the abort family so callers unwind cleanly, but it means
    "the plan is good, you asked me to stop" — the opposite of the siblings."""
    assert issubclass(np.PlanOnlyComplete, np.NarrativeRunAborted)
    assert not issubclass(np.PlanOnlyComplete, np.PlanNotPlausible)
    assert not issubclass(np.PlanOnlyComplete, np.PlannerUnavailable)
    doc = inspect.getdoc(np.PlanOnlyComplete) or ""
    assert "not a failure" in doc.lower()


def test_it_carries_the_plan_and_the_verdict():
    sig = inspect.signature(np.PlanOnlyComplete.__init__)
    assert list(sig.parameters)[1:] == ["plan", "audit"]


def test_it_stops_before_any_story_call():
    src = inspect.getsource(np)
    i_raise = src.index("raise PlanOnlyComplete(plan, plan_audit)")
    i_write = src.index('self._record_call("story_writer")')
    assert i_raise < i_write, (
        "stopping after the writer has been paid defeats the purpose")


def test_the_production_path_is_untouched_when_the_flag_is_absent():
    """An env read guards it, not a parameter, so no caller signature changes
    and an unset flag leaves the run byte-identical."""
    src = inspect.getsource(np)
    i = src.index("raise PlanOnlyComplete")
    guard = src[max(0, i - 500):i]
    assert 'os.environ.get("OMNICAST_NARRATIVE_PLAN_ONLY"' in guard
    assert '"1", "true", "yes", "on"' in guard


def test_the_driver_reports_rejections_rather_than_crashing():
    """A rejected premise is the useful case — it is the reason to run this at
    all — so the driver must print why and continue to the next one."""
    driver = SCRIPTS / "plan_only.py"
    src = driver.read_text(encoding="utf-8")
    assert "except PlanOnlyComplete" in src
    assert "except Exception" in src
    assert "--repeat" in src


def test_the_driver_pins_the_standard_model_roles():
    """Same trap that cost two quota windows: a launcher that enters the
    pipeline without pinning roles runs Opus at max effort."""
    driver = SCRIPTS / "plan_only.py"
    src = driver.read_text(encoding="utf-8")
    assert "apply_standard_roles(os.environ)" in src


def test_run_with_retry_lets_plan_only_out():
    """Run 11 had both plans ACCEPTED and the driver printed REJECTED: the
    generic except in run_with_retry caught PlanOnlyComplete, filed it as
    'aborted', retried, and dropped the plan. The re-raise must sit BEFORE
    the generic handler."""
    src = inspect.getsource(np.NarrativeUnitPipeline.run_with_retry)
    i_plan = src.index("except PlanOnlyComplete:")
    i_generic = src.index("except Exception as exc:")
    assert i_plan < i_generic
    assert "raise" in src[i_plan:i_plan + 500]
