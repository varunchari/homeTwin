"""Day 4 regression tests: AutomationIR validation, compiler, approval gate.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import io
import os
import sys
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hometwin-test-auto-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as proxy  # noqa: E402
import spark_client  # noqa: E402
from automation import compile_ir, validate_ir  # noqa: E402

REGISTRY = {"binary_sensor.patio_door", "light.floor_lamp",
            "light.string_lights", "light.reading_light"}


def valid_ir(**over):
    ir = {"trigger": {"entity_id": "binary_sensor.patio_door", "to": "on"},
          "condition": None,
          "action": {"entity_id": "light.floor_lamp", "service": "light.turn_on"},
          "delay_s": 0, "description": "door opens, lamp on"}
    ir.update(over)
    return ir


class ValidateTest(unittest.TestCase):
    def test_pattern1_state_to_action(self):
        self.assertEqual(validate_ir(valid_ir(), REGISTRY), [])

    def test_pattern2_with_sunset(self):
        ir = valid_ir(condition={"sun": "after_sunset"})
        self.assertEqual(validate_ir(ir, REGISTRY), [])

    def test_pattern3_with_delay(self):
        self.assertEqual(validate_ir(valid_ir(delay_s=60), REGISTRY), [])

    def test_rejects_lock_trigger(self):
        ir = valid_ir(trigger={"entity_id": "lock.front_door", "to": "on"})
        reasons = validate_ir(ir, REGISTRY | {"lock.front_door"})
        self.assertTrue(any("allowlist" in r for r in reasons))

    def test_rejects_cover_action(self):
        ir = valid_ir(action={"entity_id": "cover.blind", "service": "cover.open_cover"})
        reasons = validate_ir(ir, REGISTRY | {"cover.blind"})
        self.assertTrue(any("not a light" in r or "not allowed" in r for r in reasons))

    def test_rejects_unknown_entity(self):
        ir = valid_ir(action={"entity_id": "light.nope", "service": "light.turn_on"})
        self.assertTrue(any("Unknown" in r for r in validate_ir(ir, REGISTRY)))

    def test_rejects_bad_condition_and_delay(self):
        ir = valid_ir(condition={"sun": "at_noon"}, delay_s=99999)
        reasons = validate_ir(ir, REGISTRY)
        self.assertEqual(len(reasons), 2)

    def test_explicit_null_condition_counts_as_absent(self):
        self.assertEqual(validate_ir(valid_ir(condition={"sun": None}), REGISTRY), [])


class CompileTest(unittest.TestCase):
    def test_pattern1_shape(self):
        out = compile_ir(valid_ir(), alias="t")
        self.assertEqual(out["trigger"],
                         [{"platform": "state", "entity_id": "binary_sensor.patio_door",
                           "to": "on"}])
        self.assertNotIn("condition", out)
        self.assertEqual(len(out["action"]), 1)

    def test_pattern2_sunset_condition(self):
        out = compile_ir(valid_ir(condition={"sun": "after_sunset"}), alias="t")
        self.assertEqual(out["condition"], [{"condition": "sun", "after": "sunset"}])

    def test_pattern3_delay_appends_off(self):
        out = compile_ir(valid_ir(delay_s=60), alias="t")
        self.assertEqual(len(out["action"]), 3)
        self.assertEqual(out["action"][1], {"delay": "00:01:00"})
        self.assertEqual(out["action"][2]["service"], "light.turn_off")


HA_STATES = [
    {"entity_id": "binary_sensor.patio_door", "state": "off", "attributes": {}},
    {"entity_id": "light.floor_lamp", "state": "off", "attributes": {}},
]
DEPLOYED: dict[str, dict] = {}


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
        aid = url.rsplit("/", 1)[-1]
        if aid in DEPLOYED:
            return FakeResp(200, DEPLOYED[aid])
        return FakeResp(404, {})

    async def post(self, url, headers=None, json=None):
        if "/api/services/" in url:
            return FakeResp(200, [])
        aid = url.rsplit("/", 1)[-1]
        DEPLOYED[aid] = json or {}
        return FakeResp(200, {})


SPARK_IR = valid_ir()


async def fake_complete(system, user, schema, model="x", api_base=None, api_key=None):
    assert "AutomationIR" in system
    return dict(SPARK_IR)


spark_client.complete_json = fake_complete


async def _no_sam(image_bytes, phrase):
    return []


def make_bound_photo(client, w=500) -> int:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, 300), (5, 5, 5)).save(buf, "JPEG")
    saved, proxy.segment_image = proxy.segment_image, _no_sam
    try:
        pid = client.post(
            "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")}
        ).json()["photo_id"]
    finally:
        proxy.segment_image = saved
    client.post(f"/api/photos/{pid}/regions",
                json={"label": "door", "x": 0.7, "y": 0.0, "w": 0.2, "h": 1.0})
    client.post(f"/api/photos/{pid}/regions",
                json={"label": "lamp", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2})
    client.post(f"/api/photos/{pid}/bindings",
                json={"object_id": "door", "entity_id": "binary_sensor.patio_door"})
    client.post(f"/api/photos/{pid}/bindings",
                json={"object_id": "lamp", "entity_id": "light.floor_lamp"})
    return pid


class ProposeApproveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        cls.client = TestClient(proxy.app)

    def setUp(self):
        self._saved_client = proxy.httpx.AsyncClient
        self._saved_token = proxy.HA_TOKEN
        self._saved_complete = spark_client.complete_json
        proxy.httpx.AsyncClient = FakeAsyncClient
        proxy.HA_TOKEN = "test-token"
        spark_client.complete_json = fake_complete

    def tearDown(self):
        proxy.httpx.AsyncClient = self._saved_client
        proxy.HA_TOKEN = self._saved_token
        spark_client.complete_json = self._saved_complete

    def test_propose_valid_returns_compiled_with_approval(self):
        pid = make_bound_photo(self.client, w=500)
        body = self.client.post("/api/automations/propose",
                                json={"photo_id": pid, "source_object_id": "door",
                                      "target_object_id": "lamp", "text": ""}).json()
        self.assertTrue(body["approval_required"])
        self.assertIn("trigger", body["compiled"])
        self.assertEqual(body["compiled"]["trigger"][0]["entity_id"],
                         "binary_sensor.patio_door")

    def test_propose_unbound_source_conflicts(self):
        pid = make_bound_photo(self.client, w=516)
        r = self.client.post("/api/automations/propose",
                             json={"photo_id": pid, "source_object_id": "ghost",
                                   "target_object_id": "lamp", "text": ""})
        self.assertEqual(r.status_code, 404)
        self.client.post(f"/api/photos/{pid}/regions",
                         json={"label": "spare", "x": 0.4, "y": 0.4, "w": 0.1, "h": 0.1})
        r = self.client.post("/api/automations/propose",
                             json={"photo_id": pid, "source_object_id": "spare",
                                   "target_object_id": "lamp", "text": ""})
        self.assertEqual(r.status_code, 409)

    def test_propose_invalid_plan_rejected(self):
        async def bad(system, user, schema, model="x", api_base=None, api_key=None):
            return valid_ir(action={"entity_id": "lock.front_door",
                                    "service": "lock.unlock"})

        spark_client.complete_json = bad
        try:
            pid = make_bound_photo(self.client, w=532)
            r = self.client.post("/api/automations/propose",
                                 json={"photo_id": pid, "source_object_id": "door",
                                       "target_object_id": "lamp", "text": ""})
            self.assertEqual(r.status_code, 422)
            self.assertIn("allow", r.json()["detail"])
        finally:
            spark_client.complete_json = fake_complete

    def test_approve_deploys_with_readback(self):
        pid = make_bound_photo(self.client, w=548)
        prop = self.client.post("/api/automations/propose",
                                json={"photo_id": pid, "source_object_id": "door",
                                      "target_object_id": "lamp", "text": ""}).json()
        body = self.client.post(
            f"/api/automations/{prop['proposal_id']}/approve").json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["automation_id"].startswith("hometwin_"))
        self.assertIn("trigger", body["read_back"])
        again = self.client.post(
            f"/api/automations/{prop['proposal_id']}/approve").json()
        self.assertTrue(again.get("already"))

    def test_approve_unknown_is_404(self):
        r = self.client.post("/api/automations/999999/approve")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
