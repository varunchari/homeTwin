#!/usr/bin/env python3
"""HomeTwin gadget command: hometwin.status (read-only, step 1).

This is the program a Muse Gadgets Linux device runs when Muse
invokes the custom command `hometwin.status`. It takes no parameters,
reads HomeTwin state, and prints one JSON object to stdout.

It talks to the HomeTwin backend (which holds the HA token
server-side), never to Home Assistant directly, and never holds a
credential itself: the backend URL is public demo / local backend
only, and no token, key or password appears here, in the command
definition, or in the browser.

Output is deliberately narrow: only light.* states, the patio door
sensor, and sun.sun. No automations, no input_boolean helpers, no
other entities leak through this command.

Usage (as the SDK runs it, no shell, params on stdin):
    python3 hometwin_status.py < /dev/null

Environment:
    HOMETWIN_BASE_URL — HomeTwin backend base URL.
        Default: http://localhost:8000
        On the Lightsail demo: http://3.135.147.231
        On a Pi running the demo locally: http://localhost:8000
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE_URL = os.environ.get("HOMETWIN_BASE_URL", "http://localhost:8000").rstrip("/")


def main() -> int:
    # Read and discard stdin (the SDK always sends a JSON object,
    # empty for a no-parameter command). Do not fail on it.
    try:
        sys.stdin.read()
    except Exception:
        pass
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/entities", timeout=10) as resp:
            states = json.load(resp)
    except Exception as e:
        print(json.dumps({"error": f"HomeTwin backend unreachable: {e}"}), file=sys.stderr)
        return 1
    lights = []
    door = None
    sun = None
    for s in states:
        entity_id = s.get("entity_id", "")
        if entity_id.startswith("light."):
            lights.append({"entity_id": entity_id, "state": s.get("state")})
        elif entity_id == "binary_sensor.patio_door":
            door = s.get("state")
        elif entity_id == "sun.sun":
            sun = s.get("state")
    lights.sort(key=lambda x: x["entity_id"])
    print(json.dumps({"lights": lights, "patio_door": door, "sun": sun,
                      "source": "hometwin-backend"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
