"""Repair budget — content-keyed bounded retry ledger (Orkas draft-repair port)."""

import json

from omnicast.pipeline.repair_budget import (
    MAX_FAILURES_DEFAULT,
    RepairBudget,
    content_signature,
)


def test_signature_deterministic_and_input_sensitive():
    a = content_signature("script text", "ch1", "shorts=False")
    assert a == content_signature("script text", "ch1", "shorts=False")
    assert a != content_signature("script text CHANGED", "ch1", "shorts=False")
    assert a != content_signature("script text", "ch2", "shorts=False")


def test_fresh_budget_not_blocked(tmp_path):
    b = RepairBudget.load(tmp_path / "_repair_state.json")
    assert not b.blocked("sig-a")
    assert b.remaining("sig-a") == MAX_FAILURES_DEFAULT


def test_blocks_after_max_failures_same_signature(tmp_path):
    p = tmp_path / "_repair_state.json"
    sig = "sig-a"
    for n in range(MAX_FAILURES_DEFAULT):
        b = RepairBudget.load(p)
        assert not b.blocked(sig), f"blocked too early at failure {n}"
        b.record_failure(sig, "render", f"boom {n}")
    b = RepairBudget.load(p)
    assert b.blocked(sig)
    assert b.remaining(sig) == 0
    # State file is valid JSON with an audit trail.
    state = json.loads(p.read_text(encoding="utf-8"))
    assert state["failed_attempts"] == MAX_FAILURES_DEFAULT
    assert len(state["history"]) == MAX_FAILURES_DEFAULT
    assert state["last_error"]["code"] == "render"


def test_changed_content_resets_budget(tmp_path):
    p = tmp_path / "_repair_state.json"
    for _ in range(MAX_FAILURES_DEFAULT):
        b = RepairBudget.load(p)
        b.record_failure("sig-old", "render", "boom")
    b = RepairBudget.load(p)
    assert b.blocked("sig-old")
    assert not b.blocked("sig-new")  # different content -> fresh budget
    b.record_failure("sig-new", "render", "boom")
    b2 = RepairBudget.load(p)
    assert b2.failed_attempts == 1  # counter restarted, not accumulated


def test_success_clears_block(tmp_path):
    p = tmp_path / "_repair_state.json"
    b = RepairBudget.load(p)
    for _ in range(MAX_FAILURES_DEFAULT):
        b.record_failure("sig-a", "audit", "issues")
    b.record_success("sig-a", "passed on manual rerun")
    b2 = RepairBudget.load(p)
    assert not b2.blocked("sig-a")
    assert b2.failed_attempts == 0
    assert b2.state["status"] == "ok"


def test_corrupt_state_never_blocks(tmp_path):
    p = tmp_path / "_repair_state.json"
    p.write_text("{not json!!", encoding="utf-8")
    b = RepairBudget.load(p)
    assert not b.blocked("sig-a")
    b.record_failure("sig-a", "render", "boom")  # writes fresh valid state
    assert json.loads(p.read_text(encoding="utf-8"))["failed_attempts"] == 1
