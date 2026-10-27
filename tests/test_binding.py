"""Day 3 regression tests: bindings, tap-to-control, baseline reset.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import io
import os
import sys
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hometwin-test-bind-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as proxy  # noqa: E402

HA_STATES = [
    {"entity_id": "light.floor_lamp", "state": "off", "attributes": {}},
    {"entity_id": "light.string_lights", "state": "off", "attributes": {}},
    {"entity_id": "light.reading_light", "state": "off", "attributes": {}},
    {"entity_id": "binary_sensor.patio_door", "state": "off", "attributes": {}},
]
SERVICE_CALLS: list[tuple[str, dict]] = []


class FakeResp:
    def __init__(self, code, payload):
        self.status_code = code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        assert url.endswith("/api/states"), url
        return FakeResp(200, HA_STATES)

    async def post(self, url, headers=None, json=None):
        service = url.split("/api/services/")[1]
        SERVICE_CALLS.append((service, json or {}))
        return FakeResp(200, [])


proxy.httpx.AsyncClient = FakeAsyncClient
proxy.HA_TOKEN = "test-token"


def make_photo(client) -> int:
    # Unique dimensions defeat the upload dedupe (solid colors can quantize
    # identically) so every fixture owns its photo, even in one shared DB.
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (460, 300), (0, 0, 0)).save(buf, "JPEG")
    pid = client.post(
        "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")}
    ).json()["photo_id"]
    client.post(f"/api/photos/{pid}/regions",
                json={"label": "lamp", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2})
    client.post(f"/api/photos/{pid}/regions",
                json={"label": "door", "x": 0.7, "y": 0.0, "w": 0.2, "h": 1.0})
    return pid


class BindingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        cls.client = TestClient(proxy.app)
        cls.pid = make_photo(cls.client)

    def test_bind_and_read_back(self):
        r = self.client.post(f"/api/photos/{self.pid}/bindings",
                             json={"object_id": "lamp", "entity_id": "light.floor_lamp"})
        self.assertEqual(r.status_code, 200)
        bindings = self.client.get(f"/api/photos/{self.pid}/bindings").json()["bindings"]
        self.assertEqual(bindings.get("lamp"), "light.floor_lamp")
        graph = self.client.get(f"/api/photos/{self.pid}/graph").json()
        self.assertEqual(graph["bindings"].get("lamp"), "light.floor_lamp")

    def test_bind_unknown_region(self):
        r = self.client.post(f"/api/photos/{self.pid}/bindings",
                             json={"object_id": "nope", "entity_id": "light.floor_lamp"})
        self.assertEqual(r.status_code, 404)

    def test_bind_unknown_entity(self):
        r = self.client.post(f"/api/photos/{self.pid}/bindings",
                             json={"object_id": "lamp", "entity_id": "light.nope"})
        self.assertEqual(r.status_code, 422)

    def test_bind_disallowed_domain(self):
        r = self.client.post(f"/api/photos/{self.pid}/bindings",
                             json={"object_id": "lamp", "entity_id": "switch.kettle"})
        self.assertEqual(r.status_code, 422)

    def test_unbind(self):
        self.client.post(f"/api/photos/{self.pid}/bindings",
                         json={"object_id": "door", "entity_id": "binary_sensor.patio_door"})
        r = self.client.delete(f"/api/photos/{self.pid}/bindings/door")
        self.assertEqual(r.status_code, 200)
        bindings = self.client.get(f"/api/photos/{self.pid}/bindings").json()["bindings"]
        self.assertNotIn("door", bindings)


class TapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        cls.client = TestClient(proxy.app)
        cls.pid = make_photo(cls.client)
        cls.client.post(f"/api/photos/{cls.pid}/bindings",
                        json={"object_id": "lamp", "entity_id": "light.floor_lamp"})
        cls.client.post(f"/api/photos/{cls.pid}/bindings",
                        json={"object_id": "door", "entity_id": "binary_sensor.patio_door"})

    def test_tap_unknown_region(self):
        r = self.client.post(f"/api/photos/{self.pid}/tap", json={"object_id": "ghost"})
        self.assertEqual(r.status_code, 404)

    def test_tap_unbound_conflicts(self):
        self.client.post(f"/api/photos/{self.pid}/regions",
                         json={"label": "spare", "x": 0.4, "y": 0.4, "w": 0.1, "h": 0.1})
        r = self.client.post(f"/api/photos/{self.pid}/tap", json={"object_id": "spare"})
        self.assertEqual(r.status_code, 409)

    def test_tap_light_toggles(self):
        SERVICE_CALLS.clear()
        r = self.client.post(f"/api/photos/{self.pid}/tap", json={"object_id": "lamp"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["action"], "toggle")
        self.assertIn(("light/toggle", {"entity_id": "light.floor_lamp"}), SERVICE_CALLS)

    def test_tap_door_simulates(self):
        SERVICE_CALLS.clear()
        r = self.client.post(f"/api/photos/{self.pid}/tap", json={"object_id": "door"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["action"], "simulate")
        self.assertIn(("input_boolean/toggle",
                       {"entity_id": "input_boolean.patio_door_open"}), SERVICE_CALLS)

    def test_reset_baseline(self):
        SERVICE_CALLS.clear()
        r = self.client.post("/api/reset")
        self.assertEqual(r.status_code, 200)
        services = [s for s, _ in SERVICE_CALLS]
        self.assertEqual(services.count("input_boolean/turn_off"), 4)
        self.assertEqual(services.count("light/turn_off"), 3)


if __name__ == "__main__":
    unittest.main()
