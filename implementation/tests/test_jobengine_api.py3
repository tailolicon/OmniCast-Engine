"""M0 PR8 — FastAPI v1 surface (submit/status/health/events)."""

import pytest
from fastapi.testclient import TestClient

from omnicast.jobengine import store
from omnicast.jobengine.engine import JobEngine
from omnicast.jobengine.api import create_app


@pytest.fixture()
def client(tmp_path):
    db = tmp_path / "vault.db"
    store.init_jobengine_schema(db)
    eng = JobEngine(db_path=db)
    async def echo(ctx):
        return {"echo": ctx.payload}
    eng.register("echo", echo)
    return TestClient(create_app(eng))


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["ok"] and "echo" in r.json()["handlers"]


def test_submit_wait_and_status(client):
    r = client.post("/api/v1/jobs?wait=true", json={"type": "echo", "payload": {"a": 1}, "job_id": "j1"})
    assert r.status_code == 200 and r.json()["job_id"] == "j1"
    j = client.get("/api/v1/jobs/j1").json()
    assert j["status"] == "success"
    evs = client.get("/api/v1/events").json()
    assert any(e["type"] == "job.finished" for e in evs)


def test_unknown_job_404(client):
    assert client.get("/api/v1/jobs/nope").status_code == 404
