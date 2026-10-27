#!/usr/bin/env python3
"""Day 1 exit test (v1.6): HA virtual devices + WS state via backend proxy.

Run with the project venv (needs `websockets`):
    hometwin/.venv/bin/python scripts/day1_exit_test.py [--backend URL] [--public URL]

All checks must pass:
  1. query returns all entities (3 lights + door sensor)
  2. API toggle flips a light (and flips back)
  3. WS state_changed reaches the backend within ~2s
  4. re-query reproduces the same baseline set (restart step is manual:
     `docker compose restart ha backend`, then re-run this script)
  5. (with --public) public URL loads the skeleton and no HA admin UI
     is reachable through it
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request

EXPECTED = {"light.floor_lamp", "light.string_lights", "light.reading_light", "binary_sensor.patio_door"}
WS_TIMEOUT = 5.0
WS_BUDGET = 2.0


def http(method: str, url: str, payload: dict | None = None) -> tuple[int, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        raise SystemExit(f"Day 1 exit test failed at: {name}")


def states_map(backend: str) -> dict[str, str]:
    code, body = http("GET", f"{backend}/api/entities")
    check("query returns entities", code == 200, f"(http {code})")
    assert isinstance(body, list)
    return {e["entity_id"]: e["state"] for e in body}


async def ws_state_change(backend: str, entity_id: str) -> float:
    import websockets

    ws_url = backend.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
    t0 = time.monotonic()
    async with websockets.connect(ws_url, max_size=2**20) as ws:
        await ws.send("ping")  # keepalive
        code, _ = http("POST", f"{backend}/api/toggle", {"entity_id": entity_id})
        check("toggle via WS window", code == 200, f"(http {code})")
        deadline = time.monotonic() + WS_TIMEOUT
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.monotonic())
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg.get("data", {}).get("entity_id") == entity_id:
                return time.monotonic() - t0
    raise SystemExit(f"Day 1 exit test failed: no state_changed for {entity_id} within {WS_TIMEOUT}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:8000")
    ap.add_argument("--public", default=None)
    args = ap.parse_args()

    before = states_map(args.backend)
    missing = EXPECTED - set(before)
    check("all expected entities present", not missing, f"missing={sorted(missing)}")

    target = "light.floor_lamp"
    s0 = before[target]
    code, _ = http("POST", f"{args.backend}/api/toggle", {"entity_id": target})
    check("API toggle flips a light", code == 200, f"(http {code})")
    after = states_map(args.backend)
    check("toggle changed state", after[target] != s0, f"({s0} -> {after[target]})")
    http("POST", f"{args.backend}/api/toggle", {"entity_id": target})  # flip back

    dt = asyncio.run(ws_state_change(args.backend, target))
    check("WS state_changed within ~2s", dt <= WS_BUDGET, f"({dt:.2f}s)")

    again = states_map(args.backend)
    check("restart reproduces baseline set", set(again) == set(before),
          "(manual: `docker compose restart ha backend`, then re-run)")

    if args.public:
        req = urllib.request.Request(f"{args.public}/")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                code, body = resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            code, body = e.code, ""
        check("public URL loads skeleton", code == 200 and "HomeTwin" in body,
              f"(http {code})")
        try:
            code, _ = http("GET", f"{args.public}:8123/")
            ha_exposed = code == 200
        except Exception:
            ha_exposed = False
        check("no HA admin UI reachable", not ha_exposed)

    print("Day 1 exit test: ALL PASS")


if __name__ == "__main__":
    main()
