"""The shared source→episode apply loop (used by both Douyin and Bilibili sync)."""
from pathlib import Path

import pytest

from omnicast.library import store
from omnicast.library.source_sync import _apply_entries


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "vault.db"


def _entries():
    return [
        {"sid": "BV1xx411c7mD_p1", "title": "第1集", "url": "https://b/1?p=1", "position": 1},
        {"sid": "BV1xx411c7mD_p2", "title": "第2集", "url": "https://b/1?p=2", "position": 2},
        # no number in the title → falls back to its position in the list
        {"sid": "BV1xx411c7mD_p3", "title": "大结局", "url": "https://b/1?p=3", "position": 3},
    ]


def test_apply_creates_planned_episodes_with_source_ids(db):
    s = store.create_series("Tu Tiên", path=db)
    result = _apply_entries(s["series_id"], _entries(), path=db)
    assert (result["created"], result["updated"]) == (3, 0)
    eps = store.list_episodes(s["series_id"], path=db)
    assert [e["ep_no"] for e in eps] == [1, 2, 3]
    assert all(e["status"] == "planned" for e in eps)
    assert eps[2]["source_aweme_id"] == "BV1xx411c7mD_p3"
    assert eps[1]["source_url"].endswith("?p=2")


def test_apply_is_idempotent_and_fills_manual_rows(db):
    s = store.create_series("Tu Tiên", path=db)
    # the operator added ep 2 by hand before ever syncing the source
    store.upsert_episode(s["series_id"], 2, status="exported", path=db)
    first = _apply_entries(s["series_id"], _entries(), path=db)
    assert first["created"] == 2 and first["updated"] == 1
    again = _apply_entries(s["series_id"], _entries(), path=db)
    assert again["created"] == 0 and again["conflicts"] == []
    eps = store.list_episodes(s["series_id"], path=db)
    assert len(eps) == 3
    # the manual row kept its production status but gained the source link
    ep2 = next(e for e in eps if e["ep_no"] == 2)
    assert ep2["status"] == "exported"
    assert ep2["source_aweme_id"] == "BV1xx411c7mD_p2"


def test_apply_reports_conflicts_instead_of_stealing_an_episode(db):
    s = store.create_series("Tu Tiên", path=db)
    store.upsert_episode(s["series_id"], 1, source_aweme_id="OTHER", path=db)
    result = _apply_entries(s["series_id"], _entries()[:1], path=db)
    assert result["created"] == 0
    assert result["conflicts"][0]["ep_no"] == 1
    assert result["conflicts"][0]["holder_sid"] == "OTHER"


def test_sync_series_source_dispatches_to_bilibili(db, monkeypatch):
    """A bilibili source_url routes to the bilibili lister and stamps the series."""
    import omnicast.ingest.bilibili as bili
    from omnicast.library import source_sync

    monkeypatch.setattr(
        bili, "fetch_series_entries",
        lambda url, cookies=None, proxy="": {
            "title": "《修仙》", "author": "作者A", "entries": _entries(),
        },
    )
    s = store.create_series(
        "Tu Tiên", source_url="https://www.bilibili.com/video/BV1xx411c7mD", path=db
    )
    result = source_sync.sync_series_source_sync(s["series_id"], path=db)
    assert result["platform"] == "bilibili"
    assert result["source_count"] == 3
    assert result["episodes_created"] == 3
    srow = store.get_series(s["series_id"], path=db)
    assert srow["source_platform"] == "bilibili"
    assert srow["title_source"] == "《修仙》"
    assert srow["source_author"] == "作者A"
    assert srow["source_episode_count"] == 3


def test_bilibili_source_id_snaps_a_finished_job(db):
    """A dub job whose source id matches a planned row links itself up."""
    from omnicast.reup import vault_link
    from omnicast.vault.db import _connect

    s = store.create_series("Tu Tiên", path=db)
    _apply_entries(s["series_id"], _entries(), path=db)

    vault_link.register_job("job-b1", "https://www.bilibili.com/video/BV1xx411c7mD?p=2", path=db)
    with _connect(db) as conn:
        conn.execute(
            "UPDATE reup_jobs SET aweme_id=?, title=?, status='done' WHERE job_id=?",
            ("BV1xx411c7mD_p2", "第2集", "job-b1"),
        )
        row = conn.execute("SELECT source_platform FROM reup_jobs WHERE job_id='job-b1'").fetchone()
    assert row["source_platform"] == "bilibili"   # stamped by register_job

    ep = store.sync_episode_from_job("job-b1", path=db)
    assert ep is not None and ep["ep_no"] == 2
    assert ep["reup_job_id"] == "job-b1"
