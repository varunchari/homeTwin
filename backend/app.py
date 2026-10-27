"""HomeTwin Day 1 backend proxy.

HA owns device state. This proxy mediates every HA operation so the
browser never holds HA credentials. Day 1 scope: entity query, light
toggle, WebSocket state_changed fan-out. No SAM/Spark logic yet.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sam_client import SAM_MODEL, SamError, segment_image
from store import DATA_DIR, DB_PATH, MASKS_DIR, PHOTOS_DIR, add_photo, add_region, get_photo, scene_graph

SAM_EST_COST_USD = 0.0025  # $2.50/1k images; one request bills one image (assumption)

HA_URL = os.environ.get("HA_URL", "http://ha:8123").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
_HERE = Path(__file__).resolve().parent
FRONTEND_DIR = _HERE / "frontend"
if not FRONTEND_DIR.is_dir():
    FRONTEND_DIR = _HERE.parent / "frontend"  # local checkout layout

app = FastAPI(title="HomeTwin backend (Day 1)")


def _headers() -> dict[str, str]:
    if not HA_TOKEN:
        raise HTTPException(status_code=500, detail="HA_TOKEN is not configured")
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/entities")
async def entities() -> list[dict]:
    """Query current HA states (Day 1 exit: returns all entities)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{HA_URL}/api/states", headers=_headers())
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"HA query failed: {resp.status_code}")
    states = resp.json()
    return [
        {
            "entity_id": s.get("entity_id"),
            "state": s.get("state"),
            "attributes": s.get("attributes", {}),
        }
        for s in states
    ]


class ToggleRequest(BaseModel):
    entity_id: str


@app.post("/api/toggle")
async def toggle(req: ToggleRequest) -> dict:
    """Toggle a light via the HA API. Day 1 allowlist: light.* only."""
    domain, _, _ = req.entity_id.partition(".")
    if domain != "light":
        raise HTTPException(status_code=422, detail="Day 1 supports light.* toggle only")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{HA_URL}/api/services/light/toggle",
            headers=_headers(),
            json={"entity_id": req.entity_id},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"HA toggle failed: {resp.status_code}")
    return {"ok": True, "entity_id": req.entity_id}


# --- WebSocket fan-out: one shared HA listener, many browser clients ---

_clients: set[WebSocket] = set()
_ha_task: asyncio.Task | None = None


def _ha_ws_url() -> str:
    override = os.environ.get("HA_WS_URL", "").rstrip("/")
    if override:
        return override + "/api/websocket"
    base = HA_URL.replace("https://", "wss://").replace("http://", "ws://")
    return base + "/api/websocket"


async def _ha_listener() -> None:
    """Subscribe to HA state_changed and rebroadcast to browser clients."""
    global _ha_task
    try:
        async with websockets.connect(_ha_ws_url(), max_size=2**20) as ws:
            # HA auth phase
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("type") != "auth_required":
                return
            await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
            raw = await ws.recv()
            if json.loads(raw).get("type") != "auth_ok":
                return
            await ws.send(
                json.dumps(
                    {"id": 1, "type": "subscribe_events", "event_type": "state_changed"}
                )
            )
            async for raw in ws:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if event.get("type") != "event":
                    continue
                dead = set()
                for client in _clients:
                    try:
                        await client.send_json(event["event"])
                    except Exception:
                        dead.add(client)
                for client in dead:
                    _clients.discard(client)
    finally:
        _ha_task = None


async def _ensure_listener() -> None:
    global _ha_task
    if _ha_task is None or _ha_task.done():
        _ha_task = asyncio.create_task(_ha_listener())


@app.websocket("/ws")
async def ws_feed(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)
    await _ensure_listener()
    try:
        while True:
            await ws.receive_text()  # keepalive; client messages ignored Day 1
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)


if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))


# --- Day 2: photo upload, SAM segmentation, scene graph, manual fallback ---

SAM_PHRASES = ["lamp", "string lights", "patio door", "tv", "smart display", "reading light"]


def _photo_bytes(photo_id: int) -> tuple[dict, bytes]:
    photo = get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="unknown photo")
    path = PHOTOS_DIR / f"{photo_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="photo file missing")
    return photo, path.read_bytes()


def _to_relative(bbox: tuple | None, mask_png: bytes | None,
                 width: int, height: int) -> tuple | None:
    if bbox is None and mask_png:
        try:
            from io import BytesIO
            from PIL import Image
            img = Image.open(BytesIO(mask_png)).convert("L")
            box = img.getbbox()
            if box:
                bbox = box
        except Exception:
            bbox = None
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    x = min(max(left / width, 0.0), 1.0)
    y = min(max(top / height, 0.0), 1.0)
    w = min(max((right - left) / width, 0.0), 1.0 - x)
    h = min(max((bottom - top) / height, 0.0), 1.0 - y)
    return (x, y, w, h) if w > 0 and h > 0 else None


def _log_sam_call(**row) -> None:
    import json
    import time
    row.setdefault("ts", time.time())
    with open(DATA_DIR / "sam_calls.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")


@app.post("/api/photos")
async def upload_photo(file: UploadFile) -> dict:
    from io import BytesIO
    from PIL import Image
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="photo too large (15 MB max)")
    try:
        img = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=415, detail="unreadable image (JPEG/PNG only)")
    width, height = img.size
    photo_id = add_photo(file.filename or "photo", width, height)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=92)
    (PHOTOS_DIR / f"{photo_id}.jpg").write_bytes(buf.getvalue())
    return {"photo_id": photo_id, "width": width, "height": height}


@app.get("/api/photos/{photo_id}/image")
async def photo_image(photo_id: int) -> FileResponse:
    _, _ = _photo_bytes(photo_id)
    return FileResponse(str(PHOTOS_DIR / f"{photo_id}.jpg"), media_type="image/jpeg")


class SegmentRequest(BaseModel):
    phrase: str


def _phrase_variants(phrase: str) -> list[str]:
    """Full phrase first, then progressively simpler tails ("smart display" -> "display")."""
    words = phrase.split()
    variants = [phrase]
    for i in range(1, len(words)):
        tail = " ".join(words[i:])
        if tail not in variants:
            variants.append(tail)
    return variants


def _iou(a: tuple, b: tuple) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    union = aw * ah + bw * bh - ix * iy
    return ix * iy / union if union > 0 else 0.0


def _dedupe(rels: list[tuple]) -> list[dict]:
    """Merge near-duplicate boxes (IoU > 0.9), preferring the entry with a mask.

    SAM emits a box record and a mask record per instance.
    """
    merged: list[dict] = []
    for rel, mask_png in sorted(rels, key=lambda t: t[1] is None):
        for entry in merged:
            if _iou(rel, entry["rel"]) > 0.9:
                if mask_png is not None and entry["mask_png"] is None:
                    entry["mask_png"] = mask_png
                break
        else:
            merged.append({"rel": rel, "mask_png": mask_png})
    return merged


@app.post("/api/photos/{photo_id}/segment")
async def segment_photo(photo_id: int, req: SegmentRequest) -> dict:
    import time
    photo, raw = _photo_bytes(photo_id)
    phrase = " ".join(req.phrase.split())
    if not phrase:
        raise HTTPException(status_code=422, detail="empty phrase")
    matched: str | None = None
    found: list = []
    total_ms = 0
    for variant in _phrase_variants(phrase):
        t0 = time.monotonic()
        try:
            found = await segment_image(raw, variant)
        except SamError as e:
            _log_sam_call(model=SAM_MODEL, phrase=variant, photo_id=photo_id,
                          latency_ms=int((time.monotonic() - t0) * 1000),
                          n_regions=0, status=f"error: {e}",
                          est_cost_usd=SAM_EST_COST_USD)
            raise HTTPException(status_code=502, detail=f"SAM failed: {e}. Use manual fallback.")
        latency_ms = int((time.monotonic() - t0) * 1000)
        total_ms += latency_ms
        if found:
            matched = variant
            _log_sam_call(model=SAM_MODEL, phrase=variant, photo_id=photo_id,
                          latency_ms=latency_ms, n_regions=len(found), status="ok",
                          est_cost_usd=SAM_EST_COST_USD)
            break
        _log_sam_call(model=SAM_MODEL, phrase=variant, photo_id=photo_id,
                      latency_ms=latency_ms, n_regions=0, status="ok-empty",
                      est_cost_usd=SAM_EST_COST_USD)
    if matched is None:
        return {"photo_id": photo_id, "phrase": phrase, "matched_phrase": None,
                "latency_ms": total_ms, "regions": [], "suggested_phrases": SAM_PHRASES,
                "note": "No match for any variant. Draw the region manually."}
    rels = []
    for item in found:
        rel = _to_relative(item["bbox"], item["mask_png"], photo["width"], photo["height"])
        if rel is None:
            continue
        rels.append((rel, item["mask_png"]))
    regions = []
    for entry in _dedupe(rels):
        regions.append(add_region(photo_id, "sam", matched, *entry["rel"],
                                  mask_png=entry["mask_png"]))
    return {"photo_id": photo_id, "phrase": phrase, "matched_phrase": matched,
            "latency_ms": total_ms, "regions": regions,
            "suggested_phrases": SAM_PHRASES}


@app.delete("/api/photos/{photo_id}/regions/{object_id}")
async def delete_region(photo_id: int, object_id: str) -> dict:
    """Remove one region (graph curation, e.g. cross-phrase duplicates)."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("DELETE FROM regions WHERE photo_id=? AND object_id=?",
                           (photo_id, object_id))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="unknown region")
        for p in MASKS_DIR.glob(f"{photo_id}-{object_id}.png"):
            p.unlink(missing_ok=True)
        return {"ok": True, "object_id": object_id}
    finally:
        conn.close()


@app.get("/api/photos/{photo_id}/graph")
async def photo_graph(photo_id: int) -> dict:
    graph = scene_graph(photo_id)
    if not graph:
        raise HTTPException(status_code=404, detail="unknown photo")
    return graph


class ManualRegionRequest(BaseModel):
    label: str
    x: float
    y: float
    w: float
    h: float


@app.post("/api/photos/{photo_id}/regions")
async def manual_region(photo_id: int, req: ManualRegionRequest) -> dict:
    if not get_photo(photo_id):
        raise HTTPException(status_code=404, detail="unknown photo")
    label = " ".join(req.label.split())
    if not label:
        raise HTTPException(status_code=422, detail="empty label")
    for v in (req.x, req.y, req.w, req.h):
        if not 0.0 <= v <= 1.0:
            raise HTTPException(status_code=422, detail="box must be relative 0..1")
    if req.w <= 0 or req.h <= 0 or req.x + req.w > 1.0 or req.y + req.h > 1.0:
        raise HTTPException(status_code=422, detail="invalid box")
    return add_region(photo_id, "manual", label, req.x, req.y, req.w, req.h)
