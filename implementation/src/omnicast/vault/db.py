"""SQLite vault — schema, CRUD, migrations."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from omnicast.vault.models import (
    BudgetRecord,
    ChannelStats,
    ClickRecord,
    CompetitorIntel,
    ConversionRecord,
    CredentialRecord,
    HealthLog,
    ModelRecord,
    NicheRecord,
    NicheStatus,
    OfferRecord,
    PlacementRecord,
    PostMetricRecord,
    ProviderRecord,
    PublishedVideo,
    ScriptRecord,
    ScriptStatus,
    TopicRecord,
    TopicStatus,
    UsageRecord,
)

# Vault DB lives next to niche_cache.json
_DEFAULT_PATH = Path(__file__).resolve().parents[4] / "output" / "vault.db"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or _DEFAULT_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> None:
    """Create tables if not exist."""
    with _connect(path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS niches (
            niche_id             TEXT PRIMARY KEY,
            niche_name           TEXT NOT NULL,
            market               TEXT NOT NULL DEFAULT 'US',
            status               TEXT NOT NULL DEFAULT 'watching',
            original_score       INTEGER NOT NULL,
            current_health       INTEGER NOT NULL,
            saved_at             TEXT NOT NULL,
            last_checked         TEXT,
            evidence_channel_ids TEXT NOT NULL DEFAULT '[]',
            seed_queries         TEXT NOT NULL DEFAULT '[]',
            niche_data           TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS health_logs (
            log_id                INTEGER PRIMARY KEY AUTOINCREMENT,
            niche_id              TEXT NOT NULL REFERENCES niches(niche_id),
            scan_date             TEXT NOT NULL,
            new_videos_count      INTEGER NOT NULL DEFAULT 0,
            avg_new_vpd           REAL NOT NULL DEFAULT 0.0,
            dedicated_competitors INTEGER NOT NULL DEFAULT 0,
            micro_outlier_found   INTEGER NOT NULL DEFAULT 0,
            health_score          INTEGER NOT NULL,
            status_change         TEXT,
            notes                 TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_logs_niche ON health_logs(niche_id);
        CREATE INDEX IF NOT EXISTS idx_niches_status ON niches(status);
        CREATE INDEX IF NOT EXISTS idx_niches_market ON niches(market);

        CREATE TABLE IF NOT EXISTS scripts (
            script_id        TEXT PRIMARY KEY,
            run_id           TEXT NOT NULL,
            channel_id       TEXT NOT NULL,
            language         TEXT NOT NULL DEFAULT 'en',
            topic            TEXT NOT NULL,
            score            INTEGER NOT NULL,
            approved         INTEGER NOT NULL DEFAULT 0,
            status           TEXT NOT NULL DEFAULT 'draft',
            script_content   TEXT NOT NULL DEFAULT '',
            cost_usd         REAL NOT NULL DEFAULT 0.0,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            youtube_video_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_scripts_channel  ON scripts(channel_id);
        CREATE INDEX IF NOT EXISTS idx_scripts_status   ON scripts(status);
        CREATE INDEX IF NOT EXISTS idx_scripts_language ON scripts(language);

        CREATE TABLE IF NOT EXISTS policy_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            url          TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            main_text    TEXT NOT NULL,
            fetched_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS policy_rules (
            rule_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_text     TEXT NOT NULL,
            source_url    TEXT NOT NULL DEFAULT '',
            diff_context  TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'pending_approval',
            effective_date TEXT,
            created_at    TEXT NOT NULL,
            approved_at   TEXT,
            approved_by   TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_url_hash
            ON policy_snapshots(url, content_hash);
        CREATE INDEX IF NOT EXISTS idx_rules_status ON policy_rules(status);

        CREATE TABLE IF NOT EXISTS topics (
            topic_id         TEXT PRIMARY KEY,
            channel_id       TEXT NOT NULL,
            title            TEXT NOT NULL,
            score            INTEGER NOT NULL DEFAULT 0,
            status           TEXT NOT NULL DEFAULT 'queued',
            rank             INTEGER NOT NULL DEFAULT 0,
            audience_segment TEXT NOT NULL DEFAULT '',
            pain_point       TEXT NOT NULL DEFAULT '',
            content_angle    TEXT NOT NULL DEFAULT '',
            source_url       TEXT NOT NULL DEFAULT '',
            discovered_at    TEXT NOT NULL,
            used_at          TEXT,
            used_video_id    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_topics_channel ON topics(channel_id);
        CREATE INDEX IF NOT EXISTS idx_topics_status  ON topics(status);

        CREATE TABLE IF NOT EXISTS channel_stats (
            channel_id         TEXT PRIMARY KEY,
            youtube_channel_id TEXT NOT NULL DEFAULT '',
            title              TEXT NOT NULL DEFAULT '',
            avatar_url         TEXT NOT NULL DEFAULT '',
            subscribers        INTEGER NOT NULL DEFAULT 0,
            total_views        INTEGER NOT NULL DEFAULT 0,
            video_count        INTEGER NOT NULL DEFAULT 0,
            est_revenue_usd    REAL NOT NULL DEFAULT 0.0,
            health             INTEGER NOT NULL DEFAULT 0,
            fetched_at         TEXT
        );

        CREATE TABLE IF NOT EXISTS channel_metrics_daily (
            channel_id        TEXT NOT NULL,
            date              TEXT NOT NULL,          -- YYYY-MM-DD
            views             INTEGER NOT NULL DEFAULT 0,
            watch_time_hours  REAL NOT NULL DEFAULT 0.0,
            avd_seconds       REAL NOT NULL DEFAULT 0.0,
            avd_percent       REAL NOT NULL DEFAULT 0.0,
            subscriber_change INTEGER NOT NULL DEFAULT 0,
            impressions       INTEGER NOT NULL DEFAULT 0,  -- 0 = unavailable via API
            ctr               REAL NOT NULL DEFAULT 0.0,   -- 0 = unavailable via API
            revenue           REAL NOT NULL DEFAULT 0.0,
            rpm               REAL NOT NULL DEFAULT 0.0,
            traffic_sources   TEXT NOT NULL DEFAULT '{}',  -- JSON {source: share}
            fetched_at        TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (channel_id, date)
        );

        CREATE INDEX IF NOT EXISTS idx_cmd_channel ON channel_metrics_daily(channel_id);

        CREATE TABLE IF NOT EXISTS published_videos (
            video_id         TEXT PRIMARY KEY,
            channel_id       TEXT NOT NULL,
            title            TEXT NOT NULL,
            youtube_video_id TEXT NOT NULL DEFAULT '',
            published_at     TEXT NOT NULL DEFAULT '',
            status           TEXT NOT NULL DEFAULT 'produced'
        );

        CREATE INDEX IF NOT EXISTS idx_pub_channel ON published_videos(channel_id);

        CREATE TABLE IF NOT EXISTS competitor_intel (
            niche              TEXT PRIMARY KEY,
            title_playbook     TEXT NOT NULL DEFAULT '',
            thumbnail_playbook TEXT NOT NULL DEFAULT '',
            script_playbook    TEXT NOT NULL DEFAULT '',
            sample_titles      TEXT NOT NULL DEFAULT '[]',
            sample_count       INTEGER NOT NULL DEFAULT 0,
            cohort_meta        TEXT NOT NULL DEFAULT '',
            updated_at         TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS credentials (
            credential_id  TEXT PRIMARY KEY,
            provider       TEXT NOT NULL,
            account_id     TEXT NOT NULL,
            label          TEXT NOT NULL DEFAULT '',
            secret_ref     TEXT NOT NULL,
            scopes         TEXT NOT NULL DEFAULT '[]',
            status         TEXT NOT NULL DEFAULT 'active',
            priority       INTEGER NOT NULL DEFAULT 100,
            cooldown_until TEXT,
            last_used_at   TEXT,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_credentials_provider ON credentials(provider, status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_provider_account
            ON credentials(provider, account_id);

        CREATE TABLE IF NOT EXISTS providers (
            provider_id TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            capability  TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'active',
            priority    INTEGER NOT NULL DEFAULT 100,
            metadata    TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_providers_capability ON providers(capability, status);

        CREATE TABLE IF NOT EXISTS models (
            model_id      TEXT PRIMARY KEY,
            provider_id   TEXT NOT NULL,
            capability    TEXT NOT NULL,
            runtime       TEXT NOT NULL DEFAULT 'remote',
            cost_per_unit REAL NOT NULL DEFAULT 0.0,
            min_vram_mb   INTEGER NOT NULL DEFAULT 0,
            fallback      TEXT NOT NULL DEFAULT '[]',
            status        TEXT NOT NULL DEFAULT 'active',
            metadata      TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_models_provider ON models(provider_id, status);
        CREATE INDEX IF NOT EXISTS idx_models_capability ON models(capability, runtime, status);

        CREATE TABLE IF NOT EXISTS usage_ledger (
            usage_id      TEXT PRIMARY KEY,
            provider_id   TEXT NOT NULL DEFAULT '',
            credential_id TEXT NOT NULL DEFAULT '',
            capability    TEXT NOT NULL DEFAULT '',
            scope         TEXT NOT NULL DEFAULT 'global',
            scope_id      TEXT NOT NULL DEFAULT 'default',
            units         REAL NOT NULL DEFAULT 0.0,
            cost_usd      REAL NOT NULL DEFAULT 0.0,
            status        TEXT NOT NULL DEFAULT 'ok',
            created_at    TEXT NOT NULL,
            raw           TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_usage_scope ON usage_ledger(scope, scope_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage_ledger(provider_id, created_at);

        CREATE TABLE IF NOT EXISTS budgets (
            budget_id TEXT PRIMARY KEY,
            scope     TEXT NOT NULL DEFAULT 'global',
            scope_id  TEXT NOT NULL DEFAULT 'default',
            limit_usd REAL NOT NULL DEFAULT 0.0,
            spent_usd REAL NOT NULL DEFAULT 0.0,
            reset_at  TEXT,
            status    TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(scope, scope_id)
        );
        CREATE INDEX IF NOT EXISTS idx_budgets_scope ON budgets(scope, scope_id, status);

        CREATE TABLE IF NOT EXISTS post_metrics (
            platform_id        TEXT NOT NULL,
            account_id         TEXT NOT NULL,
            post_id            TEXT NOT NULL,
            channel_id         TEXT NOT NULL DEFAULT '',
            fetched_at         TEXT NOT NULL,
            views              INTEGER NOT NULL DEFAULT 0,
            likes              INTEGER NOT NULL DEFAULT 0,
            comments           INTEGER NOT NULL DEFAULT 0,
            shares             INTEGER NOT NULL DEFAULT 0,
            watch_time_seconds REAL NOT NULL DEFAULT 0.0,
            revenue            REAL NOT NULL DEFAULT 0.0,
            raw                TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (platform_id, post_id, fetched_at)
        );
        CREATE INDEX IF NOT EXISTS idx_post_metrics_channel ON post_metrics(channel_id, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_post_metrics_post ON post_metrics(platform_id, post_id);

        CREATE TABLE IF NOT EXISTS offers (
            offer_id         TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            network          TEXT NOT NULL DEFAULT '',
            url              TEXT NOT NULL,
            niches           TEXT NOT NULL DEFAULT '[]',
            commission_type  TEXT NOT NULL DEFAULT 'unknown',
            commission_value REAL NOT NULL DEFAULT 0.0,
            disclosure       TEXT NOT NULL DEFAULT '',
            status           TEXT NOT NULL DEFAULT 'active',
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status);

        CREATE TABLE IF NOT EXISTS placements (
            placement_id    TEXT PRIMARY KEY,
            offer_id        TEXT NOT NULL REFERENCES offers(offer_id),
            video_id        TEXT NOT NULL,
            channel_id      TEXT NOT NULL,
            platform_id     TEXT NOT NULL,
            destination_url TEXT NOT NULL,
            cta_text        TEXT NOT NULL DEFAULT '',
            disclosure      TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_placements_offer ON placements(offer_id);
        CREATE INDEX IF NOT EXISTS idx_placements_video ON placements(video_id);

        CREATE TABLE IF NOT EXISTS clicks (
            click_id      TEXT PRIMARY KEY,
            placement_id  TEXT NOT NULL REFERENCES placements(placement_id),
            occurred_at   TEXT NOT NULL,
            referrer      TEXT NOT NULL DEFAULT '',
            user_agent    TEXT NOT NULL DEFAULT '',
            raw           TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_clicks_placement ON clicks(placement_id, occurred_at);

        CREATE TABLE IF NOT EXISTS conversions (
            conversion_id TEXT PRIMARY KEY,
            placement_id  TEXT NOT NULL REFERENCES placements(placement_id),
            amount        REAL NOT NULL DEFAULT 0.0,
            currency      TEXT NOT NULL DEFAULT 'USD',
            occurred_at   TEXT NOT NULL,
            raw           TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_conversions_placement ON conversions(placement_id, occurred_at);

        CREATE TABLE IF NOT EXISTS revenue_events (
            revenue_id  TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            channel_id  TEXT NOT NULL DEFAULT '',
            video_id    TEXT NOT NULL DEFAULT '',
            platform_id TEXT NOT NULL DEFAULT '',
            amount      REAL NOT NULL DEFAULT 0.0,
            currency    TEXT NOT NULL DEFAULT 'USD',
            occurred_at TEXT NOT NULL,
            raw         TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_revenue_channel ON revenue_events(channel_id, occurred_at);

        -- Durable system state (kill-switch, feature flags). SQLite is the SSOT;
        -- Redis (if configured) is only a fast-path cache on top of this.
        CREATE TABLE IF NOT EXISTS system_state (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL,
            updated_by  TEXT NOT NULL DEFAULT ''
        );
        """)
        # Migrate: add script_playbook / cohort_meta to pre-existing tables.
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(competitor_intel)")]
            if "script_playbook" not in cols:
                conn.execute("ALTER TABLE competitor_intel ADD COLUMN script_playbook TEXT NOT NULL DEFAULT ''")
            if "cohort_meta" not in cols:
                conn.execute("ALTER TABLE competitor_intel ADD COLUMN cohort_meta TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass


# ── Niche CRUD ────────────────────────────────────────────────────────────────

def upsert_niche(record: NicheRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO niches
            (niche_id, niche_name, market, status, original_score, current_health,
             saved_at, last_checked, evidence_channel_ids, seed_queries, niche_data)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(niche_id) DO UPDATE SET
            niche_name=excluded.niche_name,
            market=excluded.market,
            status=excluded.status,
            current_health=excluded.current_health,
            last_checked=excluded.last_checked,
            evidence_channel_ids=excluded.evidence_channel_ids,
            seed_queries=excluded.seed_queries,
            niche_data=excluded.niche_data
        """, (
            record.niche_id,
            record.niche_name,
            record.market,
            record.status.value,
            record.original_score,
            record.current_health,
            record.saved_at,
            record.last_checked,
            json.dumps(record.evidence_channel_ids),
            json.dumps(record.seed_queries),
            json.dumps(record.niche_data, ensure_ascii=False),
        ))


def get_niche(niche_id: str, path: Path | None = None) -> NicheRecord | None:
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM niches WHERE niche_id=?", (niche_id,)
        ).fetchone()
    return _row_to_record(row) if row else None


def list_niches(
    status: NicheStatus | None = None,
    market: str | None = None,
    path: Path | None = None,
) -> list[NicheRecord]:
    clauses, params = [], []
    if status:
        clauses.append("status=?"); params.append(status.value)
    if market:
        clauses.append("market=?"); params.append(market.upper())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connect(path) as conn:
        rows = conn.execute(
            f"SELECT * FROM niches {where} ORDER BY current_health DESC", params
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def update_status(niche_id: str, status: NicheStatus,
                  health: int, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute(
            "UPDATE niches SET status=?, current_health=? WHERE niche_id=?",
            (status.value, health, niche_id),
        )


def update_last_checked(niche_id: str, ts: str, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute(
            "UPDATE niches SET last_checked=? WHERE niche_id=?", (ts, niche_id)
        )


def mark_niche_activated(
    niche_id: str, channel_id: str, path: Path | None = None
) -> bool:
    """Mark niche ACTIVE and store channel_id in niche_data.

    Returns True if niche was found and updated, False if not in vault.
    Call from niche_flow.py --create after channel JSON is saved.
    """
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT niche_data FROM niches WHERE niche_id=?", (niche_id,)
        ).fetchone()
        if not row:
            return False
        niche_data = json.loads(row["niche_data"])
        niche_data["channel_id"] = channel_id
        conn.execute(
            "UPDATE niches SET status=?, niche_data=? WHERE niche_id=?",
            (NicheStatus.ACTIVE.value, json.dumps(niche_data, ensure_ascii=False), niche_id),
        )
    return True


def _row_to_record(row: sqlite3.Row) -> NicheRecord:
    return NicheRecord(
        niche_id=row["niche_id"],
        niche_name=row["niche_name"],
        market=row["market"],
        status=NicheStatus(row["status"]),
        original_score=row["original_score"],
        current_health=row["current_health"],
        saved_at=row["saved_at"],
        last_checked=row["last_checked"],
        evidence_channel_ids=json.loads(row["evidence_channel_ids"]),
        seed_queries=json.loads(row["seed_queries"]),
        niche_data=json.loads(row["niche_data"]),
    )


# ── Health log CRUD ───────────────────────────────────────────────────────────

def insert_log(log: HealthLog, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO health_logs
            (niche_id, scan_date, new_videos_count, avg_new_vpd,
             dedicated_competitors, micro_outlier_found, health_score,
             status_change, notes)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            log.niche_id, log.scan_date, log.new_videos_count,
            log.avg_new_vpd, log.dedicated_competitors,
            int(log.micro_outlier_found), log.health_score,
            log.status_change, log.notes,
        ))


# ── Script CRUD ───────────────────────────────────────────────────────────────

def upsert_script(record: ScriptRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO scripts
            (script_id, run_id, channel_id, language, topic, score, approved,
             status, script_content, cost_usd, created_at, updated_at, youtube_video_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(script_id) DO UPDATE SET
            status=excluded.status,
            score=excluded.score,
            approved=excluded.approved,
            script_content=excluded.script_content,
            cost_usd=excluded.cost_usd,
            updated_at=excluded.updated_at,
            youtube_video_id=excluded.youtube_video_id
        """, (
            record.script_id, record.run_id, record.channel_id,
            record.language, record.topic, record.score,
            int(record.approved), record.status.value,
            record.script_content, record.cost_usd,
            record.created_at, record.updated_at,
            record.youtube_video_id,
        ))


def get_script(script_id: str, path: Path | None = None) -> ScriptRecord | None:
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM scripts WHERE script_id=?", (script_id,)
        ).fetchone()
    return _row_to_script(row) if row else None


def list_scripts(
    channel_id: str | None = None,
    language: str | None = None,
    status: ScriptStatus | None = None,
    path: Path | None = None,
) -> list[ScriptRecord]:
    clauses, params = [], []
    if channel_id:
        clauses.append("channel_id=?"); params.append(channel_id)
    if language:
        clauses.append("language=?"); params.append(language.lower())
    if status:
        clauses.append("status=?"); params.append(status.value)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connect(path) as conn:
        rows = conn.execute(
            f"SELECT * FROM scripts {where} ORDER BY created_at DESC", params
        ).fetchall()
    return [_row_to_script(r) for r in rows]


def update_script_status(
    script_id: str,
    status: ScriptStatus,
    updated_at: str,
    path: Path | None = None,
) -> None:
    with _connect(path) as conn:
        conn.execute(
            "UPDATE scripts SET status=?, updated_at=? WHERE script_id=?",
            (status.value, updated_at, script_id),
        )


def update_script_youtube(
    script_id: str,
    youtube_video_id: str,
    updated_at: str,
    path: Path | None = None,
) -> None:
    with _connect(path) as conn:
        conn.execute(
            "UPDATE scripts SET youtube_video_id=?, status=?, updated_at=? WHERE script_id=?",
            (youtube_video_id, ScriptStatus.UPLOADED.value, updated_at, script_id),
        )


def _row_to_script(row: sqlite3.Row) -> ScriptRecord:
    return ScriptRecord(
        script_id=row["script_id"],
        run_id=row["run_id"],
        channel_id=row["channel_id"],
        language=row["language"],
        topic=row["topic"],
        score=row["score"],
        approved=bool(row["approved"]),
        status=ScriptStatus(row["status"]),
        script_content=row["script_content"],
        cost_usd=row["cost_usd"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        youtube_video_id=row["youtube_video_id"],
    )


# ── Upload velocity helpers ───────────────────────────────────────────────────

def count_recent_uploads(
    channel_id: str,
    since_iso: str,
    path: Path | None = None,
) -> int:
    """Count scripts uploaded for channel_id since since_iso (ISO datetime string).

    Counts rows where status='uploaded' OR youtube_video_id IS NOT NULL.
    Used by ChannelGuard for velocity and weekly limit enforcement.

    Args:
        channel_id: Channel to check.
        since_iso:  ISO datetime string (UTC). Count uploads on/after this time.
    Returns:
        Number of uploaded scripts in that window.
    """
    with _connect(path) as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS cnt FROM scripts
               WHERE channel_id = ?
                 AND (status = 'uploaded' OR youtube_video_id IS NOT NULL)
                 AND updated_at >= ?""",
            (channel_id, since_iso),
        ).fetchone()
    return int(row["cnt"]) if row else 0


# ── Policy snapshot CRUD ─────────────────────────────────────────────────────

def get_last_snapshot(url: str, path: Path | None = None) -> dict | None:
    """Return most recent snapshot for url, or None."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM policy_snapshots WHERE url=? ORDER BY fetched_at DESC LIMIT 1",
            (url,),
        ).fetchone()
    return dict(row) if row else None


def save_snapshot(url: str, content_hash: str, main_text: str,
                  fetched_at: str, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO policy_snapshots (url, content_hash, main_text, fetched_at)
               VALUES (?,?,?,?)""",
            (url, content_hash, main_text, fetched_at),
        )


# ── Policy rules CRUD ─────────────────────────────────────────────────────────

def insert_pending_rules(rules: list[dict], path: Path | None = None) -> list[int]:
    """Insert rules with status='pending_approval'. Returns list of new rule_ids."""
    ids = []
    with _connect(path) as conn:
        for r in rules:
            cur = conn.execute(
                """INSERT INTO policy_rules
                   (rule_text, source_url, diff_context, status, created_at)
                   VALUES (?,?,?,?,?)""",
                (r["rule_text"], r.get("source_url", ""),
                 r.get("diff_context", ""), "pending_approval", r["created_at"]),
            )
            ids.append(cur.lastrowid)
    return ids


def get_active_rules(path: Path | None = None) -> list[dict]:
    """Return all rules with status='active'."""
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM policy_rules WHERE status='active' ORDER BY rule_id",
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_rules(path: Path | None = None) -> list[dict]:
    """Return all rules with status='pending_approval'."""
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM policy_rules WHERE status='pending_approval' ORDER BY rule_id",
        ).fetchall()
    return [dict(r) for r in rows]


def approve_rule(rule_id: int, approved_by: str, approved_at: str,
                 path: Path | None = None) -> None:
    """Set rule active. Archive previous active rules from same source."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT source_url FROM policy_rules WHERE rule_id=?", (rule_id,)
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE policy_rules SET status='archived'
                   WHERE status='active' AND source_url=?""",
                (row["source_url"],),
            )
        conn.execute(
            """UPDATE policy_rules SET status='active', approved_at=?, approved_by=?
               WHERE rule_id=?""",
            (approved_at, approved_by, rule_id),
        )


def reject_rule(rule_id: int, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute(
            "UPDATE policy_rules SET status='rejected' WHERE rule_id=?", (rule_id,)
        )


def get_logs(niche_id: str, limit: int = 10,
             path: Path | None = None) -> list[HealthLog]:
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM health_logs WHERE niche_id=? ORDER BY scan_date DESC LIMIT ?",
            (niche_id, limit),
        ).fetchall()
    return [
        HealthLog(
            log_id=r["log_id"], niche_id=r["niche_id"],
            scan_date=r["scan_date"], new_videos_count=r["new_videos_count"],
            avg_new_vpd=r["avg_new_vpd"],
            dedicated_competitors=r["dedicated_competitors"],
            micro_outlier_found=bool(r["micro_outlier_found"]),
            health_score=r["health_score"],
            status_change=r["status_change"], notes=r["notes"],
        )
        for r in rows
    ]


# ── Topic Vault CRUD ──────────────────────────────────────────────────────────

def make_topic_id(channel_id: str, title: str) -> str:
    """Stable id from channel + normalized title (dedupe same topic per channel)."""
    import hashlib
    norm = " ".join(title.lower().split())
    return hashlib.sha1(f"{channel_id}::{norm}".encode("utf-8")).hexdigest()[:16]


def normalize_topic_slug(title: str) -> str:
    """Normalize a topic title for script-stage duplicate checks."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def topic_has_script_product(channel_id: str, title: str, path: Path | None = None) -> bool:
    """Return True when a topic already has a script/product for the channel."""
    topic_id = make_topic_id(channel_id, title)
    slug = normalize_topic_slug(title)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT status FROM topics WHERE topic_id=?", (topic_id,)
        ).fetchone()
        if row and row["status"] == TopicStatus.USED.value:
            return True
        rows = conn.execute(
            "SELECT topic FROM scripts WHERE channel_id=?", (channel_id,)
        ).fetchall()
    return any(normalize_topic_slug(r["topic"]) == slug for r in rows)


def mark_topic_used_by_title(
    channel_id: str,
    title: str,
    used_at: str,
    video_id: str | None = None,
    path: Path | None = None,
) -> None:
    """Mark a topic used even when it was manually supplied and not queued first."""
    topic_id = make_topic_id(channel_id, title)
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO topics
            (topic_id, channel_id, title, score, status, rank, audience_segment,
             pain_point, content_angle, source_url, discovered_at, used_at, used_video_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(topic_id) DO UPDATE SET
            status=excluded.status,
            used_at=excluded.used_at,
            used_video_id=excluded.used_video_id
        """, (
            topic_id, channel_id, title, 0, TopicStatus.USED.value, 0,
            "", "", "", "", used_at, used_at, video_id,
        ))


def _row_to_topic(r: sqlite3.Row) -> TopicRecord:
    return TopicRecord(
        topic_id=r["topic_id"], channel_id=r["channel_id"], title=r["title"],
        score=r["score"], status=TopicStatus(r["status"]), rank=r["rank"],
        audience_segment=r["audience_segment"], pain_point=r["pain_point"],
        content_angle=r["content_angle"], source_url=r["source_url"],
        discovered_at=r["discovered_at"], used_at=r["used_at"],
        used_video_id=r["used_video_id"],
    )


def upsert_topic(record: TopicRecord, path: Path | None = None) -> None:
    """Insert a discovered topic. Existing topic_id keeps its status/used info
    (re-discovery only refreshes score/rank/metadata, never un-uses a topic)."""
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO topics
            (topic_id, channel_id, title, score, status, rank, audience_segment,
             pain_point, content_angle, source_url, discovered_at, used_at, used_video_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(topic_id) DO UPDATE SET
            score=excluded.score,
            rank=excluded.rank,
            audience_segment=excluded.audience_segment,
            pain_point=excluded.pain_point,
            content_angle=excluded.content_angle,
            source_url=excluded.source_url
        """, (
            record.topic_id, record.channel_id, record.title, record.score,
            record.status.value, record.rank, record.audience_segment,
            record.pain_point, record.content_angle, record.source_url,
            record.discovered_at, record.used_at, record.used_video_id,
        ))


def list_topics(channel_id: str | None = None, status: TopicStatus | None = None,
                limit: int = 200, path: Path | None = None) -> list[TopicRecord]:
    q = "SELECT * FROM topics WHERE 1=1"
    args: list = []
    if channel_id:
        q += " AND channel_id=?"; args.append(channel_id)
    if status:
        q += " AND status=?"; args.append(status.value)
    q += " ORDER BY (status='queued') DESC, score DESC, discovered_at DESC LIMIT ?"
    args.append(limit)
    with _connect(path) as conn:
        return [_row_to_topic(r) for r in conn.execute(q, args).fetchall()]


def get_next_topic(channel_id: str, path: Path | None = None) -> TopicRecord | None:
    """Highest-scoring queued topic for a channel (automation pulls this)."""
    with _connect(path) as conn:
        r = conn.execute(
            "SELECT * FROM topics WHERE channel_id=? AND status='queued' "
            "ORDER BY score DESC, rank ASC, discovered_at ASC LIMIT 1",
            (channel_id,),
        ).fetchone()
    return _row_to_topic(r) if r else None


def mark_topic_used(topic_id: str, used_at: str, video_id: str | None = None,
                    path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute(
            "UPDATE topics SET status='used', used_at=?, used_video_id=? WHERE topic_id=?",
            (used_at, video_id, topic_id),
        )


def set_topic_status(topic_id: str, status: TopicStatus, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("UPDATE topics SET status=? WHERE topic_id=?",
                     (status.value, topic_id))


def count_topics(channel_id: str | None = None, path: Path | None = None) -> dict:
    q = "SELECT status, COUNT(*) c FROM topics"
    args: list = []
    if channel_id:
        q += " WHERE channel_id=?"; args.append(channel_id)
    q += " GROUP BY status"
    with _connect(path) as conn:
        rows = conn.execute(q, args).fetchall()
    out = {"queued": 0, "used": 0, "skipped": 0}
    for r in rows:
        out[r["status"]] = r["c"]
    return out


# ── Channel Stats CRUD ────────────────────────────────────────────────────────

def _row_to_stats(r: sqlite3.Row) -> ChannelStats:
    return ChannelStats(
        channel_id=r["channel_id"], youtube_channel_id=r["youtube_channel_id"],
        title=r["title"], avatar_url=r["avatar_url"], subscribers=r["subscribers"],
        total_views=r["total_views"], video_count=r["video_count"],
        est_revenue_usd=r["est_revenue_usd"], health=r["health"],
        fetched_at=r["fetched_at"],
    )


def upsert_channel_stats(s: ChannelStats, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO channel_stats
            (channel_id, youtube_channel_id, title, avatar_url, subscribers,
             total_views, video_count, est_revenue_usd, health, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(channel_id) DO UPDATE SET
            youtube_channel_id=excluded.youtube_channel_id,
            title=excluded.title, avatar_url=excluded.avatar_url,
            subscribers=excluded.subscribers, total_views=excluded.total_views,
            video_count=excluded.video_count, est_revenue_usd=excluded.est_revenue_usd,
            health=excluded.health, fetched_at=excluded.fetched_at
        """, (
            s.channel_id, s.youtube_channel_id, s.title, s.avatar_url, s.subscribers,
            s.total_views, s.video_count, s.est_revenue_usd, s.health, s.fetched_at,
        ))


def get_channel_stats(channel_id: str, path: Path | None = None) -> ChannelStats | None:
    with _connect(path) as conn:
        r = conn.execute("SELECT * FROM channel_stats WHERE channel_id=?",
                         (channel_id,)).fetchone()
    return _row_to_stats(r) if r else None


def list_channel_stats(path: Path | None = None) -> list[ChannelStats]:
    with _connect(path) as conn:
        return [_row_to_stats(r) for r in
                conn.execute("SELECT * FROM channel_stats").fetchall()]


# ── Channel daily metrics (YouTube Analytics API time series) ─────────────────

def upsert_channel_metrics_daily(channel_id: str, rows: list[dict],
                                 path: Path | None = None) -> int:
    """Upsert daily metric rows (dicts with keys matching the table columns).
    Returns number of rows written. `date` must be YYYY-MM-DD."""
    import json as _json
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    now = _dt.now(_tz.utc).isoformat()
    written = 0
    with _connect(path) as conn:
        for r in rows:
            if not r.get("date"):
                continue
            conn.execute("""
            INSERT INTO channel_metrics_daily
                (channel_id, date, views, watch_time_hours, avd_seconds,
                 avd_percent, subscriber_change, impressions, ctr, revenue,
                 rpm, traffic_sources, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(channel_id, date) DO UPDATE SET
                views=excluded.views, watch_time_hours=excluded.watch_time_hours,
                avd_seconds=excluded.avd_seconds, avd_percent=excluded.avd_percent,
                subscriber_change=excluded.subscriber_change,
                impressions=excluded.impressions, ctr=excluded.ctr,
                revenue=excluded.revenue, rpm=excluded.rpm,
                traffic_sources=excluded.traffic_sources,
                fetched_at=excluded.fetched_at
            """, (
                channel_id, str(r["date"]), int(r.get("views", 0)),
                float(r.get("watch_time_hours", 0.0)),
                float(r.get("avd_seconds", 0.0)), float(r.get("avd_percent", 0.0)),
                int(r.get("subscriber_change", 0)), int(r.get("impressions", 0)),
                float(r.get("ctr", 0.0)), float(r.get("revenue", 0.0)),
                float(r.get("rpm", 0.0)),
                _json.dumps(r.get("traffic_sources") or {}), now,
            ))
            written += 1
    return written


def list_channel_metrics_daily(channel_id: str, days: int = 90,
                               path: Path | None = None) -> list[dict]:
    """Last N days of daily metrics, oldest first. traffic_sources decoded."""
    import json as _json
    with _connect(path) as conn:
        rows = conn.execute("""
            SELECT * FROM channel_metrics_daily WHERE channel_id=?
            ORDER BY date DESC LIMIT ?""", (channel_id, days)).fetchall()
    out = []
    for r in reversed(rows):
        d = dict(r)
        try:
            d["traffic_sources"] = _json.loads(d.get("traffic_sources") or "{}")
        except Exception:
            d["traffic_sources"] = {}
        out.append(d)
    return out


# ── Published-video ledger (content dedup) ────────────────────────────────────

def record_published(v: PublishedVideo, path: Path | None = None) -> None:
    """Upsert a produced/published video into the dedup ledger."""
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO published_videos
            (video_id, channel_id, title, youtube_video_id, published_at, status)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
            title=excluded.title,
            youtube_video_id=CASE WHEN excluded.youtube_video_id<>'' THEN excluded.youtube_video_id ELSE published_videos.youtube_video_id END,
            published_at=excluded.published_at,
            status=excluded.status
        """, (v.video_id, v.channel_id, v.title, v.youtube_video_id,
              v.published_at, v.status))


def _row_to_published(r: sqlite3.Row) -> PublishedVideo:
    return PublishedVideo(
        video_id=r["video_id"], channel_id=r["channel_id"], title=r["title"],
        youtube_video_id=r["youtube_video_id"], published_at=r["published_at"],
        status=r["status"],
    )


def list_published(channel_id: str | None = None, path: Path | None = None) -> list[PublishedVideo]:
    q = "SELECT * FROM published_videos"
    args: list = []
    if channel_id:
        q += " WHERE channel_id=?"; args.append(channel_id)
    q += " ORDER BY published_at DESC"
    with _connect(path) as conn:
        return [_row_to_published(r) for r in conn.execute(q, args).fetchall()]


# ── Competitor Intel (learned title + thumbnail playbooks) ────────────────────

def replace_competitor_intel(
    niche: str, build_row, path: Path | None = None
) -> CompetitorIntel:
    """Read-merge-write for one niche inside a SINGLE exclusive transaction.

    `build_row(previous) -> CompetitorIntel` runs with the row locked. The
    learner previously read the old row on one connection and wrote the merged
    result on another, so two runs for the same niche could interleave and the
    later write would silently drop the earlier run's carried-forward artifacts
    and provenance."""
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM competitor_intel WHERE niche=?", (niche,)).fetchone()
        previous = _row_to_competitor_intel(row) if row else None
        record = build_row(previous)
        _write_competitor_intel(conn, record)
        conn.commit()
        return record
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _write_competitor_intel(conn, c: CompetitorIntel) -> None:
    conn.execute("""
    INSERT INTO competitor_intel
        (niche, title_playbook, thumbnail_playbook, script_playbook, sample_titles, sample_count, cohort_meta, updated_at)
    VALUES (?,?,?,?,?,?,?,?)
    ON CONFLICT(niche) DO UPDATE SET
        title_playbook=excluded.title_playbook,
        thumbnail_playbook=excluded.thumbnail_playbook,
        script_playbook=excluded.script_playbook,
        sample_titles=excluded.sample_titles,
        sample_count=excluded.sample_count,
        cohort_meta=excluded.cohort_meta,
        updated_at=excluded.updated_at
    """, (c.niche, c.title_playbook, c.thumbnail_playbook,
          getattr(c, "script_playbook", ""),
          json.dumps(c.sample_titles, ensure_ascii=False), c.sample_count,
          getattr(c, "cohort_meta", ""), c.updated_at))


def _row_to_competitor_intel(r) -> CompetitorIntel:
    try:
        titles = json.loads(r["sample_titles"])
    except Exception:
        titles = []
    keys = r.keys()
    return CompetitorIntel(
        niche=r["niche"], title_playbook=r["title_playbook"],
        thumbnail_playbook=r["thumbnail_playbook"],
        script_playbook=(r["script_playbook"] if "script_playbook" in keys else ""),
        sample_titles=titles,
        sample_count=r["sample_count"],
        cohort_meta=(r["cohort_meta"] if "cohort_meta" in keys else ""),
        updated_at=r["updated_at"],
    )


def upsert_competitor_intel(c: CompetitorIntel, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO competitor_intel
            (niche, title_playbook, thumbnail_playbook, script_playbook, sample_titles, sample_count, cohort_meta, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(niche) DO UPDATE SET
            title_playbook=excluded.title_playbook,
            thumbnail_playbook=excluded.thumbnail_playbook,
            -- Was: CASE WHEN excluded.script_playbook<>'' THEN excluded ELSE
            -- existing END. That silently kept the OLD playbook while replacing
            -- cohort_meta with the NEW run's provenance, so a stale artifact
            -- ended up wearing fresh credentials. Carry-forward now happens in
            -- competitor_intel._merge_run, which moves the artifact AND its own
            -- provenance together. The SQL just stores what it is given.
            script_playbook=excluded.script_playbook,
            sample_titles=excluded.sample_titles,
            sample_count=excluded.sample_count,
            cohort_meta=excluded.cohort_meta,
            updated_at=excluded.updated_at
        """, (c.niche, c.title_playbook, c.thumbnail_playbook,
              getattr(c, "script_playbook", ""),
              json.dumps(c.sample_titles, ensure_ascii=False), c.sample_count,
              getattr(c, "cohort_meta", ""), c.updated_at))


def get_competitor_intel(niche: str, path: Path | None = None) -> CompetitorIntel | None:
    with _connect(path) as conn:
        r = conn.execute("SELECT * FROM competitor_intel WHERE niche=?", (niche,)).fetchone()
    if not r:
        return None
    try:
        titles = json.loads(r["sample_titles"])
    except Exception:
        titles = []
    keys = r.keys()
    return CompetitorIntel(
        niche=r["niche"], title_playbook=r["title_playbook"],
        thumbnail_playbook=r["thumbnail_playbook"],
        script_playbook=(r["script_playbook"] if "script_playbook" in keys else ""),
        sample_titles=titles,
        sample_count=r["sample_count"],
        cohort_meta=(r["cohort_meta"] if "cohort_meta" in keys else ""),
        updated_at=r["updated_at"],
    )


# ── Super-app monetization / platform CRUD ──────────────────────────────────

def upsert_credential(c: CredentialRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO credentials
            (credential_id, provider, account_id, label, secret_ref, scopes, status,
             priority, cooldown_until, last_used_at, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(credential_id) DO UPDATE SET
            provider=excluded.provider,
            account_id=excluded.account_id,
            label=excluded.label,
            secret_ref=excluded.secret_ref,
            scopes=excluded.scopes,
            status=excluded.status,
            priority=excluded.priority,
            cooldown_until=excluded.cooldown_until,
            last_used_at=excluded.last_used_at,
            updated_at=excluded.updated_at
        """, (
            c.credential_id, c.provider, c.account_id, c.label, c.secret_ref,
            json.dumps(c.scopes), c.status, c.priority, c.cooldown_until,
            c.last_used_at, c.created_at, c.updated_at,
        ))


def _row_to_credential(r: sqlite3.Row) -> CredentialRecord:
    return CredentialRecord(
        credential_id=r["credential_id"], provider=r["provider"],
        account_id=r["account_id"], label=r["label"], secret_ref=r["secret_ref"],
        scopes=json.loads(r["scopes"]), status=r["status"], priority=r["priority"],
        cooldown_until=r["cooldown_until"], last_used_at=r["last_used_at"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def get_credential(credential_id: str, path: Path | None = None) -> CredentialRecord | None:
    with _connect(path) as conn:
        r = conn.execute("SELECT * FROM credentials WHERE credential_id=?",
                         (credential_id,)).fetchone()
    return _row_to_credential(r) if r else None


def list_credentials(provider: str | None = None, path: Path | None = None) -> list[CredentialRecord]:
    q = "SELECT * FROM credentials"
    args: list = []
    if provider:
        q += " WHERE provider=?"; args.append(provider)
    q += " ORDER BY priority ASC, updated_at DESC"
    with _connect(path) as conn:
        return [_row_to_credential(r) for r in conn.execute(q, args).fetchall()]


def upsert_provider(p: ProviderRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO providers
            (provider_id, name, capability, status, priority, metadata, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(provider_id) DO UPDATE SET
            name=excluded.name,
            capability=excluded.capability,
            status=excluded.status,
            priority=excluded.priority,
            metadata=excluded.metadata,
            updated_at=excluded.updated_at
        """, (
            p.provider_id, p.name, p.capability, p.status, p.priority,
            json.dumps(p.metadata, ensure_ascii=False), p.created_at, p.updated_at,
        ))


def _row_to_provider(r: sqlite3.Row) -> ProviderRecord:
    return ProviderRecord(
        provider_id=r["provider_id"], name=r["name"], capability=r["capability"],
        status=r["status"], priority=r["priority"], metadata=json.loads(r["metadata"]),
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def list_providers(capability: str | None = None,
                   path: Path | None = None) -> list[ProviderRecord]:
    q = "SELECT * FROM providers"
    args: list = []
    if capability:
        q += " WHERE capability=?"; args.append(capability)
    q += " ORDER BY priority ASC, provider_id ASC"
    with _connect(path) as conn:
        return [_row_to_provider(r) for r in conn.execute(q, args).fetchall()]


def upsert_model(m: ModelRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO models
            (model_id, provider_id, capability, runtime, cost_per_unit, min_vram_mb,
             fallback, status, metadata, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(model_id) DO UPDATE SET
            provider_id=excluded.provider_id,
            capability=excluded.capability,
            runtime=excluded.runtime,
            cost_per_unit=excluded.cost_per_unit,
            min_vram_mb=excluded.min_vram_mb,
            fallback=excluded.fallback,
            status=excluded.status,
            metadata=excluded.metadata,
            updated_at=excluded.updated_at
        """, (
            m.model_id, m.provider_id, m.capability, m.runtime, m.cost_per_unit,
            m.min_vram_mb, json.dumps(m.fallback), m.status,
            json.dumps(m.metadata, ensure_ascii=False), m.created_at, m.updated_at,
        ))


def _row_to_model(r: sqlite3.Row) -> ModelRecord:
    return ModelRecord(
        model_id=r["model_id"], provider_id=r["provider_id"], capability=r["capability"],
        runtime=r["runtime"], cost_per_unit=r["cost_per_unit"],
        min_vram_mb=r["min_vram_mb"], fallback=json.loads(r["fallback"]),
        status=r["status"], metadata=json.loads(r["metadata"]),
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def list_models(capability: str | None = None, provider_id: str | None = None,
                path: Path | None = None) -> list[ModelRecord]:
    q = "SELECT * FROM models"
    args: list = []
    clauses: list[str] = []
    if capability:
        clauses.append("capability=?"); args.append(capability)
    if provider_id:
        clauses.append("provider_id=?"); args.append(provider_id)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY provider_id ASC, model_id ASC"
    with _connect(path) as conn:
        return [_row_to_model(r) for r in conn.execute(q, args).fetchall()]


def insert_usage(u: UsageRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT OR REPLACE INTO usage_ledger
            (usage_id, provider_id, credential_id, capability, scope, scope_id,
             units, cost_usd, status, created_at, raw)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            u.usage_id, u.provider_id, u.credential_id, u.capability, u.scope,
            u.scope_id, u.units, u.cost_usd, u.status, u.created_at,
            json.dumps(u.raw, ensure_ascii=False),
        ))


def _row_to_usage(r: sqlite3.Row) -> UsageRecord:
    return UsageRecord(
        usage_id=r["usage_id"], provider_id=r["provider_id"],
        credential_id=r["credential_id"], capability=r["capability"],
        scope=r["scope"], scope_id=r["scope_id"], units=r["units"],
        cost_usd=r["cost_usd"], status=r["status"], created_at=r["created_at"],
        raw=json.loads(r["raw"]),
    )


def list_usage(scope: str | None = None, scope_id: str | None = None,
               path: Path | None = None) -> list[UsageRecord]:
    q = "SELECT * FROM usage_ledger"
    args: list = []
    clauses: list[str] = []
    if scope:
        clauses.append("scope=?"); args.append(scope)
    if scope_id:
        clauses.append("scope_id=?"); args.append(scope_id)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY created_at DESC"
    with _connect(path) as conn:
        return [_row_to_usage(r) for r in conn.execute(q, args).fetchall()]


def sum_usage_cost(scope: str | None = None, scope_id: str | None = None,
                   path: Path | None = None) -> float:
    q = "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage_ledger"
    args: list = []
    clauses: list[str] = []
    if scope:
        clauses.append("scope=?"); args.append(scope)
    if scope_id:
        clauses.append("scope_id=?"); args.append(scope_id)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    with _connect(path) as conn:
        row = conn.execute(q, args).fetchone()
    return float(row["total"] if row else 0.0)


def upsert_budget(b: BudgetRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO budgets
            (budget_id, scope, scope_id, limit_usd, spent_usd, reset_at,
             status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(budget_id) DO UPDATE SET
            scope=excluded.scope,
            scope_id=excluded.scope_id,
            limit_usd=excluded.limit_usd,
            spent_usd=excluded.spent_usd,
            reset_at=excluded.reset_at,
            status=excluded.status,
            updated_at=excluded.updated_at
        """, (
            b.budget_id, b.scope, b.scope_id, b.limit_usd, b.spent_usd,
            b.reset_at, b.status, b.created_at, b.updated_at,
        ))


def _row_to_budget(r: sqlite3.Row) -> BudgetRecord:
    return BudgetRecord(
        budget_id=r["budget_id"], scope=r["scope"], scope_id=r["scope_id"],
        limit_usd=r["limit_usd"], spent_usd=r["spent_usd"], reset_at=r["reset_at"],
        status=r["status"], created_at=r["created_at"], updated_at=r["updated_at"],
    )


def get_budget(scope: str, scope_id: str,
               path: Path | None = None) -> BudgetRecord | None:
    with _connect(path) as conn:
        r = conn.execute(
            "SELECT * FROM budgets WHERE scope=? AND scope_id=? AND status='active'",
            (scope, scope_id),
        ).fetchone()
    return _row_to_budget(r) if r else None


def list_budgets(path: Path | None = None) -> list[BudgetRecord]:
    with _connect(path) as conn:
        return [_row_to_budget(r) for r in conn.execute(
            "SELECT * FROM budgets ORDER BY scope ASC, scope_id ASC"
        ).fetchall()]


def add_budget_spend(scope: str, scope_id: str, amount_usd: float,
                     path: Path | None = None) -> BudgetRecord | None:
    with _connect(path) as conn:
        r = conn.execute(
            "SELECT * FROM budgets WHERE scope=? AND scope_id=? AND status='active'",
            (scope, scope_id),
        ).fetchone()
        if not r:
            return None
        conn.execute(
            "UPDATE budgets SET spent_usd=spent_usd+?, updated_at=datetime('now') "
            "WHERE budget_id=?",
            (amount_usd, r["budget_id"]),
        )
        updated = conn.execute(
            "SELECT * FROM budgets WHERE budget_id=?", (r["budget_id"],)
        ).fetchone()
    return _row_to_budget(updated) if updated else None


def insert_post_metric(m: PostMetricRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT OR REPLACE INTO post_metrics
            (platform_id, account_id, post_id, channel_id, fetched_at, views, likes,
             comments, shares, watch_time_seconds, revenue, raw)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            m.platform_id, m.account_id, m.post_id, m.channel_id, m.fetched_at,
            m.views, m.likes, m.comments, m.shares, m.watch_time_seconds,
            m.revenue, json.dumps(m.raw, ensure_ascii=False),
        ))


def _row_to_post_metric(r: sqlite3.Row) -> PostMetricRecord:
    return PostMetricRecord(
        platform_id=r["platform_id"], account_id=r["account_id"],
        post_id=r["post_id"], channel_id=r["channel_id"],
        fetched_at=r["fetched_at"], views=r["views"], likes=r["likes"],
        comments=r["comments"], shares=r["shares"],
        watch_time_seconds=r["watch_time_seconds"], revenue=r["revenue"],
        raw=json.loads(r["raw"]),
    )


def latest_post_metric(platform_id: str, post_id: str,
                       path: Path | None = None) -> PostMetricRecord | None:
    with _connect(path) as conn:
        r = conn.execute(
            "SELECT * FROM post_metrics WHERE platform_id=? AND post_id=? "
            "ORDER BY fetched_at DESC LIMIT 1",
            (platform_id, post_id),
        ).fetchone()
    return _row_to_post_metric(r) if r else None


def list_post_metrics(channel_id: str | None = None, path: Path | None = None) -> list[PostMetricRecord]:
    q = "SELECT * FROM post_metrics"
    args: list = []
    if channel_id:
        q += " WHERE channel_id=?"; args.append(channel_id)
    q += " ORDER BY fetched_at DESC"
    with _connect(path) as conn:
        return [_row_to_post_metric(r) for r in conn.execute(q, args).fetchall()]


def upsert_offer(o: OfferRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO offers
            (offer_id, name, network, url, niches, commission_type, commission_value,
             disclosure, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(offer_id) DO UPDATE SET
            name=excluded.name,
            network=excluded.network,
            url=excluded.url,
            niches=excluded.niches,
            commission_type=excluded.commission_type,
            commission_value=excluded.commission_value,
            disclosure=excluded.disclosure,
            status=excluded.status,
            updated_at=excluded.updated_at
        """, (
            o.offer_id, o.name, o.network, o.url, json.dumps(o.niches),
            o.commission_type, o.commission_value, o.disclosure, o.status,
            o.created_at, o.updated_at,
        ))


def _row_to_offer(r: sqlite3.Row) -> OfferRecord:
    return OfferRecord(
        offer_id=r["offer_id"], name=r["name"], network=r["network"], url=r["url"],
        niches=json.loads(r["niches"]), commission_type=r["commission_type"],
        commission_value=r["commission_value"], disclosure=r["disclosure"],
        status=r["status"], created_at=r["created_at"], updated_at=r["updated_at"],
    )


def get_offer(offer_id: str, path: Path | None = None) -> OfferRecord | None:
    with _connect(path) as conn:
        r = conn.execute("SELECT * FROM offers WHERE offer_id=?", (offer_id,)).fetchone()
    return _row_to_offer(r) if r else None


def list_offers(status: str | None = "active", path: Path | None = None) -> list[OfferRecord]:
    q = "SELECT * FROM offers"
    args: list = []
    if status:
        q += " WHERE status=?"; args.append(status)
    q += " ORDER BY updated_at DESC"
    with _connect(path) as conn:
        return [_row_to_offer(r) for r in conn.execute(q, args).fetchall()]


def insert_placement(p: PlacementRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT OR REPLACE INTO placements
            (placement_id, offer_id, video_id, channel_id, platform_id,
             destination_url, cta_text, disclosure, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            p.placement_id, p.offer_id, p.video_id, p.channel_id, p.platform_id,
            p.destination_url, p.cta_text, p.disclosure, p.created_at,
        ))


def _row_to_placement(r: sqlite3.Row) -> PlacementRecord:
    return PlacementRecord(
        placement_id=r["placement_id"], offer_id=r["offer_id"],
        video_id=r["video_id"], channel_id=r["channel_id"],
        platform_id=r["platform_id"], destination_url=r["destination_url"],
        cta_text=r["cta_text"], disclosure=r["disclosure"],
        created_at=r["created_at"],
    )


def list_placements(video_id: str | None = None, path: Path | None = None) -> list[PlacementRecord]:
    q = "SELECT * FROM placements"
    args: list = []
    if video_id:
        q += " WHERE video_id=?"; args.append(video_id)
    q += " ORDER BY created_at DESC"
    with _connect(path) as conn:
        return [_row_to_placement(r) for r in conn.execute(q, args).fetchall()]


def get_placement(placement_id: str, path: Path | None = None) -> PlacementRecord | None:
    with _connect(path) as conn:
        r = conn.execute(
            "SELECT * FROM placements WHERE placement_id=?", (placement_id,)
        ).fetchone()
    return _row_to_placement(r) if r else None


def insert_click(c: ClickRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT OR REPLACE INTO clicks
            (click_id, placement_id, occurred_at, referrer, user_agent, raw)
        VALUES (?,?,?,?,?,?)
        """, (
            c.click_id, c.placement_id, c.occurred_at, c.referrer,
            c.user_agent, json.dumps(c.raw, ensure_ascii=False),
        ))


def _row_to_click(r: sqlite3.Row) -> ClickRecord:
    return ClickRecord(
        click_id=r["click_id"], placement_id=r["placement_id"],
        occurred_at=r["occurred_at"], referrer=r["referrer"],
        user_agent=r["user_agent"], raw=json.loads(r["raw"]),
    )


def list_clicks(placement_id: str | None = None,
                path: Path | None = None) -> list[ClickRecord]:
    q = "SELECT * FROM clicks"
    args: list = []
    if placement_id:
        q += " WHERE placement_id=?"; args.append(placement_id)
    q += " ORDER BY occurred_at DESC"
    with _connect(path) as conn:
        return [_row_to_click(r) for r in conn.execute(q, args).fetchall()]


def insert_conversion(c: ConversionRecord, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("""
        INSERT OR REPLACE INTO conversions
            (conversion_id, placement_id, amount, currency, occurred_at, raw)
        VALUES (?,?,?,?,?,?)
        """, (
            c.conversion_id, c.placement_id, c.amount, c.currency,
            c.occurred_at, json.dumps(c.raw, ensure_ascii=False),
        ))
        placement = conn.execute(
            "SELECT video_id, channel_id, platform_id FROM placements WHERE placement_id=?",
            (c.placement_id,),
        ).fetchone()
        if placement:
            conn.execute("""
            INSERT OR REPLACE INTO revenue_events
                (revenue_id, source, channel_id, video_id, platform_id,
                 amount, currency, occurred_at, raw)
            VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                f"conversion:{c.conversion_id}", "affiliate", placement["channel_id"],
                placement["video_id"], placement["platform_id"], c.amount,
                c.currency, c.occurred_at, json.dumps(c.raw, ensure_ascii=False),
            ))


def sum_revenue(channel_id: str | None = None, path: Path | None = None) -> float:
    q = "SELECT COALESCE(SUM(amount), 0) AS total FROM revenue_events"
    args: list = []
    if channel_id:
        q += " WHERE channel_id=?"; args.append(channel_id)
    with _connect(path) as conn:
        row = conn.execute(q, args).fetchone()
    return float(row["total"] if row else 0.0)


# ── System state (durable kill-switch / flags — SSOT, no Redis required) ──────

def get_system_state(key: str, path: Path | None = None) -> str | None:
    """Return the raw string value for `key`, or None if unset."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT value FROM system_state WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_system_state(key: str, value: str, *, updated_by: str = "", path: Path | None = None) -> None:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    with _connect(path) as conn:
        conn.execute("""
        INSERT INTO system_state (key, value, updated_at, updated_by)
        VALUES (?,?,?,?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value, updated_at=excluded.updated_at, updated_by=excluded.updated_by
        """, (key, value, ts, updated_by))


def delete_system_state(key: str, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("DELETE FROM system_state WHERE key=?", (key,))
