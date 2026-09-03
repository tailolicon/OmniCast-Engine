"""Opening a finished dub on the operator's desktop, safely."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from omnicast.api import reup_routes as routes


@pytest.fixture
def launched(monkeypatch):
    """Capture what would have been handed to the desktop."""
    calls = []
    monkeypatch.setattr(routes.sys, "platform", "win32", raising=False)
    monkeypatch.setattr("os.startfile", lambda p: calls.append(("open", p)), raising=False)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: calls.append(("popen", args)))
    return calls


def _stage(tmp_path, monkeypatch, *, published=True):
    products = tmp_path / "products"
    workspace = tmp_path / "reup"
    (workspace / "7").mkdir(parents=True)
    monkeypatch.setattr(routes, "PRODUCTS_DIR", products)
    monkeypatch.setattr(routes, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(routes, "_job_root", lambda job_id: workspace / "7")
    video = products / "chan" / "20260809_x" / "video.mp4"
    if published:
        video.parent.mkdir(parents=True)
        video.write_bytes(b"mp4")
    monkeypatch.setattr(routes, "_published_product", lambda j, r: video if published else None)
    return video


def test_opening_the_file_hands_it_to_the_default_player(tmp_path, monkeypatch, launched):
    video = _stage(tmp_path, monkeypatch)
    result = routes.reup_open_result("job", target="file")
    assert result["opened"] == "file"
    assert launched == [("open", str(video.resolve()))]


def test_opening_the_folder_selects_the_file(tmp_path, monkeypatch, launched):
    video = _stage(tmp_path, monkeypatch)
    routes.reup_open_result("job", target="folder")
    kind, args = launched[0]
    assert kind == "popen" and args[0] == "explorer"
    assert args[-1] == str(video.resolve()), "must select the file, not just list the folder"


def test_an_unknown_target_is_rejected(tmp_path, monkeypatch, launched):
    _stage(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as excinfo:
        routes.reup_open_result("job", target="rm -rf /")
    assert excinfo.value.status_code == 400
    assert launched == []


def test_a_path_outside_the_output_roots_is_refused(tmp_path, monkeypatch, launched):
    # A poisoned database value must never reach the shell.
    _stage(tmp_path, monkeypatch)
    stray = tmp_path / "elsewhere" / "payload.mp4"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"x")
    monkeypatch.setattr(routes, "_published_product", lambda j, r: stray)
    with pytest.raises(HTTPException) as excinfo:
        routes.reup_open_result("job", target="file")
    assert excinfo.value.status_code == 400
    assert launched == []


def test_a_job_with_no_video_says_so(tmp_path, monkeypatch, launched):
    _stage(tmp_path, monkeypatch, published=False)
    with pytest.raises(HTTPException) as excinfo:
        routes.reup_open_result("job", target="file")
    assert excinfo.value.status_code == 409
    assert launched == []
