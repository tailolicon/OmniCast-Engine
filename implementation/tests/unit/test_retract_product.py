"""Tightening a gate has to be able to reach work the old gate let through.

v8 of the flagship script was approved at 82/100 and written to disk with
`production_ready: true`. The gate that approved it was then corrected — it
had only deducted points for breaching a measured floor instead of failing
closed. Nothing re-examined v8. It kept its green flag, and the topic it had
claimed stayed `used`, so the corrected pipeline could not even replace it:
the rejected-quality script was both the newest approved artifact and the
reason no better one could be made.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "retract_product.py"


def _product(tmp_path: Path, **over) -> Path:
    d = tmp_path / "20260803_1404_topic"
    d.mkdir(parents=True, exist_ok=True)
    meta = {"channel": "ch", "topic": "A Topic", "slug": d.name,
            "stage": "script", "score": 82, "approved": True,
            "script_approved": True, "production_ready": True,
            "content_locked": True}
    meta.update(over)
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "script.txt").write_text("the draft itself", encoding="utf-8")
    return d


def _run(d: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(d), "--reason", "gate corrected",
         *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_retraction_clears_every_green_flag(tmp_path):
    d = _product(tmp_path)
    assert _run(d).returncode == 0
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["approved"] is False
    assert meta["script_approved"] is False
    assert meta["production_ready"] is False
    assert meta["content_locked"] is False
    assert meta["stage"] == "retracted"


def test_the_reason_and_the_previous_state_are_recorded(tmp_path):
    """A retraction with no reason is indistinguishable from a mistake, and
    without the prior state nobody can tell what was withdrawn."""
    d = _product(tmp_path)
    _run(d)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["retracted_reason"] == "gate corrected"
    assert meta["retracted_at"]
    assert meta["retracted_from"]["score"] == 82
    assert meta["retracted_from"]["production_ready"] is True


def test_nothing_is_deleted(tmp_path):
    """The draft is the evidence that the old gate was wrong. Deleting it
    would erase the reason the gate changed."""
    d = _product(tmp_path)
    _run(d)
    assert (d / "script.txt").read_text(encoding="utf-8") == "the draft itself"


def test_retracting_twice_is_harmless(tmp_path):
    d = _product(tmp_path)
    _run(d)
    first = (d / "meta.json").read_text(encoding="utf-8")
    out = _run(d)
    assert out.returncode == 0
    assert "already retracted" in out.stdout
    assert (d / "meta.json").read_text(encoding="utf-8") == first


def test_a_missing_product_is_reported_not_crashed(tmp_path):
    out = _run(tmp_path / "nope")
    assert out.returncode == 1
    assert "no meta.json" in out.stdout


def test_freeing_the_topic_is_opt_in(tmp_path):
    """Demoting the artifact and releasing its claim on the topic are separate
    decisions; a retraction for other reasons should not silently re-open a
    topic for regeneration."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"--free-topic", action="store_true"' in src
    assert "status='used'" in src        # only a used claim is released
    assert "if args.free_topic" in src
