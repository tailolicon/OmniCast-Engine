"""Backfill scanner — merge, grouping, commit, conflicts."""
import json
from pathlib import Path

import pytest

from omnicast.library import backfill, store
from omnicast.reup import vault_link
from omnicast.vault.db import _connect


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "vault.db"
    products = tmp_path / "products"
    workspace = tmp_path / "reup_ws"
    products.mkdir()
    workspace.mkdir()
    return db, products, workspace


def _job(db, job_id, *, aweme, title, author="作者A", channel="", exported="",
         status="done"):
    vault_link.register_job(job_id, f"https://www.douyin.com/video/{aweme}",
                            channel_id=channel or None, path=db)
    with _connect(db) as conn:
        conn.execute(
            "UPDATE reup_jobs SET aweme_id=?, title=?, author_name=?, "
            "exported_video_path=?, status=? WHERE job_id=?",
            (aweme, title, author, exported, status, job_id),
        )


def _product(products: Path, channel: str, slug: str, *, aweme, title) -> Path:
    pd = products / channel / slug
    pd.mkdir(parents=True)
    (pd / "video.mp4").write_bytes(b"v")
    (pd / "meta.json").write_text(json.dumps({
        "kind": "reup", "channel": channel, "title": title,
        "source_aweme_id": aweme,
    }, ensure_ascii=False), encoding="utf-8")
    return pd


def test_scan_merges_and_groups(env):
    db, products, workspace = env
    # two finished jobs of the same show
    _job(db, "job-1", aweme="101", title="《红魔猩猩》第1集 #科幻", channel="phim_a")
    _job(db, "job-2", aweme="102", title="《红魔猩猩》第2集", channel="phim_a")
    # episode 3 only exists as a delivered product (job row lost)
    _product(products, "phim_a", "20260801_0001_tap3",
             aweme="103", title="《红魔猩猩》第3集")
    # an unrelated show from another author
    _job(db, "job-9", aweme="900", title="《斗罗》第7集", author="作者B")
    # an orphan workspace with a manifest
    ws = workspace / "555"
    ws.mkdir()
    (ws / "download_manifest.jsonl").write_text(
        json.dumps({"aweme_id": "555", "desc": "《红魔猩猩》第4集",
                    "author_name": "作者A"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = backfill.scan(path=db, products_root=products, workspace_root=workspace)
    assert result["total_items"] == 5
    assert result["already_in_library"] == 0
    groups = result["groups"]
    assert len(groups) == 2

    main = next(g for g in groups if len(g["items"]) == 4)
    assert main["suggest_title"] == "红魔猩猩"
    assert main["suggest_channel_id"] == "phim_a"
    assert [i["guessed_ep"] for i in main["items"]] == [1, 2, 3, 4]


def test_commit_creates_and_second_scan_marks_claimed(env):
    db, products, workspace = env
    _job(db, "job-1", aweme="101", title="《红魔猩猩》第1集", channel="phim_a")
    pd = _product(products, "phim_a", "20260801_0001_tap2",
                  aweme="102", title="《红魔猩猩》第2集")

    scanned = backfill.scan(path=db, products_root=products, workspace_root=workspace)
    group = scanned["groups"][0]
    payload = {"groups": [{
        "series": {"title": group["suggest_title"],
                   "channel_id": group["suggest_channel_id"],
                   "source_author": group["suggest_author"]},
        "episodes": [
            {"ep_no": i["guessed_ep"], "aweme_id": i["aweme_id"],
             "title": i["title"], "title_vi": i["title_vi"],
             "reup_job_id": i["reup_job_id"], "product_dir": i["product_dir"],
             "video_path": i["video_path"],
             "status": i["status_suggest"] or None}
            for i in group["items"]
        ],
    }]}
    result = backfill.commit(payload, path=db)
    assert result["created_episodes"] == 2
    assert result["conflicts"] == []
    sid = result["created_series"][0]
    eps = store.list_episodes(sid, path=db)
    assert [e["ep_no"] for e in eps] == [1, 2]
    # product folder stamped
    meta = json.loads((pd / "meta.json").read_text(encoding="utf-8"))
    assert meta["series_id"] == sid and meta["episode_no"] == 2

    again = backfill.scan(path=db, products_root=products, workspace_root=workspace)
    assert again["already_in_library"] == 2
    assert again["groups"] == []


def test_commit_reports_conflicts_instead_of_guessing(env):
    db, _, _ = env
    s = store.create_series("红魔猩猩", path=db)
    store.upsert_episode(s["series_id"], 1, source_aweme_id="OLD", path=db)

    result = backfill.commit({"groups": [{
        "series": {"series_id": s["series_id"], "title": "红魔猩猩"},
        "episodes": [
            {"ep_no": 1, "aweme_id": "NEW"},        # ep 1 held by OLD
            {"ep_no": None, "aweme_id": "222"},      # no episode number
        ],
    }]}, path=db)
    reasons = sorted(c["reason"] for c in result["conflicts"])
    assert reasons == ["ep_no_taken", "missing_ep_no"]
    assert result["created_episodes"] == 0
