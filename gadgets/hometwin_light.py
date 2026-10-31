#!/usr/bin/env python3
"""HomeTwin gadget command: hometwin.light.set (step 2, allowlisted).

This is the program a Muse Gadgets Linux device runs when Muse
invokes the custom command `hometwin.light.set`. It is the ONE
write command in this spike, and it is gated twice: here, and again
by the HomeTwin backend policy layer (POST /api/voice/control,
which itself only allows light.* turn_on / turn_off).

Parameters (one JSON object on stdin, as the SDK sends them):
    {"entity_id": "light.string_lights", "on": true}

Policy (a rejection exits non-zero, with the reason on stderr —
the SDK reports the last stderr line to Muse, and nothing reaches
HA):
    - entity_id must start with "light." — locks, covers, doors,
      switches and helpers are rejected, never executed.
    - on must be a JSON boolean — a string "true" is rejected.
    - No other parameters are acted on.

On success it prints one JSON object with the read-back state
(queried after the control call, not assumed).

No credential is held here: it talks to the HomeTwin backend,
which holds the HA token server-side.

Environment:
    HOMETWIN_BASE_URL — default http://localhost:8000
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE_URL = os.environ.get("HOMETWIN_BASE_URL", "http://localhost:8000").rstrip("/")


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _get_state(entity_id: str) -> str | None:
    with urllib.request.urlopen(f"{BASE_URL}/api/entities", timeout=10) as resp:
        states = json.load(resp)
    for s in states:
        if s.get("entity_id") == entity_id:
            return s.get("state")
    return None


def main() -> int:
    try:
        params = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"error": "invalid JSON parameters"}), file=sys.stderr)
        return 2
    if not isinstance(params, dict):
        print(json.dumps({"error": "parameters must be a JSON object"}), file=sys.stderr)
        return 2
    entity_id = params.get("entity_id")
    on = params.get("on")
    if not isinstance(entity_id, str) or not entity_id.startswith("light."):
        print(json.dumps({"error": f"entity '{entity_id}' is not a light — rejected, no HA write"}),
              file=sys.stderr)
        return 2
    if not isinstance(on, bool):
        print(json.dumps({"error": "'on' must be a boolean"}), file=sys.stderr)
        return 2
    service = "light.turn_on" if on else "light.turn_off"
    try:
        _post("/api/voice/control", {"entity_id": entity_id, "service": service})
        state = _get_state(entity_id)
    except Exception as e:
        print(json.dumps({"error": f"HomeTwin backend failed: {e}"}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "entity_id": entity_id, "service": service,
                      "state": state, "source": "hometwin-backend"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
