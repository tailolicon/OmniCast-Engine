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
