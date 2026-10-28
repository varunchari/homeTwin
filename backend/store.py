"""SQLite store for photos, regions, and the scene graph (Day 2).

Stable spatial object IDs: ``{slug}-{n}`` per photo, persisted, so a
reload returns the identical graph. Bboxes stored relative (0..1).
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
PHOTOS_DIR = DATA_DIR / "photos"
MASKS_DIR = DATA_DIR / "masks"
PHOTOS_DIR.mkdir(exist_ok=True)
MASKS_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "hometwin.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS regions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  photo_id INTEGER NOT NULL REFERENCES photos(id),
  object_id TEXT NOT NULL,
  source TEXT NOT NULL,          -- 'sam' or 'manual'
  phrase TEXT NOT NULL,
  x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
  mask_path TEXT,
  created REAL NOT NULL,
  UNIQUE(photo_id, object_id)
);
CREATE TABLE IF NOT EXISTS bindings (
  photo_id INTEGER NOT NULL REFERENCES photos(id),
  object_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  created REAL NOT NULL,
  PRIMARY KEY (photo_id, object_id)
);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  photo_id INTEGER NOT NULL,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  text TEXT NOT NULL,
  ir TEXT NOT NULL,
  compiled TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created REAL NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        conn.execute("ALTER TABLE photos ADD COLUMN sha TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    # Backfill sha for photos stored before the column existed.
    import hashlib
    for row in conn.execute("SELECT id FROM photos WHERE sha IS NULL").fetchall():
        path = PHOTOS_DIR / f"{row['id']}.jpg"
        if path.is_file():
            conn.execute("UPDATE photos SET sha=? WHERE id=?",
                         (hashlib.sha256(path.read_bytes()).hexdigest(), row["id"]))
    conn.commit()
    return conn


def slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return text or "region"


def next_object_id(conn: sqlite3.Connection, photo_id: int, stem: str) -> str:
    n = conn.execute(
        "SELECT COUNT(*) FROM regions WHERE photo_id=? AND (object_id=? OR object_id LIKE ?)",
        (photo_id, stem, f"{stem}-%"),
    ).fetchone()[0]
    return stem if n == 0 else f"{stem}-{n + 1}"


def add_photo(filename: str, width: int, height: int) -> int:
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO photos (filename, width, height, created) VALUES (?,?,?,?)",
            (filename, width, height, time.time()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def find_photo_by_sha(sha: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM photos WHERE sha=? ORDER BY id DESC LIMIT 1",
                           (sha,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_photo_sha(photo_id: int, sha: str) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE photos SET sha=? WHERE id=?", (sha, photo_id))
        conn.commit()
    finally:
        conn.close()


def get_photo(photo_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def add_region(photo_id: int, source: str, phrase: str,
               x: float, y: float, w: float, h: float,
               mask_png: bytes | None = None) -> dict:
    conn = connect()
    try:
        object_id = next_object_id(conn, photo_id, slug(phrase))
        mask_path = None
        if mask_png:
            mask_path = str(MASKS_DIR / f"{photo_id}-{object_id}.png")
            Path(mask_path).write_bytes(mask_png)
        conn.execute(
            "INSERT INTO regions (photo_id, object_id, source, phrase, x, y, w, h, mask_path, created)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (photo_id, object_id, source, phrase, x, y, w, h, mask_path, time.time()),
        )
        conn.commit()
        return {"object_id": object_id, "source": source, "phrase": phrase,
                "x": x, "y": y, "w": w, "h": h, "has_mask": mask_png is not None}
    finally:
        conn.close()


def get_binding(photo_id: int, object_id: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT entity_id FROM bindings WHERE photo_id=? AND object_id=?",
            (photo_id, object_id)).fetchone()
        return row["entity_id"] if row else None
    finally:
        conn.close()


def set_binding(photo_id: int, object_id: str, entity_id: str) -> None:
    import time
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO bindings (photo_id, object_id, entity_id, created)"
            " VALUES (?,?,?,?) ON CONFLICT(photo_id, object_id)"
            " DO UPDATE SET entity_id=excluded.entity_id",
            (photo_id, object_id, entity_id, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def delete_phrase_regions(photo_id: int, phrase: str) -> list[str]:
    """Delete SAM regions for one phrase (segment refresh). Returns removed
    object_ids so callers can drop orphaned bindings."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT object_id, mask_path FROM regions"
            " WHERE photo_id=? AND phrase=? AND source='sam'",
            (photo_id, phrase)).fetchall()
        removed = [r["object_id"] for r in rows]
        conn.execute(
            "DELETE FROM regions WHERE photo_id=? AND phrase=? AND source='sam'",
            (photo_id, phrase))
        conn.commit()
    finally:
        conn.close()
    for r in rows:
        if r["mask_path"]:
            Path(r["mask_path"]).unlink(missing_ok=True)
    return removed


def delete_binding(photo_id: int, object_id: str) -> bool:
    conn = connect()
    try:
        cur = conn.execute(
            "DELETE FROM bindings WHERE photo_id=? AND object_id=?",
            (photo_id, object_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def save_proposal(photo_id: int, source_id: str, target_id: str, text: str,
                  ir: dict, compiled: dict) -> int:
    import json
    import time
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO proposals (photo_id, source_id, target_id, text, ir,"
            " compiled, status, created) VALUES (?,?,?,?,?,?, 'pending', ?)",
            (photo_id, source_id, target_id, text,
             json.dumps(ir), json.dumps(compiled), time.time()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_proposal(proposal_id: int) -> dict | None:
    import json
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM proposals WHERE id=?",
                           (proposal_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["ir"] = json.loads(d["ir"])
        d["compiled"] = json.loads(d["compiled"])
        return d
    finally:
        conn.close()


def list_proposals(photo_id: int | None = None) -> list[dict]:
    import json
    conn = connect()
    try:
        if photo_id is None:
            rows = conn.execute(
                "SELECT id, photo_id, source_id, target_id, text, ir, status, created"
                " FROM proposals ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT id, photo_id, source_id, target_id, text, ir, status, created"
                " FROM proposals WHERE photo_id=? ORDER BY id",
                (photo_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            ir = json.loads(d.pop("ir"))
            d["summary"] = (f"{ir['trigger']['entity_id']} to "
                            f"{ir['action']['entity_id']}")
            out.append(d)
        return out
    finally:
        conn.close()


def set_proposal_status(proposal_id: int, status: str) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal_id))
        conn.commit()
    finally:
        conn.close()


def list_bindings(photo_id: int) -> dict[str, str]:
    conn = connect()
    try:
        return {r["object_id"]: r["entity_id"] for r in conn.execute(
            "SELECT object_id, entity_id FROM bindings WHERE photo_id=?", (photo_id,))}
    finally:
        conn.close()


def scene_graph(photo_id: int) -> dict | None:
    conn = connect()
    try:
        photo = conn.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not photo:
            return None
        regions = conn.execute(
            "SELECT object_id, source, phrase, x, y, w, h,"
            " CASE WHEN mask_path IS NOT NULL THEN 1 ELSE 0 END AS has_mask"
            " FROM regions WHERE photo_id=? ORDER BY object_id",
            (photo_id,),
        ).fetchall()
        bindings = {r["object_id"]: r["entity_id"] for r in conn.execute(
            "SELECT object_id, entity_id FROM bindings WHERE photo_id=?", (photo_id,))}
        return {"photo": dict(photo), "regions": [dict(r) for r in regions],
                "bindings": bindings}
    finally:
        conn.close()
