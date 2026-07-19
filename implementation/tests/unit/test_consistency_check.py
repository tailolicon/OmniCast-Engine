"""verify_scenes orchestration: re-roll bounds, drift kept (never hard-fail),
vision-API circuit breaker. verify_image itself is monkeypatched — no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # implementation/

import consistency_check
from consistency_check import verify_scenes

DNA = "SAME recurring character Max: round face, red hoodie"


def _images(tmp_path, n) -> dict[int, Path]:
    out = {}
    for i in range(n):
        p = tmp_path / f"scene_{i:02d}_illu.png"
        p.write_bytes(b"png" + bytes([i]))
        out[i] = p
    return out


def test_empty_inputs_noop(tmp_path):
    assert verify_scenes({}, DNA)["checked"] == 0
    assert verify_scenes(_images(tmp_path, 2), "")["checked"] == 0


def test_all_match(monkeypatch, tmp_path):
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: {"match": True, "reason": ""})
    rep = verify_scenes(_images(tmp_path, 3), DNA)
    assert rep["checked"] == rep["passed"] == 3
    assert not rep["drifted"] and not rep["rerolled"]


def test_drift_without_regen_is_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: {"match": False, "reason": "wrong hair"})
    rep = verify_scenes(_images(tmp_path, 2), DNA, regen=None)
    assert rep["drifted"] == [0, 1]  # surfaced, not removed


def test_reroll_fixes_drift(monkeypatch, tmp_path):
    imgs = _images(tmp_path, 1)
    verdicts = iter([{"match": False, "reason": "wrong hair"},
                     {"match": True, "reason": ""}])
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: next(verdicts))
    calls = []
    rep = verify_scenes(imgs, DNA, regen=lambda i, p: calls.append(i) or True)
    assert calls == [0]
    assert rep["rerolled"] == [0] and rep["passed"] == 1 and not rep["drifted"]


def test_reroll_budget_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: {"match": False, "reason": "drift"})
    calls = []
    rep = verify_scenes(_images(tmp_path, 6), DNA,
                        regen=lambda i, p: calls.append(i) or True,
                        max_rerolls=2)
    assert len(calls) == 2          # budget respected
    assert len(rep["drifted"]) == 6  # all still surfaced, video not blocked


def test_vision_down_circuit_breaker(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: calls.append(1) or None)
    rep = verify_scenes(_images(tmp_path, 5), DNA)
    assert len(calls) == 2           # stops after 2 consecutive API errors
    assert sorted(rep["unverified"]) == [0, 1, 2, 3, 4]
    assert rep["checked"] == 0


# ── WS1: quantitative drift, report file, gate ────────────────────────────────

def test_scores_and_aggregates(monkeypatch, tmp_path):
    verdicts = iter([{"match": True, "score": 9, "reason": ""},
                     {"match": True, "score": 7, "reason": ""},
                     {"match": False, "score": 2, "reason": "different face"},
                     {"match": False, "score": 3, "reason": "wrong outfit"}])
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: next(verdicts))
    rep = verify_scenes(_images(tmp_path, 4), DNA, gate="off")
    assert rep["checked"] == 4 and rep["drifted"] == [2, 3]
    assert rep["drift_ratio"] == 0.5
    assert rep["mean_score"] == 5.25
    assert rep["scores"] == {0: 9.0, 1: 7.0, 2: 2.0, 3: 3.0}


def test_verdict_without_score_derives_from_match(monkeypatch, tmp_path):
    # Old cached v1 verdicts have no score → 10/0 derived from match.
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: {"match": True, "reason": ""})
    rep = verify_scenes(_images(tmp_path, 2), DNA, gate="off")
    assert rep["mean_score"] == 10.0 and rep["drift_ratio"] == 0.0


def test_report_file_written(monkeypatch, tmp_path):
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: {"match": False, "score": 1,
                                          "reason": "drift"})
    rp = tmp_path / "product" / "_consistency_report.json"
    rep = verify_scenes(_images(tmp_path, 2), DNA, report_path=rp, gate="off")
    import json
    data = json.loads(rp.read_text(encoding="utf-8"))
    assert data["drift_ratio"] == rep["drift_ratio"] == 1.0
    assert data["checked"] == 2


def test_gate_off_and_warn_never_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: {"match": False, "score": 0,
                                          "reason": "drift"})
    for mode in ("off", "warn"):
        rep = verify_scenes(_images(tmp_path, 3), DNA, gate=mode)
        assert rep["drift_ratio"] == 1.0  # surfaced, video not blocked


def test_gate_block_raises_above_threshold(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: {"match": False, "score": 0,
                                          "reason": "drift"})
    with pytest.raises(consistency_check.ConsistencyGateError):
        verify_scenes(_images(tmp_path, 3), DNA, gate="block")


def test_gate_block_passes_below_threshold(monkeypatch, tmp_path):
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: {"match": True, "score": 9,
                                          "reason": ""})
    rep = verify_scenes(_images(tmp_path, 3), DNA, gate="block")
    assert rep["passed"] == 3  # no raise


def test_gate_error_pierces_except_exception():
    # The render wraps QA in `except Exception` — a block-gate must NOT be
    # swallowed by it (SystemExit subclass), or the gate silently never fires.
    err = consistency_check.ConsistencyGateError("boom")
    assert isinstance(err, SystemExit)
    assert not isinstance(err, Exception)


def test_max_checks_env_override(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(consistency_check, "verify_image",
                        lambda img, dna: calls.append(1) or {"match": True,
                                                             "score": 10,
                                                             "reason": ""})
    monkeypatch.setenv("OMNICAST_CONSISTENCY_MAX_CHECKS", "0")  # unlimited
    rep = verify_scenes(_images(tmp_path, 20), DNA, gate="off")
    assert rep["checked"] == 20  # old hard cap of 16 lifted via env
