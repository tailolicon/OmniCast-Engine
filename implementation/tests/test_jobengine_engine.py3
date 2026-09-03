"""M0 PR4/PR5 — JobEngine (slots, execute/status/retry) + checkpoint skip-on-retry."""

import asyncio

import pytest

from omnicast.jobengine import store
from omnicast.jobengine.models import JobSpec, ResourceClass
from omnicast.jobengine.engine import JobEngine
from omnicast.jobengine.slots import SlotManager
from omnicast.jobengine.checkpoint import Step, run_checkpointed


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "vault.db"
    store.init_jobengine_schema(p)
    return p


def test_execute_success_and_status(db):
    eng = JobEngine(db_path=db)
    async def h(ctx):
        return {"echo": ctx.payload}
    eng.register("echo", h)
    out = asyncio.run(eng.execute(JobSpec(job_id="j1", type="echo", payload={"a": 1})))
    assert out == {"echo": {"a": 1}}
    j = eng.status("j1")
    assert j["status"] == "success" and j["started_at"] and j["finished_at"]


def test_no_handler_fails(db):
    eng = JobEngine(db_path=db)
    with pytest.raises(KeyError):
        asyncio.run(eng.execute(JobSpec(job_id="j2", type="nope")))
    assert eng.status("j2")["status"] == "failed"


def test_gpu_slot_serializes(db):
    eng = JobEngine(slots=SlotManager(gpu=1), db_path=db)
    s = {"cur": 0, "max": 0}
    async def h(ctx):
        s["cur"] += 1; s["max"] = max(s["max"], s["cur"])
        await asyncio.sleep(0.05); s["cur"] -= 1
        return {}
    eng.register("g", h)
    async def go():
        await asyncio.gather(*[eng.execute(JobSpec(job_id=f"g{i}", type="g", resource_class=ResourceClass.GPU)) for i in range(3)])
    asyncio.run(go())
    assert s["max"] == 1  # GPU bounded to 1 slot (anti-OOM)


def test_cpu_slots_parallel(db):
    eng = JobEngine(slots=SlotManager(cpu=4), db_path=db)
    s = {"cur": 0, "max": 0}
    async def h(ctx):
        s["cur"] += 1; s["max"] = max(s["max"], s["cur"])
        await asyncio.sleep(0.05); s["cur"] -= 1
        return {}
    eng.register("c", h)
    async def go():
        await asyncio.gather(*[eng.execute(JobSpec(job_id=f"c{i}", type="c", resource_class=ResourceClass.CPU)) for i in range(3)])
    asyncio.run(go())
    assert s["max"] >= 2  # CPU runs in parallel up to slot count


def test_retry_reuses_row(db):
    eng = JobEngine(db_path=db)
    n = {"v": 0}
    async def h(ctx):
        n["v"] += 1
        if n["v"] == 1:
            raise RuntimeError("first fails")
        return {}
    eng.register("r", h)
    with pytest.raises(RuntimeError):
        asyncio.run(eng.execute(JobSpec(job_id="j", type="r")))
    assert eng.status("j")["status"] == "failed"
    asyncio.run(eng.retry("j"))
    assert eng.status("j")["status"] == "success" and n["v"] == 2


def test_checkpoint_retry_skips_done(db):
    calls = {"a": 0, "b": 0, "c": 0}
    def mk(name, fail_first=False):
        async def fn(inp):
            calls[name] += 1
            if fail_first and calls[name] == 1:
                raise RuntimeError("boom")
            return (f"local://{name}", {"n": calls[name]})
        return fn
    store.insert_job(JobSpec(job_id="J", type="pipeline"), db_path=db)
    steps = [Step("a", mk("a")), Step("b", mk("b", True)), Step("c", mk("c"))]
    with pytest.raises(RuntimeError):
        asyncio.run(run_checkpointed("J", steps, db_path=db))
    asyncio.run(run_checkpointed("J", steps, db_path=db))
    assert calls == {"a": 1, "b": 2, "c": 1}  # a skipped on retry, b reran, c ran
