"""Picking a stopped job back up instead of starting over."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from omnicast.api import reup_routes as routes


@pytest.fixture
def spawned(monkeypatch):
    """Capture the thread that would run, without running it."""
    started = []
    monkeypatch.setattr(
        routes.threading, "Thread",
        lambda target, name=None, daemon=None: type(
            "_T", (), {"start": lambda self: started.append(name)}
        )(),
    )
    return started


def _job(monkeypatch, tmp_path, **over):
    row = {
        "job_id": "reup-1", "source_url": "https://www.douyin.com/video/7",
        "status": "failed", "project_root": str(tmp_path), "channel_id": "chan",
        "voice_preset_id": "vieneu-default-vi",
    }
    row.update(over)
    monkeypatch.setattr(routes.vault_link if hasattr(routes, "vault_link") else routes,
                        "__name__", routes.__name__, raising=False)
    import omnicast.reup.vault_link as vl

    monkeypatch.setattr(vl, "get_job", lambda job_id, **kw: row)
    monkeypatch.setattr(vl, "update_job", lambda *a, **kw: None)
    return row


def test_a_failed_job_resumes_from_its_workspace(monkeypatch, tmp_path, spawned):
    _job(monkeypatch, tmp_path)
    result = routes.reup_resume("reup-1", routes.ReupResumeRequest())
    assert result["status"] == "running"
    assert result["resumed_from"] == str(tmp_path)
    assert spawned == ["reup-resume-reup-1"]


def test_a_running_job_is_not_started_twice(monkeypatch, tmp_path, spawned):
    _job(monkeypatch, tmp_path, status="running")
    with pytest.raises(HTTPException) as excinfo:
        routes.reup_resume("reup-1", routes.ReupResumeRequest())
    assert excinfo.value.status_code == 409
    assert spawned == []


def test_a_job_that_never_got_a_workspace_cannot_resume(monkeypatch, tmp_path, spawned):
    # Died before bootstrap: there is nothing on disk to pick up, and saying so
    # beats silently re-downloading under the old job id.
    _job(monkeypatch, tmp_path, project_root="")
    with pytest.raises(HTTPException) as excinfo:
        routes.reup_resume("reup-1", routes.ReupResumeRequest())
    assert excinfo.value.status_code == 409
    assert spawned == []


def test_a_vanished_workspace_is_refused(monkeypatch, tmp_path, spawned):
    _job(monkeypatch, tmp_path, project_root=str(tmp_path / "deleted"))
    with pytest.raises(HTTPException):
        routes.reup_resume("reup-1", routes.ReupResumeRequest())
    assert spawned == []


def test_an_unknown_stop_after_is_rejected(monkeypatch, tmp_path, spawned):
    _job(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as excinfo:
        routes.reup_resume("reup-1", routes.ReupResumeRequest(stop_after="nope"))
    assert excinfo.value.status_code == 400
    assert spawned == []


def test_download_is_a_valid_stop_after_now():
    # It was announced by the runner but missing from STAGES, which also made
    # the UI show no chip during a five-minute download.
    assert "download" in routes.STAGES
    assert routes.STAGES[0] == "download"


def test_an_unknown_job_is_404(monkeypatch, spawned):
    import omnicast.reup.vault_link as vl

    monkeypatch.setattr(vl, "get_job", lambda job_id, **kw: None)
    with pytest.raises(HTTPException) as excinfo:
        routes.reup_resume("nope", routes.ReupResumeRequest())
    assert excinfo.value.status_code == 404


def test_a_manual_export_is_refused_while_the_job_is_running(monkeypatch, tmp_path, spawned):
    # The pipeline runs its own export at the end of a job. A second one on the
    # same project writes the same output and the same `.partial` staging file
    # — the collision that produced an unplayable video earlier.
    _job(monkeypatch, tmp_path, status="running")
    with pytest.raises(HTTPException) as excinfo:
        routes.reup_reexport("reup-1")
    assert excinfo.value.status_code == 409
    assert spawned == []


def test_the_done_sentinel_does_not_reset_a_finished_job_to_running(monkeypatch):
    """`_announce("done", …)` used to overwrite the status `_done` just set.

    Every completed job then sat in the list as "running" with all its stage
    chips green — indistinguishable from a job that had genuinely hung.
    """
    import omnicast.reup.vault_link as vl

    writes = []
    monkeypatch.setattr(vl, "update_job", lambda job_id, **kw: writes.append(kw))

    # Reproduce the two calls the runner makes at the end of a job.
    def announce(stage):
        if stage != "done":
            vl.update_job("j", status="running", last_stage=stage)

    vl.update_job("j", status="done", last_stage="export")   # _done("export", ...)
    announce("done")                                          # _announce("done", ...)

    assert writes[-1]["status"] == "done", "the terminal announce must not clobber it"
