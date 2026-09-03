"""farm_narrative.py — pure-helper contracts (no git, no LLM, no subprocess)."""

import importlib.util
import json
import types
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "farm_narrative",
    Path(__file__).resolve().parents[2] / "scripts" / "farm_narrative.py",
)
farm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(farm)


def _plan_item(story_id: str = "story_1", title: str = "The Night Clerk"):
    return types.SimpleNamespace(story_id=story_id, title=title)


class TestSlugify:
    def test_ascii_lowercase_dashes(self):
        assert farm.slugify("Overnight Hotel, Front Desk!") == \
            "overnight-hotel-front-desk"

    def test_unicode_stripped(self):
        assert farm.slugify("khách sạn đêm") == "khach-san-em"

    def test_bounded_and_nonempty(self):
        assert len(farm.slugify("x" * 300)) <= 60
        assert farm.slugify("!!!") == "untitled"


class TestQueueItem:
    def test_satisfies_ci_queue_assertions(self):
        item = farm.build_queue_item(
            "20260903_test-nu", "true_dread_files_us", "some topic",
            ["scriptfarm/narrative/20260903_test-nu/story_1.prompt.md"],
            ["scriptfarm/narrative/20260903_test-nu/story_1.md"])
        # The exact invariants .github/workflows/validate-scriptfarm.yml asserts:
        assert item["item_id"] and item["channel_id"] and item["title"]
        assert item["status"] in ("queued", "drafted", "approved", "rejected")
        assert item["type"] == "narrative"
        json.dumps(item)  # must be JSON-serializable as-is


class TestNormalizeDraft:
    def test_plain_prose_gets_plan_title(self):
        text = "I took the job in October.\n\nThe lobby was empty."
        draft = farm.normalize_draft(text, _plan_item())
        assert draft.startswith("[The Night Clerk]\n\n")
        assert "The lobby was empty." in draft

    def test_json_payload_title_wins(self):
        payload = json.dumps({
            "title": "Room 114 Never Checked Out",
            "hook_candidates": ["The guest ledger said nobody."],
            "narration": "The first week was quiet.\n\nThen the phone rang.",
        })
        draft = farm.normalize_draft(payload, _plan_item())
        assert draft.startswith("[Room 114 Never Checked Out]\n\n")
        assert draft.rstrip().endswith("Then the phone rang.")

    def test_round_trips_through_load_draft_file(self, tmp_path):
        from omnicast.agents.narrative_pipeline import load_draft_file
        draft = farm.normalize_draft(
            "TITLE: The Second Key\nNARRATION:\nNobody used the annex.",
            _plan_item())
        path = tmp_path / "draft.txt"
        path.write_text(draft, encoding="utf-8")
        loaded = load_draft_file(path, _plan_item())
        assert loaded.title == "The Second Key"
        assert loaded.narration == "Nobody used the annex."
        assert loaded.story_id == "story_1"

    def test_empty_answer_raises(self):
        with pytest.raises(Exception):
            farm.normalize_draft("", _plan_item())


class TestSelectDraftedItem:
    def _queue(self):
        return {"items": [
            {"item_id": "a", "type": "narrative", "status": "queued",
             "channel_id": "ch1", "added_at": "2026-09-01T00:00:00+00:00"},
            {"item_id": "b", "type": "narrative", "status": "drafted",
             "channel_id": "ch1", "added_at": "2026-09-03T00:00:00+00:00"},
            {"item_id": "c", "type": "narrative", "status": "drafted",
             "channel_id": "ch2", "added_at": "2026-09-02T00:00:00+00:00"},
            {"item_id": "d", "status": "drafted", "channel_id": "ch1",
             "added_at": "2026-09-01T00:00:00+00:00"},  # plain farm item
        ]}

    def test_oldest_drafted_narrative_wins(self):
        assert farm.select_drafted_item(self._queue())["item_id"] == "c"

    def test_channel_filter(self):
        assert farm.select_drafted_item(
            self._queue(), channel_id="ch1")["item_id"] == "b"

    def test_pinned_item_may_still_be_queued(self):
        assert farm.select_drafted_item(
            self._queue(), item_id="a")["item_id"] == "a"

    def test_unpinned_never_returns_queued_or_plain_items(self):
        queue = {"items": [item for item in self._queue()["items"]
                           if item["item_id"] in ("a", "d")]}
        assert farm.select_drafted_item(queue) is None
