"""Auto-binding regression tests: Spark proposals, validation, approval path.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import io
import os
import sys
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hometwin-test-suggest-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as proxy  # noqa: E402
import spark_client  # noqa: E402

HA_STATES = [
    {"entity_id": "light.floor_lamp", "state": "off",
     "attributes": {"friendly_name": "Floor lamp"}},
    {"entity_id": "light.reading_light", "state": "off",
     "attributes": {"friendly_name": "Reading light"}},
    {"entity_id": "binary_sensor.patio_door", "state": "off",
     "attributes": {"friendly_name": "Patio door"}},
]


class FakeResp:
    def __init__(self, code, payload):
        self.status_code = code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Superset of the binding suite's fake (adds friendly names) that also
    records into its SERVICE_CALLS so both suites stay green in one process."""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        return FakeResp(200, HA_STATES)

    async def post(self, url, headers=None, json=None):
        if "/api/services/" in url:
            try:
                import test_binding
                test_binding.SERVICE_CALLS.append(
                    (url.split("/api/services/")[1], json or {}))
            except ImportError:
                pass
        return FakeResp(200, [])


proxy.httpx.AsyncClient = FakeAsyncClient
# Set explicitly: do not rely on another suite's import side effects.
proxy.HA_TOKEN = "test-token"

SPARK_REPLY = {"matches": [
    {"object_id": "lamp", "entity_id": "light.reading_light",
     "reason": "lamp by the window", "confidence": 0.9},
    {"object_id": "door", "entity_id": "binary_sensor.patio_door",
     "reason": "door sensor", "confidence": 0.95},
    {"object_id": "ghost", "entity_id": "light.floor_lamp",
     "reason": "hallucinated region", "confidence": 0.5},
    {"object_id": "lamp2", "entity_id": "light.reading_light",
     "reason": "double-booked entity", "confidence": 0.4},
]}


async def fake_complete(system, user, schema, model="x"):
    assert "light-like" in system
    return SPARK_REPLY


spark_client.complete_json = fake_complete


async def _no_sam(image_bytes, phrase):
    return []


_photo_counter = [0]


def make_photo(client) -> int:
    """Upload with SAM silenced so auto-segment adds nothing: the fixture
    regions below are exactly the photo's regions, whatever other suites
    patched into proxy.segment_image. Unique dimensions per call defeat the
    upload dedupe (solid colors can quantize identically) so every test
    owns its photo."""
    from PIL import Image

    _photo_counter[0] += 1
    w = 400 + _photo_counter[0] * 16
    saved = proxy.segment_image
    proxy.segment_image = _no_sam
    try:
        buf = io.BytesIO()
        Image.new("RGB", (w, 300), (1, 2, 3)).save(buf, "JPEG")
        pid = client.post(
            "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")}
        ).json()["photo_id"]
    finally:
        proxy.segment_image = saved
    for label, box in (("lamp", (0.1, 0.1, 0.2, 0.2)),
                       ("door", (0.7, 0.0, 0.2, 1.0)),
                       ("lamp2", (0.4, 0.4, 0.1, 0.1))):
        x, y, w, h = box
        client.post(f"/api/photos/{pid}/regions",
                    json={"label": label, "x": x, "y": y, "w": w, "h": h})
    return pid


class SuggestTest(unittest.TestCase):
    def setUp(self):
        from starlette.testclient import TestClient

        self.client = TestClient(proxy.app)
        self.pid = make_photo(self.client)

    def test_proposals_validated(self):
        body = self.client.post(f"/api/photos/{self.pid}/suggest-bindings").json()
        by_oid = {p["object_id"]: p for p in body["proposals"]}
        # hallucinated region dropped, double-booked entity flagged
        self.assertEqual(set(by_oid), {"lamp", "door", "lamp2"})
        self.assertFalse(by_oid["lamp"]["conflict"])
        self.assertTrue(by_oid["lamp2"]["conflict"])
        self.assertEqual(by_oid["door"]["entity_id"], "binary_sensor.patio_door")

    def test_approval_applies_through_normal_binding(self):
        body = self.client.post(f"/api/photos/{self.pid}/suggest-bindings").json()
        lamp = [p for p in body["proposals"] if p["object_id"] == "lamp"][0]
        r = self.client.post(f"/api/photos/{self.pid}/bindings",
                             json={"object_id": lamp["object_id"],
                                   "entity_id": lamp["entity_id"]})
        self.assertEqual(r.status_code, 200)
        bindings = self.client.get(f"/api/photos/{self.pid}/bindings").json()["bindings"]
        self.assertEqual(bindings["lamp"], "light.reading_light")

    def test_nothing_unbound_returns_note(self):
        for oid, eid in (("lamp", "light.reading_light"),
                         ("door", "binary_sensor.patio_door"),
                         ("lamp2", "light.floor_lamp")):
            self.client.post(f"/api/photos/{self.pid}/bindings",
                             json={"object_id": oid, "entity_id": eid})
        body = self.client.post(f"/api/photos/{self.pid}/suggest-bindings").json()
        self.assertEqual(body["proposals"], [])
        self.assertIn("already bound", body["note"])

    def test_prompt_marks_bound_context(self):
        seen = {}

        async def capture(system, user, schema, model="x"):
            seen["user"] = user
            return {"matches": []}

        import spark_client
        spark_client.complete_json = capture
        try:
            self.client.post(f"/api/photos/{self.pid}/bindings",
                             json={"object_id": "lamp", "entity_id": "light.floor_lamp"})
            body = self.client.post(f"/api/photos/{self.pid}/suggest-bindings").json()
            self.assertEqual(body["proposals"], [])
            self.assertIn("UNBOUND", seen["user"])
            self.assertIn("bound to light.floor_lamp", seen["user"])
            self.assertIn("reading nook", seen["user"])
        finally:
            spark_client.complete_json = fake_complete

    def test_spark_failure_is_502(self):
        async def boom(system, user, schema, model="x"):
            from spark_client import SparkError
            raise SparkError("down")

        spark_client.complete_json = boom
        try:
            pid = make_photo(self.client)
            r = self.client.post(f"/api/photos/{pid}/suggest-bindings")
            self.assertEqual(r.status_code, 502)
        finally:
            spark_client.complete_json = fake_complete


if __name__ == "__main__":
    unittest.main()
