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
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
        return {"photo": dict(photo), "regions": [dict(r) for r in regions]}
    finally:
        conn.close()
