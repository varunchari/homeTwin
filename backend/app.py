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
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sam_client import SAM_MODEL, SamError, segment_image
from store import (DATA_DIR, DB_PATH, MASKS_DIR, PHOTOS_DIR, add_photo, add_region,
                     delete_binding, delete_phrase_regions, find_photo_by_sha,
                     get_binding, get_photo, list_bindings, scene_graph,
                     set_binding, set_photo_sha)

SAM_EST_COST_USD = 0.0025  # $2.50/1k images; one request bills one image (assumption)

HA_URL = os.environ.get("HA_URL", "http://ha:8123").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
_HERE = Path(__file__).resolve().parent
FRONTEND_DIR = _HERE / "frontend"
if not FRONTEND_DIR.is_dir():
    FRONTEND_DIR = _HERE.parent / "frontend"  # local checkout layout

app = FastAPI(title="HomeTwin backend (Day 1)")


def _limit_model(request: Request) -> None:
    """Public-demo guard for model-costly endpoints only. Tap, bind,
    What-If, approve and reset are not limited."""
    from rate_limit import (MODEL_RATE_LIMIT, MODEL_RATE_WINDOW_S,
                            check_model_rate, client_ip)

    # Test clients have no real address (host is literally "testclient")
    # and run the whole suite from one process; limiting them would
    # break the test suite without protecting any real demo visitor.
    if client_ip(request) == "testclient":
        return

    if not check_model_rate(client_ip(request)):
        raise HTTPException(
            status_code=429,
            detail=(f"Too many model requests from this address "
                    f"(limit {MODEL_RATE_LIMIT} per {MODEL_RATE_WINDOW_S // 60} minutes). "
                    "Tap, bind, What-If and Reset are not limited — "
                    "wait a few minutes and retry the model step."))


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
    async def index() -> Response:
        # Never cache the shell: otherwise browsers keep showing a stale UI
        # after deploys. Asset URLs carry the files' mtime so a new deploy
        # is a new URL and cannot be served from cache either.
        from fastapi.responses import HTMLResponse

        def _v(name: str) -> str:
            try:
                return str(int((FRONTEND_DIR / name).stat().st_mtime))
            except OSError:
                return "0"

        html = (FRONTEND_DIR / "index.html").read_text()
        html = html.replace("/static/app.js", f"/static/app.js?v={_v('app.js')}")
        html = html.replace("/static/app.css", f"/static/app.css?v={_v('app.css')}")
        return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})


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
async def upload_photo(request: Request, file: UploadFile) -> dict:
    """Upload a photo, use it directly, and auto-segment all suggested phrases.

    Same bytes re-uploaded return the existing photo (no duplicate SAM spend).
    """
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="photo too large (15 MB max)")
    _limit_model(request)
    return await _ingest_photo(raw, file.filename or "photo")


DEMO_PHOTO_PATH = _HERE / "assets" / "demo-room" / "dummy-room.jpg"
if not DEMO_PHOTO_PATH.is_file():
    DEMO_PHOTO_PATH = _HERE.parent / "assets" / "demo-room" / "dummy-room.jpg"


@app.post("/api/photos/demo")
async def load_demo_photo() -> dict:
    """Load the frozen demo room photo as an explicit user action.

    Same pipeline as upload (sha dedupe + auto-segment); nothing is
    preloaded before the user asks, so a fresh visitor sees an empty canvas.
    """
    if not DEMO_PHOTO_PATH.is_file():
        raise HTTPException(status_code=404, detail="demo photo not bundled")
    return await _ingest_photo(DEMO_PHOTO_PATH.read_bytes(), "demo-room.jpg")


async def _ingest_photo(raw: bytes, filename: str) -> dict:
    import hashlib
    from io import BytesIO
    from PIL import Image
    try:
        img = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=415, detail="unreadable image (JPEG/PNG only)")
    width, height = img.size
    buf = BytesIO()
    img.save(buf, "JPEG", quality=92)
    jpeg = buf.getvalue()
    sha = hashlib.sha256(jpeg).hexdigest()
    existing = find_photo_by_sha(sha)
    if existing and (PHOTOS_DIR / f"{existing['id']}.jpg").is_file():
        graph = scene_graph(existing["id"])
        return {"photo_id": existing["id"], "width": existing["width"],
                "height": existing["height"], "reused": True,
                "regions": graph["regions"], "bindings": graph["bindings"]}
    photo_id = add_photo(filename, width, height)
    (PHOTOS_DIR / f"{photo_id}.jpg").write_bytes(jpeg)
    set_photo_sha(photo_id, sha)
    photo = get_photo(photo_id)
    auto = []
    for phrase in SAM_PHRASES:
        try:
            auto.append(await _run_segmentation(photo_id, photo, jpeg, phrase))
        except SamError as e:
            auto.append({"phrase": phrase, "matched_phrase": None,
                         "latency_ms": 0, "regions": [],
                         "note": f"SAM failed: {e}. Use manual fallback."})
    graph = scene_graph(photo_id)
    return {"photo_id": photo_id, "width": width, "height": height, "reused": False,
            "auto_segment": auto, "regions": graph["regions"],
            "bindings": graph["bindings"]}


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


async def _run_segmentation(photo_id: int, photo: dict, raw: bytes,
                            phrase: str) -> dict:
    """Run one phrase (with tail fallback), store regions. Shared by the
    segment endpoint and upload auto-segment."""
    import time
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
            raise SamError(str(e))
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
        return {"phrase": phrase, "matched_phrase": None,
                "latency_ms": total_ms, "regions": []}
    # Refresh semantics: re-segmenting a phrase replaces its regions instead
    # of duplicating them. Bindings to vanished object_ids are dropped.
    removed = delete_phrase_regions(photo_id, matched)
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
    kept = {r["object_id"] for r in regions}
    dropped_bindings = [o for o in removed if o not in kept and delete_binding(photo_id, o)]
    return {"phrase": phrase, "matched_phrase": matched,
            "latency_ms": total_ms, "regions": regions,
            "replaced": len(removed), "dropped_bindings": dropped_bindings}


@app.post("/api/photos/{photo_id}/segment")
async def segment_photo(request: Request, photo_id: int, req: SegmentRequest) -> dict:
    photo, raw = _photo_bytes(photo_id)
    phrase = " ".join(req.phrase.split())
    if not phrase:
        raise HTTPException(status_code=422, detail="empty phrase")
    _limit_model(request)
    try:
        result = await _run_segmentation(photo_id, photo, raw, phrase)
    except SamError as e:
        raise HTTPException(status_code=502, detail=f"SAM failed: {e}. Use manual fallback.")
    if not result["regions"]:
        return {"photo_id": photo_id, **result, "suggested_phrases": SAM_PHRASES,
                "note": "No match for any variant. Draw the region manually."}
    return {"photo_id": photo_id, **result, "suggested_phrases": SAM_PHRASES}


# --- Day 3: manual binding, tap-to-control, baseline reset ---

# Demo-virtual mapping: tapping the door region simulates the sensor by
# flipping its input_boolean. Physical rollout swaps entity IDs; same API.
VIRTUAL_TAP_INPUTS = {
    "binary_sensor.patio_door": "input_boolean.patio_door_open",
}
BASELINE_INPUTS = [
    "input_boolean.lamp_floor_on",
    "input_boolean.string_lights_on",
    "input_boolean.reading_light_on",
    "input_boolean.patio_door_open",
    "input_boolean.tv_on",
    "input_boolean.display_on",
]
BASELINE_LIGHTS = ["light.floor_lamp", "light.string_lights", "light.reading_light"]
BINDABLE_DOMAINS = ("light", "binary_sensor", "input_boolean")
# Only these input_booleans are bindable screens/switches. The lamp/door
# helpers back template entities and must never surface as bind targets.
BINDABLE_INPUTS = ("input_boolean.tv_on", "input_boolean.display_on")


async def _ha_states() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{HA_URL}/api/states", headers=_headers())
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"HA query failed: {resp.status_code}")
    return resp.json()


async def _ha_service(service: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{HA_URL}/api/services/{service}",
                                 headers=_headers(), json=payload)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"HA {service} failed: {resp.status_code}")


def _region_or_404(photo_id: int, object_id: str) -> dict:
    graph = scene_graph(photo_id)
    if not graph:
        raise HTTPException(status_code=404, detail="unknown photo")
    for r in graph["regions"]:
        if r["object_id"] == object_id:
            return r
    raise HTTPException(status_code=404, detail="unknown region")


class BindingRequest(BaseModel):
    object_id: str
    entity_id: str


@app.get("/api/photos/{photo_id}/bindings")
async def photo_bindings(photo_id: int) -> dict:
    if not get_photo(photo_id):
        raise HTTPException(status_code=404, detail="unknown photo")
    return {"photo_id": photo_id, "bindings": list_bindings(photo_id)}


@app.post("/api/photos/{photo_id}/bindings")
async def bind_region(photo_id: int, req: BindingRequest) -> dict:
    _region_or_404(photo_id, req.object_id)
    domain, _, _ = req.entity_id.partition(".")
    if domain not in BINDABLE_DOMAINS:
        raise HTTPException(
            status_code=422,
            detail=f"Only {', '.join(BINDABLE_DOMAINS)}.* entities can be bound (Day 3 baseline)",
        )
    if domain == "input_boolean" and req.entity_id not in BINDABLE_INPUTS:
        raise HTTPException(
            status_code=422,
            detail="Only the TV and smart display switches can be bound, "
                   "not internal helper inputs.",
        )
    known = {s.get("entity_id") for s in await _ha_states()}
    if req.entity_id not in known:
        raise HTTPException(status_code=422, detail="unknown HA entity")
    set_binding(photo_id, req.object_id, req.entity_id)
    return {"ok": True, "object_id": req.object_id, "entity_id": req.entity_id}


@app.delete("/api/photos/{photo_id}/bindings/{object_id}")
async def unbind_region(photo_id: int, object_id: str) -> dict:
    if not delete_binding(photo_id, object_id):
        raise HTTPException(status_code=404, detail="no such binding")
    return {"ok": True, "object_id": object_id}


class TapRequest(BaseModel):
    object_id: str


@app.post("/api/photos/{photo_id}/tap")
async def tap_region(photo_id: int, req: TapRequest) -> dict:
    _region_or_404(photo_id, req.object_id)
    entity_id = get_binding(photo_id, req.object_id)
    if not entity_id:
        raise HTTPException(status_code=409, detail="region is not bound yet")
    domain, _, _ = entity_id.partition(".")
    if domain == "light":
        await _ha_service("light/toggle", {"entity_id": entity_id})
        action = "toggle"
    elif domain == "input_boolean":
        await _ha_service("input_boolean/toggle", {"entity_id": entity_id})
        action = "toggle"
    elif entity_id in VIRTUAL_TAP_INPUTS:
        await _ha_service("input_boolean/toggle",
                          {"entity_id": VIRTUAL_TAP_INPUTS[entity_id]})
        action = "simulate"
    else:
        raise HTTPException(status_code=422, detail="no tap action for this entity")
    return {"ok": True, "object_id": req.object_id, "entity_id": entity_id, "action": action}


MATCH_SYSTEM = (
    "You match photo regions to smart-home entities for binding. "
    "Reply with JSON only, following the schema. Rules: "
    "light-like regions bind only to light.* entities; "
    "door-like regions bind only to binary_sensor.* door entities; "
    "screens bind only to the TV / smart display switch entities "
    "(input_boolean.tv_on, input_boolean.display_on), never to helpers; "
    "decor binds to nothing; "
    "propose ONLY regions marked UNBOUND, and only entities marked free; "
    "use box positions (thirds of the photo) plus the already-bound regions "
    "as landmarks to tell same-label fixtures apart; "
    "when unsure, leave the region unmapped rather than guessing."
)


def _third(v: float) -> str:
    return "left" if v < 0.33 else ("right" if v > 0.66 else "center")


# Fixed description of the demo room (mirrors assets/demo-room/README.md).
# Gives the matcher the same layout facts a human binder would use.
ROOM_NOTES = (
    "Room layout: sofa against the left wall; tall floor lamp in the "
    "back-left corner; TV centered on the back wall; string lights across "
    "the top; window with blind plus patio door on the right wall; a "
    "reading nook (pouf + side table + reading lamp) by the window; "
    "coffee table with smart display in the center."
)
MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "object_id": {"type": "string"},
                    "entity_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["object_id", "entity_id", "reason", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


def _spark_log(photo_id: int, latency_ms: int, n: int, status: str,
                 raw: list | None = None, model: str | None = None,
                 provider: str = "hosted") -> None:
    import json
    import time
    from spark_client import SPARK_MODEL
    with open(DATA_DIR / "spark_calls.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "model": model or SPARK_MODEL,
                            "provider": provider,
                            "photo_id": photo_id, "latency_ms": latency_ms,
                            "n_proposals": n, "status": status,
                            "raw_matches": raw or []}) + "\n")


@app.post("/api/photos/{photo_id}/suggest-bindings")
async def suggest_bindings(request: Request, photo_id: int) -> dict:
    """Model-proposed bindings for unbound regions. Proposals only — the UI
    applies them through the normal binding endpoint after user approval."""
    import time
    from spark_client import SPARK_MODEL, SparkError, complete_json

    graph = scene_graph(photo_id)
    if not graph:
        raise HTTPException(status_code=404, detail="unknown photo")
    bound = graph["bindings"]
    if not any(r["object_id"] not in bound for r in graph["regions"]):
        return {"photo_id": photo_id, "proposals": [],
                "note": "everything already bound"}
    _limit_model(request)
    states = await _ha_states()
    entity_bound = {e: o for o, e in bound.items()}

    def _suggestable(entity_id: str) -> bool:
        domain, _, _ = entity_id.partition(".")
        if domain in ("light", "binary_sensor"):
            return True
        return entity_id in BINDABLE_INPUTS

    entities = [
        {"entity_id": s.get("entity_id"),
         "name": (s.get("attributes") or {}).get("friendly_name", s.get("entity_id")),
         "state": s.get("state")}
        for s in states
        if _suggestable(s.get("entity_id", ""))
    ]

    def _describe_region(r: dict) -> str:
        pos = f"{_third(r['x'] + r['w'] / 2)}-{_third(r['y'] + r['h'] / 2)}"
        status = f"bound to {bound[r['object_id']]}" \
            if r["object_id"] in bound else "UNBOUND"
        return (f"- {r['object_id']}: {r['phrase']} [{r['source']}] "
                f"at {pos} box=({r['x']:.2f},{r['y']:.2f},{r['w']:.2f},{r['h']:.2f}) "
                f"{status}")

    def _describe_entity(e: dict) -> str:
        status = f"bound to {entity_bound[e['entity_id']]}" \
            if e["entity_id"] in entity_bound else "free"
        return f"- {e['entity_id']}: {e['name']} ({e['state']}) {status}"

    user = (ROOM_NOTES + "\nPhoto regions:\n" +
            "\n".join(_describe_region(r) for r in graph["regions"]) +
            "\nHome Assistant entities:\n" +
            "\n".join(_describe_entity(e) for e in entities) +
            "\nPropose entity matches for the UNBOUND regions only.")
    regions = [r for r in graph["regions"] if r["object_id"] not in bound]
    t0 = time.monotonic()
    try:
        out = await complete_json(MATCH_SYSTEM, user, MATCH_SCHEMA)
    except SparkError as e:
        _spark_log(photo_id, int((time.monotonic() - t0) * 1000), 0, f"error: {e}")
        raise HTTPException(status_code=502, detail=f"Spark failed: {e}")
    latency_ms = int((time.monotonic() - t0) * 1000)
    _spark_log(photo_id, latency_ms, 0, "raw",
               [{"object_id": m.get("object_id"), "entity_id": m.get("entity_id")}
                for m in out.get("matches", [])])
    known_regions = {r["object_id"] for r in regions}
    known_entities = {e["entity_id"] for e in entities}
    proposals = []
    used_entities: set[str] = set()
    for m in out.get("matches", []):
        oid, eid = m.get("object_id"), m.get("entity_id")
        if oid not in known_regions or eid not in known_entities:
            continue  # hallucinated ids never ship
        conflict = eid in used_entities
        used_entities.add(eid)
        proposals.append({"object_id": oid, "entity_id": eid,
                          "reason": m.get("reason", ""),
                          "confidence": m.get("confidence", 0),
                          "conflict": conflict})
    _spark_log(photo_id, latency_ms, len(proposals), "ok")
    return {"photo_id": photo_id, "proposals": proposals, "latency_ms": latency_ms}


# --- Day 4: Spark AutomationIR, deterministic compile, approval ---

import re

BANNED_INTENT_RE = re.compile(
    r"\b(lock|unlock|alarm|garage|heater|thermostat|cover|blind|shade|"
    r"curtain|camera|doorbell|disarm|siren|sprinkler|vacuum)\b", re.IGNORECASE)


def _banned_intent(text: str) -> str | None:
    m = BANNED_INTENT_RE.search(text)
    return m.group(1).lower() if m else None


class ProposeRequest(BaseModel):
    photo_id: int
    source_object_id: str
    target_object_id: str
    text: str = ""
    # "hosted" = Meta Model API muse-spark-1.3 (default).
    # "open" = Baseten open-weight path, labelled in the UI and in logs.
    provider: str = "hosted"
    # None = use the model's text-derived delay; an int deterministically
    # overrides it (Automate delay dropdown). Validated before any HA write.
    delay_s: int | None = None


@app.post("/api/automations/propose")
async def propose_automation(request: Request, req: ProposeRequest) -> dict:
    """Gesture + text -> Spark AutomationIR -> validate -> compile.

    Nothing is written to HA here. The returned proposal must be approved
    before any write. Invalid plans return 422 with plain-language reasons.
    """
    import time
    from automation import (IR_SCHEMA, IR_SYSTEM, apply_delay_override,
                            build_ir_prompt, compile_ir, validate_ir)
    from spark_client import (SPARK_MODEL, SparkError, complete_json,
                              open_provider_config)
    import store as store_module

    if req.provider not in ("hosted", "open"):
        raise HTTPException(status_code=422,
                            detail="provider must be 'hosted' or 'open'")
    if req.provider == "open":
        try:
            model_api_base, model_name, model_api_key = open_provider_config()
        except SparkError as e:
            raise HTTPException(status_code=503, detail=str(e))
    else:
        model_api_base, model_name, model_api_key = None, SPARK_MODEL, None

    graph = scene_graph(req.photo_id)
    if not graph:
        raise HTTPException(status_code=404, detail="unknown photo")
    _region_or_404(req.photo_id, req.source_object_id)
    _region_or_404(req.photo_id, req.target_object_id)
    bindings = graph["bindings"]
    if req.source_object_id not in bindings:
        raise HTTPException(status_code=409, detail="source region is not bound yet")
    if req.target_object_id not in bindings:
        raise HTTPException(status_code=409, detail="target region is not bound yet")
    source_entity = bindings[req.source_object_id]
    target_entity = bindings[req.target_object_id]
    registry = {s.get("entity_id") for s in await _ha_states()}

    # Deterministic intent gate: the model launders out-of-scope requests
    # into allowed shapes (observed live: "unlock the front door" became a
    # door->light plan). The validator sees only the IR, so catch banned
    # device language here, before any model call or proposal is stored.
    hit = _banned_intent(req.text or "")
    if hit:
        raise HTTPException(
            status_code=422,
            detail=f"not supported: '{hit}' devices are outside the demo "
                   "allowlist (door sensor + lights only). No plan made, no HA write.")

    _limit_model(request)
    t0 = time.monotonic()
    try:
        ir = await complete_json(
            IR_SYSTEM, build_ir_prompt(source_entity, target_entity, req.text),
            IR_SCHEMA, model=model_name, api_base=model_api_base,
            api_key=model_api_key)
    except SparkError as e:
        raise HTTPException(status_code=502, detail=f"Spark failed: {e}")
    latency_ms = int((time.monotonic() - t0) * 1000)
    _spark_log(req.photo_id, latency_ms, 1, "ir", [ir],
                 model=model_name, provider=req.provider)

    # Explicit delay dropdown beats text parsing: deterministic, and the
    # delay beat no longer depends on the model hearing "after a minute".
    try:
        ir = apply_delay_override(ir, req.delay_s)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    reasons = validate_ir(ir, registry)
    if reasons:
        raise HTTPException(status_code=422, detail="; ".join(reasons))
    proposal_id = store_module.save_proposal(
        req.photo_id, req.source_object_id, req.target_object_id, req.text, ir,
        compile_ir(ir, alias=f"HomeTwin {req.source_object_id} to {req.target_object_id}"))
    proposal = store_module.get_proposal(proposal_id)
    return {"proposal_id": proposal_id, "ir": ir,
            "compiled": proposal["compiled"], "latency_ms": latency_ms,
            "approval_required": True, "provider": req.provider,
            "model": model_name}


@app.post("/api/automations/{proposal_id}/approve")
async def approve_automation(proposal_id: int) -> dict:
    """Approval-gated deploy: re-validate, write to HA via the automation
    config API, read back to confirm. First live use is Day 5; Day 4
    exercises propose/validate plus this path against fakes."""
    from automation import validate_ir
    import store as store_module

    proposal = store_module.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="unknown proposal")
    if proposal["status"] == "deployed":
        return {"ok": True, "proposal_id": proposal_id, "already": True}
    registry = {s.get("entity_id") for s in await _ha_states()}
    reasons = validate_ir(proposal["ir"], registry)
    if reasons:
        store_module.set_proposal_status(proposal_id, "rejected")
        raise HTTPException(status_code=422, detail="; ".join(reasons))
    automation_id = f"hometwin_{proposal_id}"
    payload = {"id": automation_id, **proposal["compiled"]}
    async with httpx.AsyncClient(timeout=15) as client:
        put = await client.post(f"{HA_URL}/api/config/automation/config/{automation_id}",
                                headers=_headers(), json=payload)
        if put.status_code not in (200, 201):
            raise HTTPException(status_code=502,
                                detail=f"HA deploy failed: {put.status_code}")
        # Writing via the config API only stores the automation; the engine
        # picks it up on reload. Without this the deployed rule never fires.
        await _ha_service("automation/reload", {})
        read = await client.get(
            f"{HA_URL}/api/config/automation/config/{automation_id}",
            headers=_headers())
    if read.status_code != 200:
        raise HTTPException(status_code=502, detail="HA read-back failed")
    store_module.set_proposal_status(proposal_id, "deployed")
    return {"ok": True, "proposal_id": proposal_id,
            "automation_id": automation_id, "read_back": read.json()}


# --- Day 5: What-If preview (simulated inputs, clearly labelled) ---

class WhatIfRequest(BaseModel):
    proposal_id: int
    door: str = "on"   # simulated door event: "on" (opened) or "off"
    sun: str = "day"   # simulated sun: "day" or "night"


@app.get("/api/automations/proposals")
async def proposals_list(photo_id: int | None = None) -> dict:
    """Proposals for one photo only. Unfiltered listing would leak another
    photo's history into a fresh session, which looks prepopulated."""
    import store as store_module
    return {"proposals": store_module.list_proposals(photo_id=photo_id)}


@app.post("/api/whatif")
async def what_if(req: WhatIfRequest) -> dict:
    """Simulated preview reusing the compiled automation. NOT an HA emulator:
    answers 'would this automation fire if the door opened under this sun?'
    using the same compiled trigger/condition the deploy path uses."""
    from automation import validate_ir
    import store as store_module

    if req.door not in ("on", "off"):
        raise HTTPException(status_code=422, detail="door must be 'on' or 'off'")
    if req.sun not in ("day", "night"):
        raise HTTPException(status_code=422, detail="sun must be 'day' or 'night'")
    proposal = store_module.get_proposal(req.proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="unknown proposal")
    registry = {s.get("entity_id") for s in await _ha_states()}
    reasons = validate_ir(proposal["ir"], registry)
    if reasons:
        raise HTTPException(status_code=422, detail="; ".join(reasons))
    compiled = proposal["compiled"]
    trigger_match = req.door == "on"
    cond = next((c for c in compiled.get("condition", [])
                 if c.get("condition") == "sun"), None)
    if cond is None:
        condition_pass, condition_note = True, "no condition"
    elif "after" in cond or "before" in cond:
        condition_pass = req.sun == "night"
        condition_note = f"sun {cond.get('after') or cond.get('before')} vs simulated {req.sun}"
    else:
        condition_pass, condition_note = False, "unknown condition form"
    fires = trigger_match and condition_pass
    return {"simulated": True, "proposal_id": req.proposal_id,
            "inputs": {"door": req.door, "sun": req.sun},
            "trigger_match": trigger_match, "condition_pass": condition_pass,
            "condition_note": condition_note, "fires": fires,
            "delay_s": proposal["ir"].get("delay_s", 0),
            "action": compiled["action"] if fires else []}


# --- Rearrange (lamp-move proposals) + Scene Composer ---

# In-memory move proposals: propose -> preview -> approve. Only the approve
# step touches the scene graph (region position); bindings stay put, so tap
# keeps working on the same light afterwards. Decline = nothing. Reset
# restores original positions (see reset_baseline).
_move_proposals: dict[int, dict] = {}
_move_next_id = 1

MOVE_SYSTEM = (
    "You place a lamp in a room photo. Emit ONE JSON object matching the schema: "
    "x and y are the new top-left corner of the lamp's region as fractions "
    "of photo width/height (0..1, origin top-left), staying inside the room "
    "and away from doors and walkways; reason is one short sentence a "
    "homeowner would understand. Never emit anything but the JSON object."
)
MOVE_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "number"}, "y": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["x", "y", "reason"],
}


class MoveProposeRequest(BaseModel):
    photo_id: int
    object_id: str
    instruction: str = ""


class MovePreviewRequest(BaseModel):
    photo_id: int
    move_id: int


class MoveApproveRequest(BaseModel):
    photo_id: int
    move_id: int


def _move_region(photo_id: int, object_id: str) -> tuple[dict, dict]:
    graph = scene_graph(photo_id)
    if not graph:
        raise HTTPException(status_code=404, detail="unknown photo")
    region = next((r for r in graph["regions"]
                   if r["object_id"] == object_id), None)
    if not region:
        raise HTTPException(status_code=404, detail="unknown region")
    return graph, region


@app.post("/api/photos/{photo_id}/move-propose")
async def move_propose(photo_id: int, req: MoveProposeRequest) -> dict:
    """Spark proposes a new pin position for a BOUND lamp. No scene change,
    no image yet, no HA write — preview and approve are separate steps."""
    import time
    from spark_client import SparkError, complete_json

    global _move_next_id
    graph, region = _move_region(req.photo_id, req.object_id)
    entity = graph["bindings"].get(req.object_id)
    if not entity or not entity.startswith("light."):
        raise HTTPException(
            status_code=409,
            detail="only a bound lamp can be moved (tap keeps working on the same light)")
    t0 = time.monotonic()
    try:
        out = await complete_json(
            MOVE_SYSTEM,
            f"Room: {graph['photo']['width']}x{graph['photo']['height']}. "
            f"Lamp region '{req.object_id}' ({region['phrase']}) now at "
            f"x={region['x']:.3f} y={region['y']:.3f} w={region['w']:.3f} "
            f"h={region['h']:.3f}. Request: {req.instruction or 'a better spot'}.",
            MOVE_SCHEMA)
    except SparkError as e:
        raise HTTPException(status_code=502, detail=f"Spark move failed: {e}")
    latency_ms = int((time.monotonic() - t0) * 1000)
    try:
        x = min(1.0, max(0.0, float(out["x"])))
        y = min(1.0, max(0.0, float(out["y"])))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Spark move was not coordinates")
    move_id = _move_next_id
    _move_next_id += 1
    _move_proposals[move_id] = {
        "move_id": move_id, "photo_id": req.photo_id,
        "object_id": req.object_id, "x": x, "y": y,
        "reason": str(out.get("reason", "")),
    }
    _spark_log(req.photo_id, latency_ms, 1, "move-propose")
    return {"move_id": move_id, "object_id": req.object_id,
            "from_xy": [region["x"], region["y"]], "to_xy": [x, y],
            "reason": str(out.get("reason", "")), "latency_ms": latency_ms}


@app.post("/api/photos/{photo_id}/move-preview")
async def move_preview(request: Request, photo_id: int,
                       req: MovePreviewRequest) -> dict:
    """Illustrative Muse Image edit showing the lamp at the proposed spot.
    Labelled illustrative in-UI; moves no pin and writes nothing to HA."""
    import time
    from image_client import IMAGE_MODEL, ImageError, edit_image

    _limit_model(request)
    proposal = _move_proposals.get(req.move_id)
    if not proposal or proposal["photo_id"] != req.photo_id:
        raise HTTPException(status_code=404, detail="unknown move proposal")
    _photo, raw = _photo_bytes(req.photo_id)
    _graph, region = _move_region(req.photo_id, proposal["object_id"])
    t0 = time.monotonic()
    try:
        image_bytes = await edit_image(
            raw, f"Move the {region['phrase']} to the "
            f"{'left' if proposal['x'] < region['x'] else 'right'} side of the room, "
            f"{'upper' if proposal['y'] < region['y'] else 'lower'} area, keeping "
            "everything else in this room photo exactly the same")
    except ImageError as e:
        raise HTTPException(status_code=502, detail=f"image preview failed: {e}")
    latency_ms = int((time.monotonic() - t0) * 1000)
    name = _save_preview(image_bytes)
    _log_image_call("move-preview", latency_ms, IMAGE_MODEL)
    return {"move_id": req.move_id, "preview_url": f"/api/advisor/previews/{name}",
            "illustrative": True, "to_xy": [proposal["x"], proposal["y"]]}


@app.post("/api/photos/{photo_id}/move-approve")
async def move_approve(photo_id: int, req: MoveApproveRequest) -> dict:
    """Accept the proposal: the PIN moves, the binding does not. Tap keeps
    working on the same light; HA stays untouched."""
    import store as store_module

    proposal = _move_proposals.get(req.move_id)
    if not proposal or proposal["photo_id"] != req.photo_id:
        raise HTTPException(status_code=404, detail="unknown move proposal")
    _graph, region = _move_region(req.photo_id, proposal["object_id"])
    store_module.record_move_origin(req.photo_id, proposal["object_id"],
                                    region["x"], region["y"])
    if not store_module.set_region_position(req.photo_id, proposal["object_id"],
                                             proposal["x"], proposal["y"]):
        raise HTTPException(status_code=404, detail="region vanished")
    del _move_proposals[req.move_id]
    return {"ok": True, "object_id": proposal["object_id"],
            "from_xy": [region["x"], region["y"]],
            "to_xy": [proposal["x"], proposal["y"]]}


class SceneSaveRequest(BaseModel):
    name: str


@app.post("/api/scenes")
async def scene_save(req: SceneSaveRequest) -> dict:
    """Save current light states as a named scene. Pure capture, no HA write."""
    import store as store_module

    name = " ".join(req.name.split())
    if not name or len(name) > 40:
        raise HTTPException(status_code=422, detail="scene name 1-40 chars")
    states = {s.get("entity_id"): s.get("state")
              for s in await _ha_states()
              if s.get("entity_id", "").startswith("light.")}
    if not states:
        raise HTTPException(status_code=502, detail="no lights found in HA")
    store_module.save_scene(name, states)
    return {"ok": True, "name": name, "states": states}


@app.get("/api/scenes")
async def scene_list() -> dict:
    import store as store_module

    return {"scenes": store_module.list_scenes()}


@app.post("/api/scenes/{name}/apply")
async def scene_apply(name: str) -> dict:
    """Apply a saved scene: lights to their captured states. The Apply click
    IS the approval — one explicit user action, allowlisted light on/off only."""
    import store as store_module

    scene = next((s for s in store_module.list_scenes() if s["name"] == name), None)
    if not scene:
        raise HTTPException(status_code=404, detail="unknown scene")
    applied = []
    for entity_id, state in scene["states"].items():
        if not entity_id.startswith("light.") or state not in ("on", "off"):
            continue
        await _ha_service(f"light/turn_{state}", {"entity_id": entity_id})
        applied.append({"entity_id": entity_id, "state": state})
    return {"ok": True, "name": name, "applied": applied}


@app.delete("/api/scenes/{name}")
async def scene_delete(name: str) -> dict:
    import store as store_module

    if not store_module.delete_scene(name):
        raise HTTPException(status_code=404, detail="unknown scene")
    return {"ok": True, "name": name}


# --- Design Advisor + time-of-day previews (illustrative only) ---

def _preview_media_type(image_bytes: bytes) -> tuple[str, str]:
    if image_bytes.startswith(b"\x89PNG"):
        return "image/png", "png"
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg", "jpg"
    if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        return "image/webp", "webp"
    return "image/png", "png"


def _save_preview(image_bytes: bytes) -> str:
    import uuid

    previews_dir = DATA_DIR / "advisor_previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    (previews_dir / name).write_bytes(image_bytes)
    return name


def _log_image_call(kind: str, latency_ms: int, model: str) -> None:
    import json
    import time

    with open(DATA_DIR / "image_calls.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "model": model, "kind": kind,
                            "latency_ms": latency_ms}) + "\n")


class AdvisorSuggestRequest(BaseModel):
    photo_id: int
    request_text: str = "cozy evening"


class AdvisorSettingAction(BaseModel):
    entity_id: str
    service: str


class AdvisorSetting(BaseModel):
    name: str
    description: str = ""
    actions: list[AdvisorSettingAction]


class AdvisorPreviewRequest(BaseModel):
    photo_id: int
    setting: AdvisorSetting
    request_text: str = "cozy evening"


class AdvisorApplyRequest(BaseModel):
    setting: AdvisorSetting


class TimeOfDayRequest(BaseModel):
    photo_id: int
    variant: str


@app.post("/api/advisor/suggest")
async def advisor_suggest(request: Request, req: AdvisorSuggestRequest) -> dict:
    """Spark proposes exactly 2 feasible lighting settings. No HA write,
    no image yet — preview and apply are separate, approval-gated steps."""
    import time
    from advisor import (ADVISOR_SCHEMA, ADVISOR_SYSTEM,
                         build_advisor_prompt, validate_advisor_response)
    from spark_client import SPARK_MODEL, SparkError, complete_json

    if not get_photo(req.photo_id):
        raise HTTPException(status_code=404, detail="unknown photo")
    registry = {s.get("entity_id") for s in await _ha_states()}
    lights = sorted(e for e in registry if e.startswith("light."))
    if not lights:
        raise HTTPException(status_code=502, detail="no lights found in HA")
    _limit_model(request)
    t0 = time.monotonic()
    try:
        out = await complete_json(
            ADVISOR_SYSTEM, build_advisor_prompt(lights, req.request_text),
            ADVISOR_SCHEMA)
    except SparkError as e:
        raise HTTPException(status_code=502, detail=f"Spark failed: {e}")
    latency_ms = int((time.monotonic() - t0) * 1000)
    settings = out.get("settings")
    reasons = validate_advisor_response(settings, registry)
    if reasons:
        raise HTTPException(status_code=422, detail="; ".join(reasons))
    _spark_log(req.photo_id, latency_ms, 0, "advisor", settings,
                 model=SPARK_MODEL, provider="hosted")
    return {"settings": settings, "latency_ms": latency_ms,
            "model": SPARK_MODEL, "approval_required": True}


@app.post("/api/advisor/preview")
async def advisor_preview(request: Request, req: AdvisorPreviewRequest) -> dict:
    """Illustrative Muse Image preview for one chosen setting. No HA write."""
    import time
    from advisor import advisor_preview_prompt, validate_settings
    from image_client import IMAGE_MODEL, ImageError, generate_image

    if not get_photo(req.photo_id):
        raise HTTPException(status_code=404, detail="unknown photo")
    registry = {s.get("entity_id") for s in await _ha_states()}
    setting = req.setting.model_dump()
    reasons = validate_settings([setting], registry)
    if reasons:
        raise HTTPException(status_code=422, detail="; ".join(reasons))
    _limit_model(request)
    t0 = time.monotonic()
    try:
        image_bytes = await generate_image(advisor_preview_prompt(setting))
    except ImageError as e:
        raise HTTPException(status_code=502, detail=str(e))
    latency_ms = int((time.monotonic() - t0) * 1000)
    name = _save_preview(image_bytes)
    media_type, _ext = _preview_media_type(image_bytes)
    _log_image_call("advisor", latency_ms, IMAGE_MODEL)
    return {"preview_url": f"/api/advisor/previews/{name}",
            "media_type": media_type, "setting": setting,
            "latency_ms": latency_ms, "model": IMAGE_MODEL,
            "illustrative": True}


@app.post("/api/advisor/apply")
async def advisor_apply(req: AdvisorApplyRequest) -> dict:
    """Apply one validated setting: supported light on/off only, via HA."""
    from advisor import validate_settings

    registry = {s.get("entity_id") for s in await _ha_states()}
    setting = req.setting.model_dump()
    reasons = validate_settings([setting], registry)
    if reasons:
        raise HTTPException(status_code=422, detail="; ".join(reasons))
    applied = []
    for action in setting["actions"]:
        # _ha_service takes "light/turn_on" style names.
        ha_service = action["service"].replace(".", "/", 1)
        await _ha_service(ha_service, {"entity_id": action["entity_id"]})
        applied.append(action)
    return {"ok": True, "setting": setting["name"], "applied": applied}


@app.post("/api/advisor/time-of-day")
async def time_of_day_preview(request: Request, req: TimeOfDayRequest) -> dict:
    """Illustrative variant of the frozen room, edited from its photo.
    Returns the preset matching settings too; applying them is a
    separate approval-gated call to /api/advisor/apply."""
    import time
    from advisor import TIME_OF_DAY_PRESETS
    from image_client import IMAGE_MODEL, ImageError, edit_image

    if req.variant not in TIME_OF_DAY_PRESETS:
        raise HTTPException(status_code=422,
                            detail="variant must be morning, sunset, or night")
    from advisor import TIME_OF_DAY_PRESETS, validate_settings

    _photo, raw = _photo_bytes(req.photo_id)
    preset = TIME_OF_DAY_PRESETS[req.variant]
    registry = {s.get("entity_id") for s in await _ha_states()}
    reasons = validate_settings([{"name": preset["label"], "description": "",
                                  "actions": preset["actions"]}], registry)
    if reasons:
        raise HTTPException(status_code=422, detail="; ".join(reasons))
    _limit_model(request)
    t0 = time.monotonic()
    try:
        image_bytes = await edit_image(raw, preset["image_prompt"])
    except ImageError as e:
        raise HTTPException(status_code=502, detail=str(e))
    latency_ms = int((time.monotonic() - t0) * 1000)
    name = _save_preview(image_bytes)
    media_type, _ext = _preview_media_type(image_bytes)
    _log_image_call(f"time-of-day:{req.variant}", latency_ms, IMAGE_MODEL)
    return {"variant": req.variant, "label": preset["label"],
            "description": preset["description"],
            "preview_url": f"/api/advisor/previews/{name}",
            "media_type": media_type,
            "setting": {"name": preset["label"],
                        "description": preset["description"],
                        "actions": preset["actions"]},
            "latency_ms": latency_ms, "model": IMAGE_MODEL,
            "illustrative": True}


@app.get("/api/advisor/previews/{name}")
async def advisor_preview_image(name: str) -> FileResponse:
    import re

    if not re.fullmatch(r"[0-9a-f]{32}", name or ""):
        raise HTTPException(status_code=404, detail="unknown preview")
    path = DATA_DIR / "advisor_previews" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="unknown preview")
    media_type, _ext = _preview_media_type(path.read_bytes())
    return FileResponse(str(path), media_type=media_type)


# --- Voice: push-to-talk transcription into the typed pipeline ---

@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request, file: UploadFile) -> dict:
    """Transcribe one push-to-talk recording. Audio is held in memory
    only and never written to disk; only the transcript is logged.
    A supported transcript is returned with its match; anything else
    is returned with supported=False and must not be executed."""
    import time
    from voice import TRANSCRIBE_MODEL, TranscribeError, match_utterance, transcribe_audio

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="empty recording")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="recording too large (10 MB max)")
    _limit_model(request)
    t0 = time.monotonic()
    try:
        transcript = await transcribe_audio(raw, file.content_type or "audio/webm")
    except TranscribeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    latency_ms = int((time.monotonic() - t0) * 1000)
    matched = match_utterance(transcript)
    import json

    with open(DATA_DIR / "voice_calls.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "model": TRANSCRIBE_MODEL,
                            "latency_ms": latency_ms, "transcript": transcript,
                            "supported": matched is not None,
                            "kind": matched["kind"] if matched else None}) + "\n")
    if not matched:
        return {"transcript": transcript, "supported": False,
                "matched": None, "note": "not supported yet",
                "latency_ms": latency_ms, "model": TRANSCRIBE_MODEL}
    return {"transcript": transcript, "supported": True,
            "matched": {"key": matched["key"], "kind": matched["kind"],
                        "entity_id": matched["entity_id"],
                        "service": matched["service"],
                        "automate_text": matched["automate_text"],
                        "source_entity": matched["source_entity"],
                        "target_entity": matched["target_entity"]},
            "latency_ms": latency_ms, "model": TRANSCRIBE_MODEL}


class VoiceControlRequest(BaseModel):
    entity_id: str
    service: str


@app.post("/api/voice/control")
async def voice_control(req: VoiceControlRequest) -> dict:
    """Direct light control for a tap-control utterance, clicked
    explicitly by the user after seeing the transcript. Validated to
    light.* turn_on / turn_off only; this is a tap, not an automation."""
    registry = {s.get("entity_id") for s in await _ha_states()}
    if req.entity_id not in registry:
        raise HTTPException(status_code=422,
                            detail=f"Unknown entity '{req.entity_id}' (not in this home).")
    if not req.entity_id.startswith("light."):
        raise HTTPException(status_code=422,
                            detail=f"Entity '{req.entity_id}' is not a light.")
    if req.service not in ("light.turn_on", "light.turn_off"):
        raise HTTPException(status_code=422,
                            detail=f"Service '{req.service}' is not allowed.")
    ha_service = req.service.replace(".", "/", 1)
    await _ha_service(ha_service, {"entity_id": req.entity_id})
    return {"ok": True, "entity_id": req.entity_id, "service": req.service}


@app.post("/api/reset")
async def reset_baseline() -> dict:
    """One-click return to the frozen baseline: every demo input off, every
    light off, and every deployed hometwin_* automation deleted, so the next
    trial run starts from a clean slate (per-approval deploys never linger)."""
    import store as store_module

    for entity_id in BASELINE_INPUTS:
        await _ha_service("input_boolean/turn_off", {"entity_id": entity_id})
    for entity_id in BASELINE_LIGHTS:
        await _ha_service("light/turn_off", {"entity_id": entity_id})
    cleared = []
    async with httpx.AsyncClient(timeout=15) as client:
        for p in store_module.list_proposals():
            if p["status"] != "deployed":
                continue
            automation_id = f"hometwin_{p['id']}"
            # HA answers 400 (not 404) when deleting a missing id, so check
            # existence first: missing means an earlier reset already cleared
            # it — just fix the stale record.
            get = await client.get(
                f"{HA_URL}/api/config/automation/config/{automation_id}",
                headers=_headers())
            if get.status_code == 404:
                store_module.set_proposal_status(p["id"], "reset")
                continue
            if get.status_code != 200:
                continue
            resp = await client.delete(
                f"{HA_URL}/api/config/automation/config/{automation_id}",
                headers=_headers())
            if resp.status_code == 200:
                store_module.set_proposal_status(p["id"], "reset")
                cleared.append(automation_id)
    await _ha_service("automation/reload", {})
    # Full demo reset: history goes too, including unapproved drafts,
    # so What-If is empty after Reset (updated demo steps).
    history_cleared = store_module.delete_proposals(("pending", "deployed", "reset"))
    # Fresh-demo reset: bindings go too, so the suggest flow is showable on
    # every run. Regions (the segmentation result) are kept.
    bindings_cleared = store_module.clear_bindings()
    # Rearrangement is a proposal too: moved pins return home, scenes go.
    moves_restored = 0
    for origin in store_module.pop_move_origins():
        if store_module.set_region_position(origin["photo_id"],
                                            origin["object_id"],
                                            origin["x"], origin["y"]):
            moves_restored += 1
    scenes_cleared = store_module.clear_scenes()
    _move_proposals.clear()
    return {"ok": True, "inputs_off": BASELINE_INPUTS, "lights_off": BASELINE_LIGHTS,
            "automations_cleared": cleared, "history_cleared": history_cleared,
            "bindings_cleared": bindings_cleared,
            "moves_restored": moves_restored, "scenes_cleared": scenes_cleared}


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
