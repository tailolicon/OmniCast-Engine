"""PR1 tests — Job Engine M0 schema + models + idempotency.

Additive-only layer: every test runs against a throwaway db_path so it never
touches the real output/vault.db.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
UTC = timezone.utc

import pytest

from omnicast.jobengine import (
    JobSpec, JobStatus, ResourceClass, idempotency_key, canonical_inputs,
)
from omnicast.jobengine import store


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "vault.db"
    store.init_jobengine_schema(p)
    return p


def test_schema_creates_all_tables(db):
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "job_steps", "checkpoints", "assets", "worker_slots", "events"} <= names


def test_job_roundtrip_and_status(db):
    spec = JobSpec(job_id="j1", type="pipeline", resource_class=ResourceClass.GPU,
                   payload={"channel": "abc"})
    store.insert_job(spec, db_path=db)
    j = store.get_job("j1", db_path=db)
    assert j["status"] == JobStatus.QUEUED.value
    assert j["resource_class"] == "gpu"
    assert j["payload"] == {"channel": "abc"}

    store.set_job_status("j1", JobStatus.RUNNING, mark_started=True, db_path=db)
    store.set_job_status("j1", JobStatus.FAILED, error="boom", mark_finished=True, db_path=db)
    j = store.get_job("j1", db_path=db)
    assert j["status"] == "failed" and j["error"] == "boom"
    assert j["started_at"] and j["finished_at"]
    assert len(store.list_jobs(status="failed", db_path=db)) == 1


def test_steps_upsert(db):
    store.insert_job(JobSpec(job_id="j2", type="pipeline"), db_path=db)
    store.upsert_step("j2", 0, "script", "running", mark_started=True, db_path=db)
    store.upsert_step("j2", 0, "script", "success", mark_finished=True, db_path=db)
    store.upsert_step("j2", 1, "render", "failed", error="oom", db_path=db)
    steps = store.get_steps("j2", db_path=db)
    assert [s["status"] for s in steps] == ["success", "failed"]
    assert steps[0]["started_at"]  # preserved across upsert


def test_checkpoint_roundtrip(db):
    store.insert_job(JobSpec(job_id="j3", type="pipeline"), db_path=db)
    key = idempotency_key("render", {"prompt": "a cat"})
    store.save_checkpoint("j3", "render", key, "local://out/x.png", {"w": 1024}, db_path=db)
    ck = store.get_checkpoint("j3", "render", db_path=db)
    assert ck["idempotency_key"] == key
    assert ck["output_ref"] == "local://out/x.png"
    assert ck["output"] == {"w": 1024}


def test_asset_dedup_and_gc(db):
    a1 = store.register_asset(kind="image", storage_ref="local://a.png",
                              sha256="deadbeef", size_bytes=10, db_path=db)
    a2 = store.register_asset(kind="image", storage_ref="local://b.png",
                              sha256="deadbeef", size_bytes=10, db_path=db)
    assert a1 == a2  # dedup by sha256

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    expired = store.register_asset(kind="audio", storage_ref="local://tmp.wav",
                                   ttl_at=past, db_path=db)
    store.register_asset(kind="master", storage_ref="local://master.mp4", db_path=db)  # ttl NULL

    due = store.assets_due_for_gc(db_path=db)
    ids = {d["asset_id"] for d in due}
    assert expired in ids                      # expired intermediate collected
    assert all(d["kind"] != "master" for d in due)  # master (ttl NULL) never collected

    store.mark_asset_deleted(expired, db_path=db)
    assert store.get_asset(expired, db_path=db)["state"] == "deleted"
    assert not store.assets_due_for_gc(db_path=db)  # no longer due


def test_worker_slots_and_events(db):
    store.upsert_worker_slots("w1", slots_gpu=1, slots_cpu=8, slots_net=16, db_path=db)
    store.upsert_worker_slots("w1", slots_gpu=2, slots_cpu=8, slots_net=16, db_path=db)
    ws = store.get_worker_slots("w1", db_path=db)
    assert ws["slots_gpu"] == 2 and ws["slots_cpu"] == 8

    e1 = store.append_event("job.started", job_id="j1", payload={"x": 1}, db_path=db)
    store.append_event("job.finished", job_id="j1", db_path=db)
    evs = store.list_events(since_id=e1 - 1, db_path=db)
    assert [e["type"] for e in evs] == ["job.started", "job.finished"]
    assert evs[0]["payload"] == {"x": 1}


# ── idempotency gotcha: non-deterministic fields must NOT change the key ──────

def test_idempotency_ignores_nondeterministic_fields():
    base = {"prompt": "a cat", "channel_id": "c1"}
    noisy = {
        "prompt": "a cat", "channel_id": "c1",
        "timestamp": "2026-06-30T10:00:00Z", "run_id": "uuid-123",
        "created_at": "2026-06-30T10:00:00Z", "attempt": 3,
        "tmp_path": "/tmp/abc123/scene.png",
    }
    assert idempotency_key("render", base) == idempotency_key("render", noisy)


def test_idempotency_changes_on_real_input_change():
    k1 = idempotency_key("render", {"prompt": "a cat"})
    k2 = idempotency_key("render", {"prompt": "a dog"})
    k3 = idempotency_key("tts", {"prompt": "a cat"})  # different step_id
    assert k1 != k2 and k1 != k3


def test_canonical_inputs_key_order_stable():
    assert canonical_inputs({"b": 1, "a": 2}) == canonical_inputs({"a": 2, "b": 1})
