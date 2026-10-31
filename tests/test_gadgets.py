"""Gadgets spike tests: command definitions, scripts, backend policy.

Scripts are run as subprocesses against a tiny fake HomeTwin backend
in-process (no Pi, no Muse pairing, no token). Backend endpoint tests
use the same fake-HA pattern as the voice tests.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.join(os.path.dirname(__file__), "..")
GADGETS = os.path.join(ROOT, "gadgets")
sys.path.insert(0, os.path.join(ROOT, "backend"))

FAKE_STATES = [
    {"entity_id": "light.floor_lamp", "state": "off", "attributes": {}},
    {"entity_id": "light.string_lights", "state": "off", "attributes": {}},
    {"entity_id": "light.reading_light", "state": "on", "attributes": {}},
    {"entity_id": "binary_sensor.patio_door", "state": "off", "attributes": {}},
    {"entity_id": "sun.sun", "state": "below_horizon", "attributes": {}},
    {"entity_id": "automation.hometwin_1", "state": "on", "attributes": {}},
    {"entity_id": "input_boolean.tv_on", "state": "off", "attributes": {}},
]
CONTROL_CALLS = []


class FakeBackendHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/entities":
            self._json(FAKE_STATES)
        else:
            self._json({"detail": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/voice/control":
            CONTROL_CALLS.append(body)
            self._json({"ok": True, **body})
        else:
            self._json({"detail": "not found"}, 404)

    def _json(self, payload, code=200):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_fake_backend():
    server = HTTPServer(("127.0.0.1", 0), FakeBackendHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def run_script(script, params=None, base_url=None):
    env = dict(os.environ, HOMETWIN_BASE_URL=base_url or "")
    proc = subprocess.run(
        [sys.executable, os.path.join(GADGETS, script)],
        input=json.dumps(params) if params is not None else "",
        capture_output=True, text=True, timeout=20, env=env)
    return proc


class CommandDefinitionTest(unittest.TestCase):
    def test_definitions_are_valid_sdk_json(self):
        for filename, name, required in [
                ("hometwin.status.json", "hometwin.status", {}),
                ("hometwin.light.set.json", "hometwin.light.set",
                 {"entity_id", "on"})]:
            with open(os.path.join(GADGETS, "commands.d", filename)) as f:
                data = json.load(f)
            self.assertEqual(filename[:-5], name)
            self.assertTrue(data["description"])
            self.assertIsInstance(data["exec"], list)
            self.assertTrue(data["exec"])
            self.assertEqual(set(data["required"]), set(required))
            self.assertTrue(0 < data["timeout_ms"] <= 600000)
            self.assertFalse(name.startswith(("system.", "file.", "device.", "link.")))
            for spec in data["required"].values():
                self.assertIn(spec["type"],
                              ("string", "integer", "number", "boolean", "object", "array"))


class ScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base_url = start_fake_backend()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        CONTROL_CALLS.clear()

    def test_status_returns_filtered_real_state(self):
        proc = run_script("hometwin_status.py", params={}, base_url=self.base_url)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual([l["entity_id"] for l in out["lights"]],
                         ["light.floor_lamp", "light.reading_light", "light.string_lights"])
        self.assertEqual(out["patio_door"], "off")
        self.assertEqual(out["sun"], "below_horizon")
        # No automation or helper entities leak through.
        self.assertNotIn("automation", proc.stdout)
        self.assertNotIn("input_boolean", proc.stdout)

    def test_light_set_turns_on_and_reads_back(self):
        proc = run_script("hometwin_light.py",
                          params={"entity_id": "light.string_lights", "on": True},
                          base_url=self.base_url)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["service"], "light.turn_on")
        self.assertEqual(CONTROL_CALLS,
                         [{"entity_id": "light.string_lights", "service": "light.turn_on"}])

    def test_light_set_rejects_non_light_before_any_write(self):
        for params in ({"entity_id": "binary_sensor.patio_door", "on": True},
                       {"entity_id": "lock.front_door", "on": True},
                       {"entity_id": "light.string_lights", "on": "true"},
                       {"entity_id": "light.string_lights"},
                       "not-a-dict"):
            proc = run_script("hometwin_light.py", params=params, base_url=self.base_url)
            self.assertNotEqual(proc.returncode, 0, params)
        self.assertEqual(CONTROL_CALLS, [])


HA_STATES = [
    {"entity_id": "light.floor_lamp", "state": "off", "attributes": {}},
    {"entity_id": "light.string_lights", "state": "off", "attributes": {}},
    {"entity_id": "light.reading_light", "state": "off", "attributes": {}},
    {"entity_id": "binary_sensor.patio_door", "state": "off", "attributes": {}},
    {"entity_id": "sun.sun", "state": "below_horizon", "attributes": {}},
]


class FakeResp:
    def __init__(self, code, payload):
        self.status_code = code
        self._payload = payload

    def json(self):
        return self._payload


SERVICE_CALLS = []


class FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        if url.endswith("/api/states"):
            return FakeResp(200, HA_STATES)
        return FakeResp(404, {})

    async def post(self, url, headers=None, json=None):
        SERVICE_CALLS.append(url)
        return FakeResp(200, [])


class GadgetEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        import app as proxy

        cls.proxy = proxy
        cls.client = TestClient(proxy.app)

    def setUp(self):
        self._saved_client = self.proxy.httpx.AsyncClient
        self._saved_token = self.proxy.HA_TOKEN
        self.proxy.httpx.AsyncClient = FakeAsyncClient
        self.proxy.HA_TOKEN = "test-token"
        SERVICE_CALLS.clear()

    def tearDown(self):
        self.proxy.httpx.AsyncClient = self._saved_client
        self.proxy.HA_TOKEN = self._saved_token

    def test_status_endpoint_filters_and_labels_simulated(self):
        body = self.client.get("/api/gadgets/status").json()
        self.assertTrue(body["simulated"])
        self.assertEqual(body["command"], "hometwin.status")
        self.assertEqual([l["entity_id"] for l in body["lights"]],
                         ["light.floor_lamp", "light.reading_light", "light.string_lights"])
        self.assertEqual(body["sun"], "below_horizon")

    def test_light_endpoint_allows_string_lights_and_rejects_other(self):
        body = self.client.post("/api/gadgets/light",
                                json={"entity_id": "light.string_lights", "on": True}).json()
        self.assertTrue(body["ok"])
        self.assertTrue(any(c.endswith("light/turn_on") for c in SERVICE_CALLS), SERVICE_CALLS)
        r = self.client.post("/api/gadgets/light",
                             json={"entity_id": "binary_sensor.patio_door", "on": True})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/gadgets/light",
                             json={"entity_id": "light.nope", "on": True})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
