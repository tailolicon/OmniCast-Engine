"""Library store — schema, CRUD, rollups, reup-job sync."""
from pathlib import Path

import pytest

from omnicast.library import store
from omnicast.reup import vault_link
from omnicast.vault.db import _connect


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "vault.db"


def test_series_crud_and_slug_dedupe(db):
    s1 = store.create_series("Khi Dot Do", channel_id="phim_a", path=db)
    s2 = store.create_series("Khi Dot Do", path=db)      # same title, new show
    assert s1["series_id"] == "khi_dot_do"
    assert s2["series_id"] == "khi_dot_do_2"

    updated = store.update_series(s1["series_id"], source_episode_count=40, path=db)
    assert updated["source_episode_count"] == 40
    assert store.get_series("khong_ton_tai", path=db) is None
    with pytest.raises(KeyError):
        store.update_series("khong_ton_tai", note="x", path=db)


def test_episode_upsert_merges_without_blanking(db):
    s = store.create_series("Show", path=db)
    e1 = store.upsert_episode(s["series_id"], 1, source_aweme_id="111",
                              title="第1集", path=db)
    # second writer knows the file but not the source — must not blank aweme
    e2 = store.upsert_episode(s["series_id"], 1, video_path="/x/video.mp4", path=db)
    assert e1["episode_id"] == e2["episode_id"]
    assert e2["source_aweme_id"] == "111"
    assert e2["video_path"] == "/x/video.mp4"

    # explicit patch CAN blank (unlink)
    e3 = store.update_episode(e2["episode_id"], source_aweme_id="", path=db)
    assert e3["source_aweme_id"] == ""

    with pytest.raises(KeyError):
        store.upsert_episode("khong_co", 1, path=db)


def test_posts_and_overview_rollup(db):
    s = store.create_series("Show", channel_id="phim_a", path=db)
    store.update_series(s["series_id"], source_episode_count=40, path=db)
    ep1 = store.upsert_episode(s["series_id"], 1, status="exported", path=db)
    store.upsert_episode(s["series_id"], 2, status="exported", path=db)
    store.upsert_episode(s["series_id"], 3, path=db)          # planned

    yt = store.create_account("youtube", "Kênh Phim A", channel_id="phim_a", path=db)
    store.create_account("tiktok", "TT Phim A", channel_id="phim_a", path=db)
    store.set_post(ep1["episode_id"], yt["account_id"],
                   post_url="https://youtu.be/x", path=db)

    ov = store.series_overview(path=db)
    assert len(ov) == 1
    row = ov[0]
    assert row["ep_total"] == 3
    assert row["ep_exported"] == 2
    assert row["ep_planned"] == 1
    assert row["missing_source"] == 38          # 40 at source − 2 dubbed
    assert row["posted"] == {"youtube": 1}

    # untick
    store.delete_post(ep1["episode_id"], yt["account_id"], path=db)
    assert store.series_overview(path=db)[0]["posted"] == {}


def test_post_upsert_keeps_url_when_reticked_without_one(db):
    s = store.create_series("Show", path=db)
    ep = store.upsert_episode(s["series_id"], 1, path=db)
    acc = store.create_account("tiktok", "TT", path=db)
    store.set_post(ep["episode_id"], acc["account_id"],
                   post_url="https://tiktok.com/v/1", path=db)
    again = store.set_post(ep["episode_id"], acc["account_id"], path=db)
    assert again["post_url"] == "https://tiktok.com/v/1"


def test_single_bucket_auto_numbers_and_series_kind_refuses(db):
    """'Video lẻ' buckets take the next slot; phim bộ must state its episode."""
    bucket = store.create_series("Video lẻ kênh A", kind="single", path=db)
    e1 = store.attach_job_to_episode("job-a", bucket["series_id"], None, path=db)
    e2 = store.attach_job_to_episode("job-b", bucket["series_id"], None, path=db)
    assert (e1["ep_no"], e2["ep_no"]) == (1, 2)

    show = store.create_series("Phim bộ", path=db)  # kind mặc định 'series'
    with pytest.raises(ValueError):
        store.attach_job_to_episode("job-c", show["series_id"], None, path=db)


def test_kind_column_migrates_old_databases(db):
    """DBs created before `kind` existed gain the column on first touch."""
    with _connect(db) as conn:
        conn.execute(
            "CREATE TABLE series ("
            "series_id TEXT PRIMARY KEY, title TEXT NOT NULL, "
            "title_source TEXT NOT NULL DEFAULT '', channel_id TEXT NOT NULL DEFAULT '', "
            "source_platform TEXT NOT NULL DEFAULT 'douyin', "
            "source_author TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '', "
            "source_mix_id TEXT NOT NULL DEFAULT '', "
            "source_episode_count INTEGER NOT NULL DEFAULT 0, "
            "source_synced_at TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'active', note TEXT NOT NULL DEFAULT '', "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO series (series_id, title, created_at, updated_at) "
            "VALUES ('old_show', 'Old', 't', 't')"
        )
    row = store.get_series("old_show", path=db)   # init runs the ALTER
    assert row is not None and row["kind"] == "series"
    single = store.create_series("Lẻ", kind="single", path=db)
    assert single["kind"] == "single"


def _fake_finished_job(db, job_id: str, *, aweme: str, exported: str,
                       title: str = "", title_vi: str = "") -> None:
    """Register a job then force the columns a finished run would have."""
    vault_link.register_job(job_id, f"https://v.douyin.com/{aweme}", path=db)
    with _connect(db) as conn:
        conn.execute(
            "UPDATE reup_jobs SET aweme_id=?, title=?, title_vi=?, "
            "exported_video_path=?, status='done' WHERE job_id=?",
            (aweme, title, title_vi, exported, job_id),
        )


def test_sync_episode_from_job_by_job_link(db, tmp_path):
    product = tmp_path / "products" / "phim_a" / "20260809_0001_tap5"
    product.mkdir(parents=True)
    (product / "meta.json").write_text("{}", encoding="utf-8")
    video = product / "video.mp4"
    video.write_bytes(b"x")

    s = store.create_series("Show", channel_id="phim_a", path=db)
    store.attach_job_to_episode("job-1", s["series_id"], 5,
                                source_url="https://v.douyin.com/abc", path=db)
    _fake_finished_job(db, "job-1", aweme="777", exported=str(video),
                       title="《Show》第5集", title_vi="Show tập 5")

    ep = store.sync_episode_from_job("job-1", path=db)
    assert ep is not None
    assert ep["status"] == "exported"
    assert ep["source_aweme_id"] == "777"
    assert ep["video_path"] == str(video)
    assert ep["product_dir"] == str(product)
    # the folder itself got stamped
    import json

    meta = json.loads((product / "meta.json").read_text(encoding="utf-8"))
    assert meta["series_id"] == s["series_id"]
    assert meta["episode_no"] == 5


def test_sync_episode_from_job_snaps_by_aweme(db):
    s = store.create_series("Show", path=db)
    store.upsert_episode(s["series_id"], 9, source_aweme_id="888", path=db)  # planned by source-sync
    _fake_finished_job(db, "job-2", aweme="888", exported="")

    ep = store.sync_episode_from_job("job-2", path=db)
    assert ep is not None
    assert ep["ep_no"] == 9
    assert ep["reup_job_id"] == "job-2"
    assert ep["status"] == "processing"      # no export yet

    # a job nobody claims stays unclaimed
    _fake_finished_job(db, "job-3", aweme="999", exported="")
    assert store.sync_episode_from_job("job-3", path=db) is None
    assert "job-3" in store.unassigned_job_ids(path=db)
