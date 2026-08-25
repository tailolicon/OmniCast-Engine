"""Serial queue: one job at a time, retries that resume, rubble cleaned up."""

import threading
import time

import pytest

from omnicast.reup.queue import QueuedJob, ReupQueue, clean_partial_workspace


@pytest.fixture(autouse=True)
def quiet_vault(monkeypatch):
    writes = []
    import omnicast.reup.vault_link as vl

    monkeypatch.setattr(vl, "update_job", lambda job_id, **kw: writes.append((job_id, kw)))
    monkeypatch.setattr(vl, "get_job", lambda job_id, **kw: {})
    monkeypatch.setattr("omnicast.reup.queue.RETRY_BACKOFF_S", (0.0, 0.0))
    return writes


def _drain(queue, expected, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(expected) >= 1 and not queue.snapshot()["pending"] and queue.snapshot()["running"] is None:
            return
        time.sleep(0.02)


def test_jobs_run_one_at_a_time(quiet_vault):
    # Five pasted links used to start five dubs at once, all competing for the
    # same CPU, GPU and Douyin rate limit.
    concurrent, peak, order = [], [0], []
    lock = threading.Lock()

    def run(job):
        with lock:
            concurrent.append(job.job_id)
            peak[0] = max(peak[0], len(concurrent))
        time.sleep(0.05)
        with lock:
            concurrent.remove(job.job_id)
            order.append(job.job_id)

    queue = ReupQueue(run)
    for i in range(4):
        queue.submit(QueuedJob(job_id=f"j{i}", url=f"u{i}"))
    _drain(queue, order)
    queue.stop()
    assert peak[0] == 1, "the queue must serialise"
    assert order == ["j0", "j1", "j2", "j3"], "and keep submission order"


def test_a_failing_job_is_retried_then_given_up_on(quiet_vault):
    attempts = []

    def run(job):
        attempts.append(job.attempts)
        raise RuntimeError("provider blew up")

    queue = ReupQueue(run, max_attempts=3)
    queue.submit(QueuedJob(job_id="j", url="u"))
    _drain(queue, attempts)
    queue.stop()
    assert attempts == [1, 2, 3]
    final = [kw for jid, kw in quiet_vault if kw.get("status") == "failed"]
    assert final and "bỏ cuộc sau 3" in final[-1]["error"]


def test_a_job_that_recovers_stops_retrying(quiet_vault):
    calls = []

    def run(job):
        calls.append(job.attempts)
        if job.attempts < 2:
            raise RuntimeError("transient")

    queue = ReupQueue(run, max_attempts=5)
    queue.submit(QueuedJob(job_id="j", url="u"))
    _drain(queue, calls)
    queue.stop()
    assert calls == [1, 2]
    assert not [kw for _, kw in quiet_vault if kw.get("status") == "failed"]


def test_one_bad_job_does_not_block_the_rest(quiet_vault):
    done = []

    def run(job):
        if job.job_id == "bad":
            raise RuntimeError("nope")
        done.append(job.job_id)

    queue = ReupQueue(run, max_attempts=2)
    queue.submit(QueuedJob(job_id="bad", url="u"))
    queue.submit(QueuedJob(job_id="good", url="u"))
    _drain(queue, done)
    queue.stop()
    assert done == ["good"]


def test_rubble_is_deleted_but_a_resumable_workspace_is_kept(tmp_path, monkeypatch):
    import omnicast.reup.vault_link as vl

    resumable = tmp_path / "ok"
    resumable.mkdir()
    (resumable / "project.json").write_text("{}", encoding="utf-8")
    (resumable / "project.db").write_bytes(b"")
    monkeypatch.setattr(vl, "get_job", lambda job_id, **kw: {"project_root": str(resumable)})
    assert clean_partial_workspace("j") is None
    assert resumable.is_dir(), "caches here make the retry cheap — keep them"

    rubble = tmp_path / "half"
    rubble.mkdir()
    (rubble / "cache").mkdir()
    monkeypatch.setattr(vl, "get_job", lambda job_id, **kw: {"project_root": str(rubble)})
    assert clean_partial_workspace("j") == rubble
    assert not rubble.exists(), "the runner refuses to build on partial project data"


def test_a_job_with_no_workspace_yet_is_left_alone(monkeypatch):
    import omnicast.reup.vault_link as vl

    monkeypatch.setattr(vl, "get_job", lambda job_id, **kw: {"project_root": ""})
    assert clean_partial_workspace("j") is None
