"""Rearrange (lamp-move) + Scene Composer tests.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import io
import os
import shutil
import sys
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="hometwin-test-rearrange-")
os.environ["DATA_DIR"] = TEST_DIR
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as proxy  # noqa: E402
import image_client  # noqa: E402
import spark_client  # noqa: E402
import store as store_module  # noqa: E402

store_module.DATA_DIR = store_module.Path(TEST_DIR)
proxy.DATA_DIR = store_module.Path(TEST_DIR)


async def _no_sam(image_bytes, phrase):
    return []


def make_bound_lamp(client, w=800):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, 300), (6, 6, 6)).save(buf, "JPEG")
    saved = proxy.segment_image
    proxy.segment_image = _no_sam
    try:
        pid = client.post(
            "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")}
        ).json()["photo_id"]
    finally:
        proxy.segment_image = saved
    client.post(f"/api/photos/{pid}/regions",
                json={"label": "lamp", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2})
    client.post(f"/api/photos/{pid}/bindings",
                json={"object_id": "lamp", "entity_id": "light.reading_light"})
    return pid


async def fake_move_complete(system, user, schema, model="x",
                             api_base=None, api_key=None):
    assert "lamp" in system.lower()
    return {"x": 0.6, "y": 0.5, "reason": "closer to the sofa"}


async def fake_bad_move(system, user, schema, model="x",
                        api_base=None, api_key=None):
    return {"x": "far", "y": None}


async def fake_edit(image_bytes, prompt):
    assert image_bytes
    return b"\x89PNGfake-move"


SERVICE_CALLS = []

HA_STATES = [
    {"entity_id": "light.floor_lamp", "state": "off", "attributes": {}},
    {"entity_id": "light.string_lights", "state": "off", "attributes": {}},
    {"entity_id": "light.reading_light", "state": "off", "attributes": {}},
]


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
        if url.endswith("/api/states"):
            return FakeResp(200, HA_STATES)
        return FakeResp(404, {})


class RearrangeEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        cls.client = TestClient(proxy.app)

    def setUp(self):
        self._saved_client = proxy.httpx.AsyncClient
        proxy.httpx.AsyncClient = FakeAsyncClient
        self._saved_token = proxy.HA_TOKEN
        self._saved_complete = spark_client.complete_json
        self._saved_edit = image_client.edit_image
        self._saved_service = proxy._ha_service
        proxy.HA_TOKEN = "test-token"
        spark_client.complete_json = fake_move_complete
        image_client.edit_image = fake_edit
        SERVICE_CALLS.clear()

        async def fake_service(service, payload):
            SERVICE_CALLS.append((service, payload.get("entity_id")))

        proxy._ha_service = fake_service

    def tearDown(self):
        proxy.httpx.AsyncClient = self._saved_client
        proxy.HA_TOKEN = self._saved_token
        spark_client.complete_json = self._saved_complete
        image_client.edit_image = self._saved_edit
        proxy._ha_service = self._saved_service

    def test_propose_preview_approve_moves_pin_binding_intact(self):
        pid = make_bound_lamp(self.client)
        prop = self.client.post(f"/api/photos/{pid}/move-propose",
                                json={"photo_id": pid, "object_id": "lamp",
                                      "instruction": "closer to the sofa"}).json()
        self.assertEqual(prop["to_xy"], [0.6, 0.5])
        self.assertIn("sofa", prop["reason"])
        # Nothing moved yet: pin still home.
        graph = self.client.get(f"/api/photos/{pid}/graph").json()
        lamp = next(r for r in graph["regions"] if r["object_id"] == "lamp")
        self.assertAlmostEqual(lamp["x"], 0.1)
        prev = self.client.post(f"/api/photos/{pid}/move-preview",
                                json={"photo_id": pid,
                                      "move_id": prop["move_id"]}).json()
        self.assertTrue(prev["illustrative"])
        img = self.client.get(prev["preview_url"])
        self.assertEqual(img.content, b"\x89PNGfake-move")
        ok = self.client.post(f"/api/photos/{pid}/move-approve",
                              json={"photo_id": pid,
                                    "move_id": prop["move_id"]}).json()
        self.assertTrue(ok["ok"])
        graph = self.client.get(f"/api/photos/{pid}/graph").json()
        lamp = next(r for r in graph["regions"] if r["object_id"] == "lamp")
        self.assertAlmostEqual(lamp["x"], 0.6)
        self.assertAlmostEqual(lamp["y"], 0.5)
        # Binding untouched: tap still drives the same light.
        self.assertEqual(graph["bindings"]["lamp"], "light.reading_light")
        tap = self.client.post(f"/api/photos/{pid}/tap",
                               json={"object_id": "lamp"}).json()
        self.assertEqual(tap["entity_id"], "light.reading_light")
        self.assertIn(("light/toggle", "light.reading_light"), SERVICE_CALLS)

    def test_unbound_region_rejected(self):
        pid = make_bound_lamp(self.client, w=816)
        self.client.post(f"/api/photos/{pid}/regions",
                         json={"label": "tv", "x": 0.5, "y": 0.5,
                               "w": 0.2, "h": 0.2})
        r = self.client.post(f"/api/photos/{pid}/move-propose",
                             json={"photo_id": pid, "object_id": "tv",
                                   "instruction": "move it"})
        self.assertEqual(r.status_code, 409)

    def test_bad_coordinates_rejected(self):
        spark_client.complete_json = fake_bad_move
        try:
            pid = make_bound_lamp(self.client, w=832)
            r = self.client.post(f"/api/photos/{pid}/move-propose",
                                 json={"photo_id": pid, "object_id": "lamp",
                                       "instruction": "move it"})
            self.assertEqual(r.status_code, 502)
        finally:
            spark_client.complete_json = fake_move_complete

    def test_reset_restores_moved_pins(self):
        pid = make_bound_lamp(self.client, w=848)
        prop = self.client.post(f"/api/photos/{pid}/move-propose",
                                json={"photo_id": pid, "object_id": "lamp",
                                      "instruction": "move it"}).json()
        self.client.post(f"/api/photos/{pid}/move-approve",
                         json={"photo_id": pid, "move_id": prop["move_id"]})
        body = self.client.post("/api/reset").json()
        self.assertEqual(body["moves_restored"], 1)
        graph = self.client.get(f"/api/photos/{pid}/graph").json()
        lamp = next(r for r in graph["regions"] if r["object_id"] == "lamp")
        self.assertAlmostEqual(lamp["x"], 0.1)


class SceneEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        cls.client = TestClient(proxy.app)

    def setUp(self):
        self._saved_client = proxy.httpx.AsyncClient
        proxy.httpx.AsyncClient = FakeAsyncClient
        self._saved_service = proxy._ha_service
        SERVICE_CALLS.clear()

        async def fake_service(service, payload):
            SERVICE_CALLS.append((service, payload.get("entity_id")))

        proxy._ha_service = fake_service

    def tearDown(self):
        proxy.httpx.AsyncClient = self._saved_client
        proxy._ha_service = self._saved_service

    def test_save_apply_delete_round_trip(self):
        saved = self.client.post("/api/scenes",
                                 json={"name": "  Movie Night  "}).json()
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["name"], "Movie Night")
        self.assertEqual(saved["states"]["light.reading_light"], "on")
        listed = self.client.get("/api/scenes").json()["scenes"]
        self.assertTrue(any(s["name"] == "Movie Night" for s in listed))
        applied = self.client.post("/api/scenes/Movie Night/apply").json()
        self.assertTrue(applied["ok"])
        self.assertEqual(
            {a["entity_id"] for a in applied["applied"]},
            {"light.reading_light", "light.floor_lamp", "light.string_lights"})
        self.assertEqual(
            SERVICE_CALLS,
            [("light/turn_off", "light.floor_lamp"),
             ("light/turn_off", "light.string_lights"),
             ("light/turn_off", "light.reading_light")])
        r = self.client.delete("/api/scenes/Movie Night")
        self.assertTrue(r.json()["ok"])
        r = self.client.post("/api/scenes/Movie Night/apply")
        self.assertEqual(r.status_code, 404)

    def test_bad_names_rejected(self):
        for bad in ("", "   ", "x" * 41):
            r = self.client.post("/api/scenes", json={"name": bad})
            self.assertEqual(r.status_code, 422)

    def test_reset_clears_scenes(self):
        self.client.post("/api/scenes", json={"name": "Temp"})
        body = self.client.post("/api/reset").json()
        self.assertGreaterEqual(body["scenes_cleared"], 1)
        self.assertEqual(self.client.get("/api/scenes").json()["scenes"], [])


def tearDownModule():
    shutil.rmtree(TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
