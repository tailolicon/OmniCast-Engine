"""_all_channels() phải bỏ qua file JSON không phải channel config (credentials.json)."""
import json

import pytest


@pytest.fixture()
def channels_dir(tmp_path, monkeypatch):
    from omnicast.api import server

    monkeypatch.setattr(server, "CHANNELS_DIR", tmp_path)
    return tmp_path


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_skips_json_without_channel_id(channels_dir):
    from omnicast.api import server

    _write(channels_dir / "good.json", {"channel_id": "good_us", "name": "Good"})
    _write(channels_dir / "credentials.json", {"youtube": {"client_id": "x"}})
    _write(channels_dir / "empty_id.json", {"channel_id": "", "name": "Ghost"})

    channels = server._all_channels()

    assert [c["channel_id"] for c in channels] == ["good_us"]


def test_skips_broken_json_and_non_dict(channels_dir):
    from omnicast.api import server

    _write(channels_dir / "list.json", ["not", "a", "dict"])
    (channels_dir / "broken.json").write_text("{oops", encoding="utf-8")
    _write(channels_dir / "ok.json", {"channel_id": "ok_us"})

    channels = server._all_channels()

    assert [c["channel_id"] for c in channels] == ["ok_us"]
