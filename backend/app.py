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
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
