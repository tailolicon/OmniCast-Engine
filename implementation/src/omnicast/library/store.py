"""Library tables in vault.db + CRUD.

Model:
    series            one show/drama being reupped (owned by one logical channel)
    series_episodes   one episode of a series; links to the reup job + product
    platform_accounts a channel's presence on one platform (YT/TikTok/FB account)
    episode_posts     episode × account — where each episode actually got posted

Episode status is the PRODUCTION state (planned → queued → processing →
review → exported, or failed). Distribution state lives in episode_posts,
one row per platform account, so "dubbed but never posted to TikTok" is a
query, not a memory exercise.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from omnicast.vault.db import _connect
from omnicast.library.titles import series_slug

PLATFORMS = ("youtube", "tiktok", "facebook", "douyin", "other")

EPISODE_STATUSES = ("planned", "queued", "processing", "review", "exported", "failed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    series_id            TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    title_source         TEXT NOT NULL DEFAULT '',
    -- 'series' = phim bộ (episode numbers mean something);
    -- 'single' = bucket of one-off videos (ep_no is just an internal ordinal,
    --            the UI shows titles instead of "Tập N")
    kind                 TEXT NOT NULL DEFAULT 'series',
    channel_id           TEXT NOT NULL DEFAULT '',
    source_platform      TEXT NOT NULL DEFAULT 'douyin',
    source_author        TEXT NOT NULL DEFAULT '',
    source_url           TEXT NOT NULL DEFAULT '',
    source_mix_id        TEXT NOT NULL DEFAULT '',
    source_episode_count INTEGER NOT NULL DEFAULT 0,
    source_synced_at     TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'active',
    note                 TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_series_channel ON series(channel_id);

CREATE TABLE IF NOT EXISTS series_episodes (
    episode_id      TEXT PRIMARY KEY,
    series_id       TEXT NOT NULL REFERENCES series(series_id),
    ep_no           INTEGER NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    title_vi        TEXT NOT NULL DEFAULT '',
    source_aweme_id TEXT NOT NULL DEFAULT '',
    source_url      TEXT NOT NULL DEFAULT '',
    reup_job_id     TEXT NOT NULL DEFAULT '',
    product_dir     TEXT NOT NULL DEFAULT '',
    video_path      TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'planned',
    note            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(series_id, ep_no)
);
CREATE INDEX IF NOT EXISTS idx_lib_ep_series ON series_episodes(series_id);
CREATE INDEX IF NOT EXISTS idx_lib_ep_aweme  ON series_episodes(source_aweme_id);
CREATE INDEX IF NOT EXISTS idx_lib_ep_job    ON series_episodes(reup_job_id);

CREATE TABLE IF NOT EXISTS platform_accounts (
    account_id  TEXT PRIMARY KEY,
    platform    TEXT NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    channel_id  TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lib_acc_platform ON platform_accounts(platform);
CREATE INDEX IF NOT EXISTS idx_lib_acc_channel  ON platform_accounts(channel_id);

CREATE TABLE IF NOT EXISTS episode_posts (
    episode_id       TEXT NOT NULL REFERENCES series_episodes(episode_id),
    account_id       TEXT NOT NULL REFERENCES platform_accounts(account_id),
    status           TEXT NOT NULL DEFAULT 'posted',
    post_url         TEXT NOT NULL DEFAULT '',
    external_post_id TEXT NOT NULL DEFAULT '',
    posted_at        TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT 'manual',
    note             TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (episode_id, account_id)
);
CREATE INDEX IF NOT EXISTS idx_lib_posts_account ON episode_posts(account_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SERIES_KINDS = ("series", "single")


def init_library_tables(path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.executescript(SCHEMA)
        # `kind` landed after the first Vòng-4 DBs were created; ALTER keeps them.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(series)")}
        if "kind" not in existing:
            conn.execute(
                "ALTER TABLE series ADD COLUMN kind TEXT NOT NULL DEFAULT 'series'"
            )


def _rows(conn, query: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def _row(conn, query: str, params: tuple = ()) -> dict | None:
    r = conn.execute(query, params).fetchone()
    return dict(r) if r else None


# ── series ──────────────────────────────────────────────────────────────────

_SERIES_FIELDS = {
    "title", "title_source", "kind", "channel_id", "source_platform",
    "source_author", "source_url", "source_mix_id", "source_episode_count",
    "source_synced_at", "status", "note",
}


def create_series(
    title: str,
    *,
    series_id: str | None = None,
    path: Path | None = None,
    **fields,
) -> dict:
    init_library_tables(path)
    unknown = set(fields) - _SERIES_FIELDS
    if unknown:
        raise ValueError(f"unknown series fields: {sorted(unknown)}")
    now = _now()
    with _connect(path) as conn:
        sid = series_id or series_slug(title, str(fields.get("source_author") or ""))
        # slug collisions get a numeric tail instead of clobbering a sibling show
        base_sid, n = sid, 2
        while _row(conn, "SELECT 1 FROM series WHERE series_id=?", (sid,)):
            sid = f"{base_sid}_{n}"
            n += 1
        row = {
            "series_id": sid, "title": title.strip() or sid,
            "created_at": now, "updated_at": now,
            **{k: fields[k] for k in fields},
        }
        cols = ", ".join(row)
        conn.execute(
            f"INSERT INTO series ({cols}) VALUES ({','.join('?' * len(row))})",
            tuple(row.values()),
        )
        return _row(conn, "SELECT * FROM series WHERE series_id=?", (sid,)) or row


def update_series(series_id: str, *, path: Path | None = None, **fields) -> dict:
    init_library_tables(path)
    unknown = set(fields) - _SERIES_FIELDS
    if unknown:
        raise ValueError(f"unknown series fields: {sorted(unknown)}")
    if not fields:
        raise ValueError("nothing to update")
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{k}=?" for k in fields)
    with _connect(path) as conn:
        cur = conn.execute(
            f"UPDATE series SET {assignments} WHERE series_id=?",
            (*fields.values(), series_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"series {series_id} not found")
        return _row(conn, "SELECT * FROM series WHERE series_id=?", (series_id,)) or {}


def get_series(series_id: str, *, path: Path | None = None) -> dict | None:
    init_library_tables(path)
    with _connect(path) as conn:
        return _row(conn, "SELECT * FROM series WHERE series_id=?", (series_id,))


def list_series(
    *, channel_id: str | None = None, status: str | None = None,
    path: Path | None = None,
) -> list[dict]:
    init_library_tables(path)
    query, params = "SELECT * FROM series", []
    clauses = []
    if channel_id:
        clauses.append("channel_id=?")
        params.append(channel_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC"
    with _connect(path) as conn:
        return _rows(conn, query, tuple(params))


def delete_series(series_id: str, *, path: Path | None = None) -> None:
    """Remove a series and everything hanging off it. Files are untouched."""
    init_library_tables(path)
    with _connect(path) as conn:
        conn.execute(
            "DELETE FROM episode_posts WHERE episode_id IN "
            "(SELECT episode_id FROM series_episodes WHERE series_id=?)",
            (series_id,),
        )
        conn.execute("DELETE FROM series_episodes WHERE series_id=?", (series_id,))
        conn.execute("DELETE FROM series WHERE series_id=?", (series_id,))


# ── episodes ────────────────────────────────────────────────────────────────

_EPISODE_FIELDS = {
    "ep_no", "title", "title_vi", "source_aweme_id", "source_url",
    "reup_job_id", "product_dir", "video_path", "status", "note",
}


def upsert_episode(
    series_id: str, ep_no: int, *, path: Path | None = None, **fields,
) -> dict:
    """Insert episode (series_id, ep_no) or merge fields into the existing row.

    Merge semantics are fill-don't-blank: an incoming empty string never
    erases a stored value, so a source-sync (which only knows the aweme) and a
    backfill commit (which only knows the file) can both touch the same row.
    """
    init_library_tables(path)
    unknown = set(fields) - _EPISODE_FIELDS
    if unknown:
        raise ValueError(f"unknown episode fields: {sorted(unknown)}")
    now = _now()
    with _connect(path) as conn:
        if not _row(conn, "SELECT 1 FROM series WHERE series_id=?", (series_id,)):
            raise KeyError(f"series {series_id} not found")
        existing = _row(
            conn,
            "SELECT * FROM series_episodes WHERE series_id=? AND ep_no=?",
            (series_id, int(ep_no)),
        )
        if existing is None:
            row = {
                "episode_id": f"ep-{uuid4().hex[:12]}",
                "series_id": series_id, "ep_no": int(ep_no),
                "created_at": now, "updated_at": now,
                **{k: v for k, v in fields.items() if v not in (None, "")},
            }
            cols = ", ".join(row)
            conn.execute(
                f"INSERT INTO series_episodes ({cols}) VALUES ({','.join('?' * len(row))})",
                tuple(row.values()),
            )
            episode_id = row["episode_id"]
        else:
            updates = {
                k: v for k, v in fields.items()
                if v not in (None, "") and v != existing.get(k)
            }
            # status may legitimately move "backward" only via explicit update_episode
            if updates:
                updates["updated_at"] = now
                assignments = ", ".join(f"{k}=?" for k in updates)
                conn.execute(
                    f"UPDATE series_episodes SET {assignments} WHERE episode_id=?",
                    (*updates.values(), existing["episode_id"]),
                )
            episode_id = existing["episode_id"]
        conn.execute("UPDATE series SET updated_at=? WHERE series_id=?", (now, series_id))
        return _row(conn, "SELECT * FROM series_episodes WHERE episode_id=?", (episode_id,)) or {}


def update_episode(episode_id: str, *, path: Path | None = None, **fields) -> dict:
    """Explicit patch — unlike upsert, empty strings DO overwrite (unlink)."""
    init_library_tables(path)
    unknown = set(fields) - _EPISODE_FIELDS
    if unknown:
        raise ValueError(f"unknown episode fields: {sorted(unknown)}")
    if not fields:
        raise ValueError("nothing to update")
    fields = dict(fields)
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{k}=?" for k in fields)
    with _connect(path) as conn:
        cur = conn.execute(
            f"UPDATE series_episodes SET {assignments} WHERE episode_id=?",
            (*fields.values(), episode_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"episode {episode_id} not found")
        return _row(conn, "SELECT * FROM series_episodes WHERE episode_id=?", (episode_id,)) or {}


def get_episode(episode_id: str, *, path: Path | None = None) -> dict | None:
    init_library_tables(path)
    with _connect(path) as conn:
        return _row(conn, "SELECT * FROM series_episodes WHERE episode_id=?", (episode_id,))


def list_episodes(series_id: str, *, path: Path | None = None) -> list[dict]:
    init_library_tables(path)
    with _connect(path) as conn:
        return _rows(
            conn,
            "SELECT * FROM series_episodes WHERE series_id=? ORDER BY ep_no",
            (series_id,),
        )


def find_episode(
    *, aweme_id: str | None = None, reup_job_id: str | None = None,
    path: Path | None = None,
) -> dict | None:
    init_library_tables(path)
    with _connect(path) as conn:
        if reup_job_id:
            row = _row(
                conn, "SELECT * FROM series_episodes WHERE reup_job_id=?", (reup_job_id,)
            )
            if row:
                return row
        if aweme_id:
            return _row(
                conn,
                "SELECT * FROM series_episodes WHERE source_aweme_id=? ORDER BY updated_at DESC",
                (str(aweme_id),),
            )
    return None


def delete_episode(episode_id: str, *, path: Path | None = None) -> None:
    init_library_tables(path)
    with _connect(path) as conn:
        conn.execute("DELETE FROM episode_posts WHERE episode_id=?", (episode_id,))
        conn.execute("DELETE FROM series_episodes WHERE episode_id=?", (episode_id,))


# ── platform accounts ───────────────────────────────────────────────────────

_ACCOUNT_FIELDS = {"platform", "name", "url", "channel_id", "external_id", "status", "note"}


def create_account(
    platform: str, name: str, *,
    account_id: str | None = None, path: Path | None = None, **fields,
) -> dict:
    init_library_tables(path)
    platform = (platform or "").strip().lower()
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    unknown = set(fields) - _ACCOUNT_FIELDS
    if unknown:
        raise ValueError(f"unknown account fields: {sorted(unknown)}")
    now = _now()
    with _connect(path) as conn:
        aid = account_id or f"{platform[:2]}_{series_slug(name)}"[:60]
        base_aid, n = aid, 2
        while _row(conn, "SELECT 1 FROM platform_accounts WHERE account_id=?", (aid,)):
            aid = f"{base_aid}_{n}"
            n += 1
        row = {
            "account_id": aid, "platform": platform, "name": name.strip() or aid,
            "created_at": now, "updated_at": now,
            **{k: fields[k] for k in fields},
        }
        cols = ", ".join(row)
        conn.execute(
            f"INSERT INTO platform_accounts ({cols}) VALUES ({','.join('?' * len(row))})",
            tuple(row.values()),
        )
        return _row(conn, "SELECT * FROM platform_accounts WHERE account_id=?", (aid,)) or row


def update_account(account_id: str, *, path: Path | None = None, **fields) -> dict:
    init_library_tables(path)
    unknown = set(fields) - _ACCOUNT_FIELDS
    if unknown:
        raise ValueError(f"unknown account fields: {sorted(unknown)}")
    if not fields:
        raise ValueError("nothing to update")
    fields = dict(fields)
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{k}=?" for k in fields)
    with _connect(path) as conn:
        cur = conn.execute(
            f"UPDATE platform_accounts SET {assignments} WHERE account_id=?",
            (*fields.values(), account_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"account {account_id} not found")
        return _row(conn, "SELECT * FROM platform_accounts WHERE account_id=?", (account_id,)) or {}


def list_accounts(
    *, platform: str | None = None, channel_id: str | None = None,
    path: Path | None = None,
) -> list[dict]:
    init_library_tables(path)
    query, params, clauses = "SELECT * FROM platform_accounts", [], []
    if platform:
        clauses.append("platform=?")
        params.append(platform)
    if channel_id:
        clauses.append("channel_id=?")
        params.append(channel_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY platform, name"
    with _connect(path) as conn:
        return _rows(conn, query, tuple(params))


def get_account(account_id: str, *, path: Path | None = None) -> dict | None:
    init_library_tables(path)
    with _connect(path) as conn:
        return _row(conn, "SELECT * FROM platform_accounts WHERE account_id=?", (account_id,))


def delete_account(account_id: str, *, path: Path | None = None) -> None:
    init_library_tables(path)
    with _connect(path) as conn:
        conn.execute("DELETE FROM episode_posts WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM platform_accounts WHERE account_id=?", (account_id,))


# ── posts ───────────────────────────────────────────────────────────────────

def set_post(
    episode_id: str, account_id: str, *,
    status: str = "posted", post_url: str = "", external_post_id: str = "",
    posted_at: str = "", source: str = "manual", note: str = "",
    path: Path | None = None,
) -> dict:
    init_library_tables(path)
    now = _now()
    with _connect(path) as conn:
        if not _row(conn, "SELECT 1 FROM series_episodes WHERE episode_id=?", (episode_id,)):
            raise KeyError(f"episode {episode_id} not found")
        if not _row(conn, "SELECT 1 FROM platform_accounts WHERE account_id=?", (account_id,)):
            raise KeyError(f"account {account_id} not found")
        conn.execute(
            """
            INSERT INTO episode_posts
                (episode_id, account_id, status, post_url, external_post_id,
                 posted_at, source, note, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(episode_id, account_id) DO UPDATE SET
                status=excluded.status,
                post_url=CASE WHEN excluded.post_url<>'' THEN excluded.post_url
                              ELSE episode_posts.post_url END,
                external_post_id=CASE WHEN excluded.external_post_id<>''
                              THEN excluded.external_post_id
                              ELSE episode_posts.external_post_id END,
                posted_at=CASE WHEN excluded.posted_at<>'' THEN excluded.posted_at
                              ELSE episode_posts.posted_at END,
                source=excluded.source,
                note=CASE WHEN excluded.note<>'' THEN excluded.note
                              ELSE episode_posts.note END,
                updated_at=excluded.updated_at
            """,
            (episode_id, account_id, status, post_url, external_post_id,
             posted_at or now, source, note, now),
        )
        return _row(
            conn,
            "SELECT * FROM episode_posts WHERE episode_id=? AND account_id=?",
            (episode_id, account_id),
        ) or {}


def delete_post(episode_id: str, account_id: str, *, path: Path | None = None) -> None:
    init_library_tables(path)
    with _connect(path) as conn:
        conn.execute(
            "DELETE FROM episode_posts WHERE episode_id=? AND account_id=?",
            (episode_id, account_id),
        )


def posts_for_series(series_id: str, *, path: Path | None = None) -> list[dict]:
    init_library_tables(path)
    with _connect(path) as conn:
        return _rows(
            conn,
            """
            SELECT p.*, a.platform, a.name AS account_name
            FROM episode_posts p
            JOIN platform_accounts a USING(account_id)
            JOIN series_episodes e USING(episode_id)
            WHERE e.series_id=?
            """,
            (series_id,),
        )


# ── rollups ─────────────────────────────────────────────────────────────────

def series_overview(*, path: Path | None = None) -> list[dict]:
    """One row per series with production + distribution rollups.

    missing_source = episodes the SOURCE has but no finished dub exists for —
    the number the operator asked for ("series nào chưa đủ tập").
    """
    init_library_tables(path)
    with _connect(path) as conn:
        series = _rows(conn, "SELECT * FROM series ORDER BY updated_at DESC")
        ep_counts = _rows(
            conn,
            "SELECT series_id, status, COUNT(*) AS n FROM series_episodes "
            "GROUP BY series_id, status",
        )
        posted = _rows(
            conn,
            """
            SELECT e.series_id, a.platform, COUNT(DISTINCT e.episode_id) AS n
            FROM episode_posts p
            JOIN platform_accounts a USING(account_id)
            JOIN series_episodes e USING(episode_id)
            WHERE p.status='posted'
            GROUP BY e.series_id, a.platform
            """,
        )
    by_series_status: dict[str, dict[str, int]] = {}
    for r in ep_counts:
        by_series_status.setdefault(r["series_id"], {})[r["status"]] = r["n"]
    posted_map: dict[str, dict[str, int]] = {}
    for r in posted:
        posted_map.setdefault(r["series_id"], {})[r["platform"]] = r["n"]

    out = []
    for s in series:
        counts = by_series_status.get(s["series_id"], {})
        total = sum(counts.values())
        exported = counts.get("exported", 0)
        source_count = int(s.get("source_episode_count") or 0)
        missing_source = max(source_count - exported, 0) if source_count else counts.get("planned", 0)
        out.append({
            **s,
            "ep_total": total,
            "ep_exported": exported,
            "ep_planned": counts.get("planned", 0),
            "ep_processing": counts.get("queued", 0) + counts.get("processing", 0),
            "ep_review": counts.get("review", 0),
            "ep_failed": counts.get("failed", 0),
            "missing_source": missing_source,
            "posted": posted_map.get(s["series_id"], {}),
        })
    return out


# ── reup pipeline integration ───────────────────────────────────────────────

def next_ep_no(series_id: str, *, path: Path | None = None) -> int:
    init_library_tables(path)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT MAX(ep_no) AS m FROM series_episodes WHERE series_id=?",
            (series_id,),
        ).fetchone()
    return int(row["m"] or 0) + 1


def attach_job_to_episode(
    job_id: str, series_id: str, ep_no: int | None = None, *,
    source_url: str = "", path: Path | None = None,
) -> dict:
    """Called at enqueue time: reserve (series, ep) and point it at the job.

    ep_no=None is only meaningful for a 'single' bucket (one-off videos):
    there the number is an internal ordinal, so the next free slot is taken.
    For a real phim bộ a missing number is an error — silently appending would
    file tập 37 as tập 5.
    """
    if ep_no is None:
        series = get_series(series_id, path=path)
        if series is None:
            raise KeyError(f"series {series_id} not found")
        if str(series.get("kind") or "series") != "single":
            raise ValueError(
                "Phim bộ cần số tập rõ ràng — chỉ series 'video lẻ' được tự đánh số"
            )
        ep_no = next_ep_no(series_id, path=path)
    return upsert_episode(
        series_id, int(ep_no),
        reup_job_id=job_id, source_url=source_url, status="queued",
        path=path,
    )


def sync_episode_from_job(job_id: str, *, path: Path | None = None) -> dict | None:
    """Pull a finished/failed reup job's facts into its episode row.

    Linking is by reup_job_id first; when the operator queued the job without
    choosing a series, fall back to the aweme_id — if source-sync already
    planned that episode, the job snaps into place automatically.
    Also stamps the delivered product's meta.json with series/episode, so the
    folder itself says what it is even without the DB.
    """
    from omnicast.reup import vault_link

    job = vault_link.get_job(job_id, path=path)
    if not job:
        return None
    episode = find_episode(reup_job_id=job_id, path=path)
    if episode is None and job.get("aweme_id"):
        episode = find_episode(aweme_id=str(job["aweme_id"]), path=path)
        if episode is not None and not episode.get("reup_job_id"):
            episode = update_episode(episode["episode_id"], reup_job_id=job_id, path=path)
    if episode is None:
        return None

    exported = str(job.get("exported_video_path") or "")
    review_pending = int(job.get("review_pending") or 0)
    job_status = str(job.get("status") or "")
    if exported:
        status = "exported"
    elif review_pending > 0:
        status = "review"
    elif job_status == "failed":
        status = "failed"
    else:
        status = "processing"

    # Only a delivered product folder counts — a workspace export dir must not
    # get a meta.json stamped into it.
    product_dir = ""
    if exported:
        parent = Path(exported).parent
        if (parent / "meta.json").exists() or "products" in parent.parts:
            product_dir = str(parent)

    episode = update_episode(
        episode["episode_id"],
        status=status,
        path=path,
        **{
            k: v for k, v in {
                "source_aweme_id": str(job.get("aweme_id") or "") or None,
                "title": str(job.get("title") or "") or None,
                "title_vi": str(job.get("title_vi") or "") or None,
                "video_path": exported or None,
                "product_dir": product_dir or None,
            }.items() if v is not None
        },
    )

    # Stamp the product folder (best effort — the DB row is the SSOT).
    if product_dir:
        try:
            from omnicast.storage.products import write_meta

            write_meta(
                Path(product_dir),
                series_id=episode["series_id"],
                episode_no=episode["ep_no"],
            )
        except Exception:
            pass
    return episode


def episodes_with_posts(series_id: str, *, path: Path | None = None) -> dict:
    """Detail payload: series + episodes + posts keyed for the grid UI."""
    series = get_series(series_id, path=path)
    if series is None:
        raise KeyError(f"series {series_id} not found")
    episodes = list_episodes(series_id, path=path)
    posts = posts_for_series(series_id, path=path)
    posts_by_episode: dict[str, list[dict]] = {}
    for p in posts:
        posts_by_episode.setdefault(p["episode_id"], []).append(p)
    for e in episodes:
        e["posts"] = posts_by_episode.get(e["episode_id"], [])
    return {"series": series, "episodes": episodes}


def unassigned_job_ids(*, path: Path | None = None) -> set[str]:
    """reup jobs that no episode claims — the 'mồ côi' pile."""
    from omnicast.reup import vault_link  # noqa: F401  (ensures table exists)

    init_library_tables(path)
    with _connect(path) as conn:
        try:
            rows = conn.execute(
                "SELECT job_id FROM reup_jobs WHERE job_id NOT IN "
                "(SELECT reup_job_id FROM series_episodes WHERE reup_job_id<>'')"
            ).fetchall()
        except Exception:
            return set()
        return {r["job_id"] for r in rows}


def export_snapshot(*, path: Path | None = None) -> dict:
    """Whole library as one JSON-able dict (debug/backup)."""
    init_library_tables(path)
    with _connect(path) as conn:
        return {
            "series": _rows(conn, "SELECT * FROM series"),
            "episodes": _rows(conn, "SELECT * FROM series_episodes"),
            "accounts": _rows(conn, "SELECT * FROM platform_accounts"),
            "posts": _rows(conn, "SELECT * FROM episode_posts"),
        }


def _json(value) -> str:  # tiny helper kept for callers building notes
    return json.dumps(value, ensure_ascii=False)
