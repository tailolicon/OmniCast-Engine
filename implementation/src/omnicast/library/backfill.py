"""Backfill: sweep everything reup ever produced into review-able proposals.

Three places hold traces of past work, none of them complete on their own:

    reup_jobs (vault.db)        — lifecycle rows; know channel + titles + paths
    output/products/*/*/meta.json — delivered videos (kind == "reup")
    output/reup/<aweme_id>/     — workspaces, incl. jobs that died mid-way

`scan()` merges the three by aweme_id, groups by (author, base title) and
returns PROPOSALS — nothing is written. The operator reviews the grouping in
the UI (episode numbers the parser could not find, channels, series names)
and `commit()` turns approved groups into series + episode rows.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from omnicast.library import store
from omnicast.library.titles import base_title, group_key, parse_episode
from omnicast.storage.products import OUTPUT_DIR, iter_products, read_meta
from omnicast.vault.db import _connect

REUP_WORKSPACE = OUTPUT_DIR / "reup"


def _job_rows(path: Path | None) -> list[dict]:
    from omnicast.reup import vault_link

    vault_link.init_reup_tables(path)
    with _connect(path) as conn:
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM reup_jobs").fetchall()]
        except Exception:
            return []


def _read_manifest_title(workspace: Path) -> dict:
    """Best-effort title/author from a workspace's download manifest."""
    candidates = [workspace / "download_manifest.jsonl"]
    try:
        candidates += sorted(workspace.glob("*/download_manifest.jsonl"))[:3]
    except OSError:
        pass
    for manifest in candidates:
        try:
            if not manifest.is_file():
                continue
            first = manifest.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            if not first:
                continue
            row = json.loads(first[0])
            return {
                "title": str(row.get("desc") or ""),
                "author": str(row.get("author_name") or ""),
                "aweme_id": str(row.get("aweme_id") or ""),
            }
        except Exception:
            continue
    return {}


def _job_status_suggest(job: dict) -> str:
    if str(job.get("exported_video_path") or ""):
        return "exported"
    if int(job.get("review_pending") or 0) > 0:
        return "review"
    if str(job.get("status") or "") == "failed":
        return "failed"
    return "processing"


def scan(*, path: Path | None = None, products_root: Path | None = None,
         workspace_root: Path | None = None) -> dict:
    """Collect + group everything. Read-only."""
    store.init_library_tables(path)

    # what the library already claims, to mark duplicates instead of re-proposing
    with _connect(path) as conn:
        try:
            claimed = [dict(r) for r in conn.execute(
                "SELECT episode_id, series_id, ep_no, source_aweme_id, reup_job_id, product_dir "
                "FROM series_episodes"
            ).fetchall()]
        except Exception:
            claimed = []
    claimed_by_aweme = {c["source_aweme_id"]: c for c in claimed if c["source_aweme_id"]}
    claimed_by_job = {c["reup_job_id"]: c for c in claimed if c["reup_job_id"]}
    claimed_by_product = {c["product_dir"]: c for c in claimed if c["product_dir"]}

    items: dict[str, dict] = {}

    def _merge(key: str, **fields) -> dict:
        item = items.setdefault(key, {
            "key": key, "aweme_id": "", "title": "", "title_vi": "", "author": "",
            "channel_id": "", "reup_job_id": "", "job_status": "",
            "product_dir": "", "video_path": "", "video_exists": False,
            "source_url": "", "status_suggest": "",
        })
        for k, v in fields.items():
            if v not in (None, "", False) and not item.get(k):
                item[k] = v
            elif k == "video_exists" and v:
                item[k] = True
        return item

    # 1) vault job rows — richest source
    for job in _job_rows(path):
        aweme = str(job.get("aweme_id") or "")
        key = f"aweme:{aweme}" if aweme else f"job:{job['job_id']}"
        exported = str(job.get("exported_video_path") or "")
        _merge(
            key,
            aweme_id=aweme,
            title=str(job.get("title") or ""),
            title_vi=str(job.get("title_vi") or ""),
            author=str(job.get("author_name") or ""),
            channel_id=str(job.get("channel_id") or ""),
            reup_job_id=str(job.get("job_id") or ""),
            job_status=str(job.get("status") or ""),
            source_url=str(job.get("source_url") or ""),
            video_path=exported,
            video_exists=bool(exported and Path(exported).is_file()),
            status_suggest=_job_status_suggest(job),
        )

    # 2) delivered products
    products_base = products_root  # None → storage.products default tree
    for pd in iter_products() if products_base is None else _iter_products_at(products_base):
        meta = read_meta(pd)
        if str(meta.get("kind") or "") != "reup":
            continue
        aweme = str(meta.get("source_aweme_id") or "")
        key = f"aweme:{aweme}" if aweme else f"product:{pd}"
        channel = str(meta.get("channel") or pd.parent.name)
        if channel == "_chua_gan_kenh":
            channel = ""
        video = pd / "video.mp4"
        _merge(
            key,
            aweme_id=aweme,
            title=str(meta.get("title") or ""),
            channel_id=channel,
            product_dir=str(pd),
            video_path=str(video) if video.is_file() else "",
            video_exists=video.is_file(),
            source_url=str(meta.get("source_url") or ""),
            status_suggest="exported" if video.is_file() else "",
        )

    # 3) orphan workspaces (crashed before any row/product existed)
    ws_root = workspace_root or REUP_WORKSPACE
    known_awemes = {i["aweme_id"] for i in items.values() if i["aweme_id"]}
    if ws_root.is_dir():
        for ws in sorted(ws_root.iterdir()):
            if not ws.is_dir() or ws.name.startswith("_"):
                continue
            if ws.name in known_awemes:
                continue
            info = _read_manifest_title(ws)
            aweme = info.get("aweme_id") or (ws.name if ws.name.isdigit() else "")
            if aweme and aweme in known_awemes:
                continue
            key = f"aweme:{aweme}" if aweme else f"workspace:{ws}"
            _merge(
                key,
                aweme_id=aweme,
                title=info.get("title") or "",
                author=info.get("author") or "",
                status_suggest="processing",
            )

    # annotate: parse episodes + mark items the library already knows
    already = 0
    for item in items.values():
        cleaned, ep = parse_episode(item["title"])
        if ep is None and item["title_vi"]:
            cleaned_vi, ep = parse_episode(item["title_vi"])
        item["guessed_ep"] = ep
        # A job row may say "processing" while the product's video.mp4 is
        # sitting right there — the file wins.
        if item["video_exists"]:
            item["status_suggest"] = "exported"
        item["guessed_base"] = base_title(item["title"], item["title_vi"])
        claim = (
            claimed_by_aweme.get(item["aweme_id"])
            or claimed_by_job.get(item["reup_job_id"])
            or claimed_by_product.get(item["product_dir"])
        )
        if claim:
            item["already_episode"] = {
                "series_id": claim["series_id"], "ep_no": claim["ep_no"],
            }
            already += 1
        else:
            item["already_episode"] = None

    # group the unclaimed ones
    groups: dict[str, dict] = {}
    for item in items.values():
        if item["already_episode"]:
            continue
        gkey = group_key(item["author"], item["title"], item["title_vi"])
        group = groups.setdefault(gkey, {
            "group_key": gkey,
            "suggest_title": "",
            "suggest_author": item["author"],
            "suggest_channel_id": "",
            "items": [],
        })
        if not group["suggest_title"] and item["guessed_base"]:
            group["suggest_title"] = item["guessed_base"]
        group["items"].append(item)

    # Product meta.json carries no author, so a product-only item lands in an
    # author-less bucket. When exactly ONE author group shares its base title,
    # fold it in — same show, the job row just got lost along the way.
    by_base: dict[str, list[str]] = {}
    for gkey in groups:
        base = gkey.split("::", 1)[1]
        by_base.setdefault(base, []).append(gkey)
    for base, keys in by_base.items():
        if base == "khongro":
            continue
        anonymous = [k for k in keys if k.startswith("::")]
        named = [k for k in keys if not k.startswith("::")]
        if anonymous and len(named) == 1:
            target = groups[named[0]]
            for k in anonymous:
                target["items"].extend(groups.pop(k)["items"])

    for group in groups.values():
        channels = Counter(i["channel_id"] for i in group["items"] if i["channel_id"])
        group["suggest_channel_id"] = channels.most_common(1)[0][0] if channels else ""
        group["items"].sort(
            key=lambda i: (i["guessed_ep"] is None, i["guessed_ep"] or 0, i["aweme_id"])
        )
        if not group["suggest_title"]:
            group["suggest_title"] = group["items"][0]["title"] or group["items"][0]["aweme_id"] or "Chưa rõ tên"

    ordered = sorted(groups.values(), key=lambda g: -len(g["items"]))
    return {
        "total_items": len(items),
        "already_in_library": already,
        "groups": ordered,
        "existing_series": store.list_series(path=path),
    }


def _iter_products_at(root: Path) -> list[Path]:
    out: list[Path] = []
    if root.is_dir():
        for channel_dir in root.iterdir():
            if channel_dir.is_dir():
                out.extend(d for d in channel_dir.iterdir() if d.is_dir())
    return out


def commit(payload: dict, *, path: Path | None = None) -> dict:
    """Write approved groups. Returns per-group results + conflicts skipped.

    A conflict is never guessed away: an episode number already held by a
    DIFFERENT video, or a video already claimed by another series, is
    reported and skipped so the operator resolves it by hand.
    """
    store.init_library_tables(path)
    created_series, created_eps, updated_eps = [], 0, 0
    conflicts: list[dict] = []

    for group in payload.get("groups") or []:
        sinfo = dict(group.get("series") or {})
        episodes = list(group.get("episodes") or [])
        if not episodes:
            continue
        series = None
        sid = str(sinfo.get("series_id") or "").strip()
        if sid:
            series = store.get_series(sid, path=path)
        if series is None:
            series = store.create_series(
                str(sinfo.get("title") or "Chưa rõ tên"),
                series_id=sid or None,
                channel_id=str(sinfo.get("channel_id") or ""),
                source_author=str(sinfo.get("source_author") or ""),
                source_url=str(sinfo.get("source_url") or ""),
                title_source=str(sinfo.get("title_source") or ""),
                path=path,
            )
            created_series.append(series["series_id"])
        series_id = series["series_id"]

        for ep in episodes:
            ep_no = ep.get("ep_no")
            if ep_no in (None, ""):
                conflicts.append({
                    "series_id": series_id, "reason": "missing_ep_no",
                    "title": ep.get("title") or ep.get("title_vi") or "",
                    "aweme_id": ep.get("aweme_id") or "",
                })
                continue
            aweme = str(ep.get("aweme_id") or "")
            if aweme:
                other = store.find_episode(aweme_id=aweme, path=path)
                if other and other["series_id"] != series_id:
                    conflicts.append({
                        "series_id": series_id, "reason": "aweme_in_other_series",
                        "aweme_id": aweme, "other_series": other["series_id"],
                        "other_ep": other["ep_no"],
                    })
                    continue
            existing = next(
                (e for e in store.list_episodes(series_id, path=path)
                 if e["ep_no"] == int(ep_no)),
                None,
            )
            if existing and aweme and existing["source_aweme_id"] and \
                    existing["source_aweme_id"] != aweme:
                conflicts.append({
                    "series_id": series_id, "reason": "ep_no_taken",
                    "ep_no": int(ep_no), "aweme_id": aweme,
                    "holder_aweme": existing["source_aweme_id"],
                })
                continue
            row = store.upsert_episode(
                series_id, int(ep_no),
                title=str(ep.get("title") or ""),
                title_vi=str(ep.get("title_vi") or ""),
                source_aweme_id=aweme,
                source_url=str(ep.get("source_url") or ""),
                reup_job_id=str(ep.get("reup_job_id") or ""),
                product_dir=str(ep.get("product_dir") or ""),
                video_path=str(ep.get("video_path") or ""),
                status=str(ep.get("status") or "") or None,
                path=path,
            )
            if existing:
                updated_eps += 1
            else:
                created_eps += 1
            # stamp the product folder so the filesystem agrees with the DB
            pd = str(ep.get("product_dir") or "")
            if pd:
                try:
                    from omnicast.storage.products import write_meta

                    write_meta(Path(pd), series_id=series_id, episode_no=int(ep_no))
                except Exception:
                    pass

    return {
        "created_series": created_series,
        "created_episodes": created_eps,
        "updated_episodes": updated_eps,
        "conflicts": conflicts,
    }
