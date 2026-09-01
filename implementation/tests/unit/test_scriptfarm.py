"""Script Farm — CI validator contract + laptop import loader."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / "scriptfarm" / "tools" / "validate_script.py"


@pytest.fixture()
def farm_validator(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("farm_validator", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Point the validator at a synthetic farm so tests never touch real channels.
    monkeypatch.setattr(mod, "FARM", tmp_path)
    (tmp_path / "channels" / "test_channel").mkdir(parents=True)
    (tmp_path / "channels" / "test_channel" / "meta.json").write_text(
        json.dumps({"target_duration_min": 1}), encoding="utf-8")
    return mod


def _scene(vo: str) -> dict:
    return {"vo": vo, "visual": "close-up of a calculator on a desk"}


def _script_text(*, segments: int = 3, words_per_scene: int = 20,
                 scenes_per_block: int = 3) -> str:
    vo = " ".join(["word"] * words_per_scene)
    block = "SCENES:\n" + json.dumps([_scene(vo)] * scenes_per_block)
    parts = ["HOOK:", block]
    for i in range(1, segments + 1):
        parts += [f"SEGMENT {i}: Heading {i}", block]
    parts += ["OUTRO:", block]
    return "\n".join(parts) + "\n"


def _write_item(tmp_path: Path, text: str, item_id: str = "20260901_test") -> Path:
    item_dir = tmp_path / "scripts" / "test_channel" / item_id
    item_dir.mkdir(parents=True)
    script = item_dir / "script.md"
    script.write_text(text, encoding="utf-8")
    (item_dir / "result.json").write_text(json.dumps({
        "item_id": item_id, "channel_id": "test_channel", "title": "t",
    }), encoding="utf-8")
    return script


def test_valid_script_passes(farm_validator, tmp_path):
    script = _write_item(tmp_path, _script_text())
    assert farm_validator.validate(script) == []


def test_structure_failures_reported(farm_validator, tmp_path):
    script = _write_item(tmp_path, "HOOK:\nSCENES:\n[]\nOUTRO:\nSCENES:\nnot-json\n")
    errs = "\n".join(farm_validator.validate(script))
    assert "SEGMENT blocks" in errs
    assert "SCENES array is empty" in errs
    assert "unparseable" in errs


def test_placeholder_and_floor_and_vo_cap(farm_validator, tmp_path):
    text = _script_text(words_per_scene=50, scenes_per_block=1) + "\n{{TITLE}}\n"
    script = _write_item(tmp_path, text)
    errs = "\n".join(farm_validator.validate(script))
    assert "placeholder residue" in errs
    assert "max 45" in errs


def test_result_json_mismatch(farm_validator, tmp_path):
    script = _write_item(tmp_path, _script_text())
    (script.parent / "result.json").write_text(json.dumps({
        "item_id": "wrong", "channel_id": "test_channel",
    }), encoding="utf-8")
    errs = "\n".join(farm_validator.validate(script))
    assert "item_id" in errs


def test_real_channel_templates_have_no_unrendered_files():
    """Every committed channel dir carries the generated trio."""
    channels = sorted((REPO_ROOT / "scriptfarm" / "channels").glob("*/"))
    assert channels, "no generated channel templates committed"
    for ch in channels:
        for name in ("SYSTEM.md", "TASK.md", "meta.json"):
            assert (ch / name).is_file(), f"{ch.name} missing {name}"


class TestFarmLoader:
    def _seed(self, root: Path, status: str = "drafted") -> None:
        farm = root / "scriptfarm"
        (farm / "scripts" / "ch1" / "item1").mkdir(parents=True)
        (farm / "scripts" / "ch1" / "item1" / "script.md").write_text(
            "HOOK:\nSCENES:\n[]", encoding="utf-8")
        (farm / "queue.json").write_text(json.dumps({"items": [{
            "item_id": "item1", "channel_id": "ch1",
            "title": "My Topic", "status": status,
        }]}), encoding="utf-8")

    def test_loads_matching_drafted(self, tmp_path):
        from omnicast.pipeline.steps import _load_farm_script
        self._seed(tmp_path)
        assert _load_farm_script(tmp_path, "ch1", "my topic  ").startswith("HOOK:")

    def test_ignores_queued_and_wrong_topic(self, tmp_path):
        from omnicast.pipeline.steps import _load_farm_script
        self._seed(tmp_path, status="queued")
        assert _load_farm_script(tmp_path, "ch1", "My Topic") == ""
        self._seed_status_update(tmp_path)
        assert _load_farm_script(tmp_path, "ch1", "Other Topic") == ""
        assert _load_farm_script(tmp_path, "ch2", "My Topic") == ""

    def _seed_status_update(self, root: Path) -> None:
        farm = root / "scriptfarm"
        (farm / "queue.json").write_text(json.dumps({"items": [{
            "item_id": "item1", "channel_id": "ch1",
            "title": "My Topic", "status": "drafted",
        }]}), encoding="utf-8")

    def test_missing_farm_is_silent(self, tmp_path):
        from omnicast.pipeline.steps import _load_farm_script
        assert _load_farm_script(tmp_path, "ch1", "My Topic") == ""
