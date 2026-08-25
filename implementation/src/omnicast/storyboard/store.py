"""Storyboard persistence — SQLite `vault.db`, per the project storage rule.

CLAUDE.md is explicit: anything with a lifecycle or that needs querying lives in
`vault.db`, not in new JSON files. A storyboard has both — it moves through an
approval flow and the UI queries it by channel and by status.

PATH NOTE (deliberate, not a copy-paste slip). This module resolves the DB the
way the modules that actually write to it do — `parents[3]`, i.e.
`implementation/output/vault.db`, matching `storage/products.py`,
`agents/writer.py` and `agents/critic.py`. `vault/db.py`'s own `_DEFAULT_PATH`
uses `parents[4]` and therefore points at a different, stale file at the repo
root. Following the module default here would have written the cast registry
into a database nothing else reads. That inconsistency is pre-existing and is
left alone rather than "fixed" in passing: every current caller passes an
explicit path, and changing the default would silently redirect all of them.

Writes are whole-board and transactional. A storyboard is small (tens of rows)
and partially-written boards are the kind of state that produces a render with
half a cast, so `save_board` deletes and reinserts the children inside one
transaction rather than trying to diff.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from omnicast.storyboard.models import (
    Angle,
    BoardStatus,
    CameraShot,
    Entity,
    EntityImage,
    EntityKind,
    Frame,
    FrameType,
    ImageSource,
    Movement,
    RefMapping,
    RefRole,
    ScreenDirection,
    Shot,
    ShotEntityRef,
    Storyboard,
    normalize_name,
)

#: implementation/output/vault.db — see the module docstring before changing.
_IMPL_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = _IMPL_ROOT / "output" / "vault.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sb_boards (
    board_id        TEXT PRIMARY KEY,
    channel_id      TEXT NOT NULL,
    product_slug    TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'draft',
    script_hash     TEXT NOT NULL DEFAULT '',
    style_prompt    TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT '',
    approved_at     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sb_boards_channel ON sb_boards(channel_id, status);

CREATE TABLE IF NOT EXISTS sb_entities (
    entity_id       TEXT PRIMARY KEY,
    board_id        TEXT NOT NULL REFERENCES sb_boards(board_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    aliases         TEXT NOT NULL DEFAULT '[]',
    traits          TEXT NOT NULL DEFAULT '{}',
    tags            TEXT NOT NULL DEFAULT '[]',
    costume_id      TEXT,
    owner_id        TEXT,
    view_count      INTEGER NOT NULL DEFAULT 3,
    conflicts       TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_sb_entities_board ON sb_entities(board_id, kind);
-- Two cast members with the same folded name on one board is the drift this
-- package exists to prevent; make the database refuse it outright.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sb_entities_unique
    ON sb_entities(board_id, kind, normalized_name);

CREATE TABLE IF NOT EXISTS sb_entity_images (
    image_id    TEXT PRIMARY KEY,
    entity_id   TEXT NOT NULL REFERENCES sb_entities(entity_id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    view        TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'identity',
    source      TEXT NOT NULL DEFAULT 'generated',
    approved    INTEGER NOT NULL DEFAULT 0,
    prompt_used TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sb_images_entity ON sb_entity_images(entity_id);

CREATE TABLE IF NOT EXISTS sb_shots (
    shot_id             TEXT PRIMARY KEY,
    board_id            TEXT NOT NULL REFERENCES sb_boards(board_id) ON DELETE CASCADE,
    idx                 INTEGER NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    script_excerpt      TEXT NOT NULL DEFAULT '',
    voiceover           TEXT NOT NULL DEFAULT '',
    location_id         TEXT,
    camera_shot         TEXT NOT NULL DEFAULT 'MS',
    angle               TEXT NOT NULL DEFAULT 'EYE_LEVEL',
    movement            TEXT NOT NULL DEFAULT 'STATIC',
    duration_s          REAL NOT NULL DEFAULT 0,
    action_beats        TEXT NOT NULL DEFAULT '[]',
    mood                TEXT NOT NULL DEFAULT '',
    transition          TEXT NOT NULL DEFAULT 'cut',
    parent_shot_id      TEXT,
    planned_start_state TEXT NOT NULL DEFAULT '',
    observed_end_state  TEXT NOT NULL DEFAULT '',
    declared_changes    TEXT NOT NULL DEFAULT '[]',
    screen_direction    TEXT NOT NULL DEFAULT 'unset',
    eyeline             TEXT NOT NULL DEFAULT '',
    light_key           TEXT NOT NULL DEFAULT '',
    time_of_day         TEXT NOT NULL DEFAULT '',
    motion_vector       TEXT NOT NULL DEFAULT '',
    sound_state         TEXT NOT NULL DEFAULT '',
    beats_completed     TEXT NOT NULL DEFAULT '[]',
    beats_reserved      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_sb_shots_board ON sb_shots(board_id, idx);

CREATE TABLE IF NOT EXISTS sb_shot_entities (
    shot_id   TEXT NOT NULL REFERENCES sb_shots(shot_id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL,
    idx       INTEGER NOT NULL DEFAULT 0,
    role      TEXT,
    note      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (shot_id, entity_id)
);

CREATE TABLE IF NOT EXISTS sb_frames (
    frame_id        TEXT PRIMARY KEY,
    shot_id         TEXT NOT NULL REFERENCES sb_shots(shot_id) ON DELETE CASCADE,
    frame_type      TEXT NOT NULL DEFAULT 'key',
    base_prompt     TEXT NOT NULL DEFAULT '',
    rendered_prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    mappings        TEXT NOT NULL DEFAULT '[]',
    image_path      TEXT NOT NULL DEFAULT '',
    approved        INTEGER NOT NULL DEFAULT 0,
    attempts        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sb_frames_shot ON sb_frames(shot_id);
"""


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


#: Columns added to `sb_shots` after the first release. `CREATE TABLE IF NOT
#: EXISTS` is a no-op on an existing table, so a database created before these
#: fields existed would keep loading boards until the first SELECT named one
#: and failed. Each entry is (column, DDL type + default).
_SHOT_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("screen_direction", "TEXT NOT NULL DEFAULT 'unset'"),
    ("eyeline", "TEXT NOT NULL DEFAULT ''"),
    ("light_key", "TEXT NOT NULL DEFAULT ''"),
    ("time_of_day", "TEXT NOT NULL DEFAULT ''"),
    ("motion_vector", "TEXT NOT NULL DEFAULT ''"),
    ("sound_state", "TEXT NOT NULL DEFAULT ''"),
    ("beats_completed", "TEXT NOT NULL DEFAULT '[]'"),
    ("beats_reserved", "TEXT NOT NULL DEFAULT '[]'"),
)


def init_storyboard_db(path: Path | None = None) -> None:
    """Create the storyboard tables and bring old ones forward.

    Safe to call repeatedly — every statement is idempotent.
    """
    with _connect(path) as conn:
        conn.executescript(_SCHEMA)
        existing = {row["name"] for row in
                    conn.execute("PRAGMA table_info(sb_shots)")}
        for column, ddl in _SHOT_MIGRATIONS:
            if column not in existing:
                conn.execute(f"ALTER TABLE sb_shots ADD COLUMN {column} {ddl}")
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


# --------------------------------------------------------------------------
# Write
# --------------------------------------------------------------------------

def save_board(board: Storyboard, path: Path | None = None) -> None:
    """Persist a whole board, replacing any previous version of it.

    One transaction: a board that lost half its cast to a mid-write failure
    would still be `cast_approved` and would render with invented faces.
    """
    init_storyboard_db(path)
    created = board.created_at or _now()
    with _connect(path) as conn:
        conn.execute("BEGIN")
        conn.execute(
            """INSERT INTO sb_boards (board_id, channel_id, product_slug, title,
                   status, script_hash, style_prompt, negative_prompt, notes,
                   created_at, approved_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(board_id) DO UPDATE SET
                   channel_id=excluded.channel_id,
                   product_slug=excluded.product_slug,
                   title=excluded.title,
                   status=excluded.status,
                   script_hash=excluded.script_hash,
                   style_prompt=excluded.style_prompt,
                   negative_prompt=excluded.negative_prompt,
                   notes=excluded.notes,
                   approved_at=excluded.approved_at""",
            (board.board_id, board.channel_id, board.product_slug, board.title,
             board.status.value, board.script_hash, board.style_prompt,
             board.negative_prompt, json.dumps(board.notes, ensure_ascii=False),
             created, board.approved_at),
        )
        # Children are rebuilt wholesale. ON DELETE CASCADE takes the images,
        # shot links and frames with their parents.
        conn.execute("DELETE FROM sb_entities WHERE board_id=?", (board.board_id,))
        conn.execute("DELETE FROM sb_shots WHERE board_id=?", (board.board_id,))

        for e in board.entities:
            conn.execute(
                """INSERT INTO sb_entities (entity_id, board_id, kind, name,
                       normalized_name, description, aliases, traits, tags,
                       costume_id, owner_id, view_count, conflicts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (e.entity_id, board.board_id, e.kind.value, e.name,
                 normalize_name(e.name), e.description,
                 json.dumps(e.aliases, ensure_ascii=False),
                 json.dumps(e.traits, ensure_ascii=False),
                 json.dumps(e.tags, ensure_ascii=False),
                 e.costume_id, e.owner_id, e.view_count,
                 json.dumps(e.conflicts, ensure_ascii=False)),
            )
            for im in e.images:
                conn.execute(
                    """INSERT INTO sb_entity_images (image_id, entity_id, path,
                           view, role, source, approved, prompt_used, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (im.image_id, e.entity_id, im.path, im.view, im.role.value,
                     im.source.value, 1 if im.approved else 0, im.prompt_used,
                     im.created_at or _now()),
                )

        for s in board.shots:
            conn.execute(
                """INSERT INTO sb_shots (shot_id, board_id, idx, title,
                       script_excerpt, voiceover, location_id, camera_shot,
                       angle, movement, duration_s, action_beats, mood,
                       transition, parent_shot_id, planned_start_state,
                       observed_end_state, declared_changes, screen_direction,
                       eyeline, light_key, time_of_day, motion_vector,
                       sound_state, beats_completed, beats_reserved)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (s.shot_id, board.board_id, s.index, s.title, s.script_excerpt,
                 s.voiceover, s.location_id, s.camera_shot.value, s.angle.value,
                 s.movement.value, s.duration_s,
                 json.dumps(s.action_beats, ensure_ascii=False), s.mood,
                 s.transition, s.parent_shot_id, s.planned_start_state,
                 s.observed_end_state,
                 json.dumps(s.declared_changes, ensure_ascii=False),
                 s.screen_direction.value, s.eyeline, s.light_key,
                 s.time_of_day, s.motion_vector, s.sound_state,
                 json.dumps(s.beats_completed, ensure_ascii=False),
                 json.dumps(s.beats_reserved, ensure_ascii=False)),
            )
            for c in s.cast:
                conn.execute(
                    """INSERT INTO sb_shot_entities (shot_id, entity_id, idx,
                           role, note) VALUES (?,?,?,?,?)
                       ON CONFLICT(shot_id, entity_id) DO UPDATE SET
                           idx=excluded.idx, role=excluded.role,
                           note=excluded.note""",
                    (s.shot_id, c.entity_id, c.index,
                     c.role.value if c.role else None, c.note),
                )

        for f in board.frames:
            conn.execute(
                """INSERT INTO sb_frames (frame_id, shot_id, frame_type,
                       base_prompt, rendered_prompt, negative_prompt, mappings,
                       image_path, approved, attempts)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (f.frame_id, f.shot_id, f.frame_type.value, f.base_prompt,
                 f.rendered_prompt, f.negative_prompt,
                 json.dumps([m.model_dump(mode="json") for m in f.mappings],
                            ensure_ascii=False),
                 f.image_path, 1 if f.approved else 0, f.attempts),
            )
        conn.commit()


def set_status(board_id: str, status: BoardStatus, path: Path | None = None) -> None:
    """Move a board through the approval flow without rewriting its contents."""
    approved_at = _now() if status is BoardStatus.APPROVED else ""
    with _connect(path) as conn:
        conn.execute(
            "UPDATE sb_boards SET status=?, approved_at=CASE WHEN ?<>'' THEN ? "
            "ELSE approved_at END WHERE board_id=?",
            (status.value, approved_at, approved_at, board_id))
        conn.commit()


def set_image_approved(image_id: str, approved: bool,
                       path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("UPDATE sb_entity_images SET approved=? WHERE image_id=?",
                     (1 if approved else 0, image_id))
        conn.commit()


def add_entity_image(image: EntityImage, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute(
            """INSERT INTO sb_entity_images (image_id, entity_id, path, view,
                   role, source, approved, prompt_used, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(image_id) DO UPDATE SET
                   path=excluded.path, view=excluded.view, role=excluded.role,
                   source=excluded.source, approved=excluded.approved,
                   prompt_used=excluded.prompt_used""",
            (image.image_id, image.entity_id, image.path, image.view,
             image.role.value, image.source.value, 1 if image.approved else 0,
             image.prompt_used, image.created_at or _now()))
        conn.commit()


def update_frame(frame: Frame, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute(
            """UPDATE sb_frames SET base_prompt=?, rendered_prompt=?,
                   negative_prompt=?, mappings=?, image_path=?, approved=?,
                   attempts=? WHERE frame_id=?""",
            (frame.base_prompt, frame.rendered_prompt, frame.negative_prompt,
             json.dumps([m.model_dump(mode="json") for m in frame.mappings],
                        ensure_ascii=False),
             frame.image_path, 1 if frame.approved else 0, frame.attempts,
             frame.frame_id))
        conn.commit()


def delete_board(board_id: str, path: Path | None = None) -> None:
    with _connect(path) as conn:
        conn.execute("DELETE FROM sb_boards WHERE board_id=?", (board_id,))
        conn.commit()


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------

def _row_to_entity(row: sqlite3.Row, images: list[EntityImage]) -> Entity:
    return Entity(
        entity_id=row["entity_id"],
        board_id=row["board_id"],
        kind=EntityKind(row["kind"]),
        name=row["name"],
        description=row["description"],
        aliases=_loads(row["aliases"], []),
        traits=_loads(row["traits"], {}),
        tags=_loads(row["tags"], []),
        costume_id=row["costume_id"],
        owner_id=row["owner_id"],
        view_count=row["view_count"],
        images=images,
        conflicts=_loads(row["conflicts"], []),
    )


def _row_to_shot(row: sqlite3.Row, cast: list[ShotEntityRef]) -> Shot:
    return Shot(
        shot_id=row["shot_id"],
        board_id=row["board_id"],
        index=row["idx"],
        title=row["title"],
        script_excerpt=row["script_excerpt"],
        voiceover=row["voiceover"],
        location_id=row["location_id"],
        cast=cast,
        camera_shot=CameraShot(row["camera_shot"]),
        angle=Angle(row["angle"]),
        movement=Movement(row["movement"]),
        duration_s=row["duration_s"],
        action_beats=_loads(row["action_beats"], []),
        mood=row["mood"],
        transition=row["transition"],
        parent_shot_id=row["parent_shot_id"],
        planned_start_state=row["planned_start_state"],
        observed_end_state=row["observed_end_state"],
        declared_changes=_loads(row["declared_changes"], []),
        screen_direction=ScreenDirection(row["screen_direction"] or "unset"),
        eyeline=row["eyeline"] or "",
        light_key=row["light_key"] or "",
        time_of_day=row["time_of_day"] or "",
        motion_vector=row["motion_vector"] or "",
        sound_state=row["sound_state"] or "",
        beats_completed=_loads(row["beats_completed"], []),
        beats_reserved=_loads(row["beats_reserved"], []),
    )


def load_board(board_id: str, path: Path | None = None) -> Storyboard | None:
    """Rebuild a whole board, or None if it does not exist."""
    init_storyboard_db(path)
    with _connect(path) as conn:
        brow = conn.execute("SELECT * FROM sb_boards WHERE board_id=?",
                            (board_id,)).fetchone()
        if brow is None:
            return None

        images: dict[str, list[EntityImage]] = {}
        for r in conn.execute(
                """SELECT i.* FROM sb_entity_images i
                   JOIN sb_entities e ON e.entity_id = i.entity_id
                   WHERE e.board_id=? ORDER BY i.created_at, i.image_id""",
                (board_id,)):
            images.setdefault(r["entity_id"], []).append(EntityImage(
                image_id=r["image_id"], entity_id=r["entity_id"], path=r["path"],
                view=r["view"], role=RefRole(r["role"]),
                source=ImageSource(r["source"]), approved=bool(r["approved"]),
                prompt_used=r["prompt_used"], created_at=r["created_at"]))

        entities = [
            _row_to_entity(r, images.get(r["entity_id"], []))
            for r in conn.execute(
                "SELECT * FROM sb_entities WHERE board_id=? ORDER BY kind, name",
                (board_id,))
        ]

        cast: dict[str, list[ShotEntityRef]] = {}
        for r in conn.execute(
                """SELECT se.* FROM sb_shot_entities se
                   JOIN sb_shots s ON s.shot_id = se.shot_id
                   WHERE s.board_id=? ORDER BY se.idx""", (board_id,)):
            cast.setdefault(r["shot_id"], []).append(ShotEntityRef(
                entity_id=r["entity_id"], index=r["idx"],
                role=RefRole(r["role"]) if r["role"] else None,
                note=r["note"]))

        shots = [
            _row_to_shot(r, cast.get(r["shot_id"], []))
            for r in conn.execute(
                "SELECT * FROM sb_shots WHERE board_id=? ORDER BY idx", (board_id,))
        ]

        frames: list[Frame] = []
        for r in conn.execute(
                """SELECT f.* FROM sb_frames f JOIN sb_shots s
                   ON s.shot_id = f.shot_id WHERE s.board_id=?
                   ORDER BY s.idx, f.frame_type""", (board_id,)):
            frames.append(Frame(
                frame_id=r["frame_id"], shot_id=r["shot_id"],
                frame_type=FrameType(r["frame_type"]),
                base_prompt=r["base_prompt"],
                rendered_prompt=r["rendered_prompt"],
                negative_prompt=r["negative_prompt"],
                mappings=[RefMapping(**m) for m in _loads(r["mappings"], [])],
                image_path=r["image_path"], approved=bool(r["approved"]),
                attempts=r["attempts"]))

        return Storyboard(
            board_id=brow["board_id"], channel_id=brow["channel_id"],
            product_slug=brow["product_slug"], title=brow["title"],
            status=BoardStatus(brow["status"]), script_hash=brow["script_hash"],
            style_prompt=brow["style_prompt"],
            negative_prompt=brow["negative_prompt"],
            entities=entities, shots=shots, frames=frames,
            notes=_loads(brow["notes"], []),
            created_at=brow["created_at"], approved_at=brow["approved_at"])


def list_boards(channel_id: str | None = None, status: BoardStatus | None = None,
                path: Path | None = None) -> list[dict]:
    """Board headers for the dashboard — deliberately not the whole graph."""
    init_storyboard_db(path)
    sql = ("SELECT board_id, channel_id, product_slug, title, status, "
           "created_at, approved_at FROM sb_boards")
    where, args = [], []
    if channel_id:
        where.append("channel_id=?")
        args.append(channel_id)
    if status:
        where.append("status=?")
        args.append(status.value)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC"
    with _connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def find_board_by_script(channel_id: str, script_hash: str,
                         path: Path | None = None) -> str | None:
    """Existing board for this exact script, so a re-run resumes instead of
    re-extracting (and re-charging for) a cast the operator already approved."""
    init_storyboard_db(path)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT board_id FROM sb_boards WHERE channel_id=? AND script_hash=? "
            "ORDER BY created_at DESC LIMIT 1", (channel_id, script_hash)).fetchone()
        return row["board_id"] if row else None
