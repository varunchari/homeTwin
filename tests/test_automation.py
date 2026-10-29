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
from automation import apply_delay_override, compile_ir, validate_ir  # noqa: E402

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


class DelayOverrideTest(unittest.TestCase):
    def test_none_keeps_model_delay(self):
        self.assertEqual(apply_delay_override(valid_ir(delay_s=60), None)["delay_s"], 60)

    def test_explicit_override_replaces_model_delay(self):
        self.assertEqual(apply_delay_override(valid_ir(delay_s=0), 60)["delay_s"], 60)
        self.assertEqual(apply_delay_override(valid_ir(delay_s=60), 0)["delay_s"], 0)

    def test_override_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            apply_delay_override(valid_ir(), 3601)
        with self.assertRaises(ValueError):
            apply_delay_override(valid_ir(), -1)


class BasetenConfigTest(unittest.TestCase):
    def test_missing_key_or_model_is_configuration_error(self):
        saved_key = os.environ.pop("BASETEN_API_KEY", None)
        saved_model = os.environ.pop("BASETEN_MODEL", None)
        try:
            with self.assertRaises(spark_client.SparkError):
                spark_client.open_provider_config()
            os.environ["BASETEN_API_KEY"] = "test-key-not-real"
            with self.assertRaises(spark_client.SparkError):
                spark_client.open_provider_config()
        finally:
            if saved_key is not None:
                os.environ["BASETEN_API_KEY"] = saved_key
            else:
                os.environ.pop("BASETEN_API_KEY", None)
            if saved_model is not None:
                os.environ["BASETEN_MODEL"] = saved_model
            else:
                os.environ.pop("BASETEN_MODEL", None)

    def test_configured_values_returned_without_hardcoded_model(self):
        os.environ["BASETEN_API_KEY"] = "test-key-not-real"
        os.environ["BASETEN_MODEL"] = "dashboard-model-under-test"
        try:
            base, model, _key = spark_client.open_provider_config()
            self.assertEqual(base, "https://inference.baseten.co/v1")
            self.assertEqual(model, "dashboard-model-under-test")
        finally:
            os.environ.pop("BASETEN_API_KEY", None)
            os.environ.pop("BASETEN_MODEL", None)


HA_STATES = [
    {"entity_id": "binary_sensor.patio_door", "state": "off", "attributes": {}},
    {"entity_id": "light.floor_lamp", "state": "off", "attributes": {}},
    {"entity_id": "input_boolean.tv_on", "state": "off",
     "attributes": {"friendly_name": "TV power"}},
    {"entity_id": "input_boolean.lamp_floor_on", "state": "off",
     "attributes": {"friendly_name": "Floor lamp input"}},
]
DEPLOYED: dict[str, dict] = {}


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
        aid = url.rsplit("/", 1)[-1]
        if aid in DEPLOYED:
            return FakeResp(200, DEPLOYED[aid])
        return FakeResp(404, {})

    async def post(self, url, headers=None, json=None):
        if "/api/services/" in url:
            SERVICE_CALLS.append(url.rsplit("/api/services/", 1)[-1])
            return FakeResp(200, [])
        aid = url.rsplit("/", 1)[-1]
        DEPLOYED[aid] = json or {}
        return FakeResp(200, {})

    async def delete(self, url, headers=None):
        aid = url.rsplit("/", 1)[-1]
        SERVICE_CALLS.append(f"delete:{aid}")
        if aid in DEPLOYED:
            del DEPLOYED[aid]
            return FakeResp(200, {})
        return FakeResp(404, {})


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

    def test_propose_delay_dropdown_overrides_model(self):
        pid = make_bound_photo(self.client, w=501)
        body = self.client.post("/api/automations/propose",
                                json={"photo_id": pid, "source_object_id": "door",
                                      "target_object_id": "lamp", "text": "",
                                      "delay_s": 60}).json()
        self.assertEqual(body["ir"]["delay_s"], 60)
        self.assertEqual(len(body["compiled"]["action"]), 3)
        self.assertEqual(body["compiled"]["action"][1], {"delay": "00:01:00"})
        self.assertEqual(body["provider"], "hosted")

    def test_propose_unknown_provider_rejected(self):
        pid = make_bound_photo(self.client, w=502)
        r = self.client.post("/api/automations/propose",
                             json={"photo_id": pid, "source_object_id": "door",
                                   "target_object_id": "lamp", "text": "",
                                   "provider": "other"})
        self.assertEqual(r.status_code, 422)

    def test_propose_open_without_host_config_is_503(self):
        saved_key = os.environ.pop("BASETEN_API_KEY", None)
        saved_model = os.environ.pop("BASETEN_MODEL", None)
        try:
            pid = make_bound_photo(self.client, w=503)
            r = self.client.post("/api/automations/propose",
                                 json={"photo_id": pid, "source_object_id": "door",
                                       "target_object_id": "lamp", "text": "",
                                       "provider": "open"})
            self.assertEqual(r.status_code, 503)
        finally:
            if saved_key is not None:
                os.environ["BASETEN_API_KEY"] = saved_key
            if saved_model is not None:
                os.environ["BASETEN_MODEL"] = saved_model

    def test_propose_open_routes_to_baseten_config(self):
        seen = {}

        async def capturing(system, user, schema, model="x", api_base=None, api_key=None):
            seen.update(model=model, api_base=api_base, api_key=api_key)
            return dict(SPARK_IR)

        os.environ["BASETEN_API_KEY"] = "test-key-not-real"
        os.environ["BASETEN_MODEL"] = "dashboard-model-under-test"
        spark_client.complete_json = capturing
        try:
            pid = make_bound_photo(self.client, w=504)
            body = self.client.post("/api/automations/propose",
                                    json={"photo_id": pid, "source_object_id": "door",
                                          "target_object_id": "lamp", "text": "",
                                          "provider": "open"}).json()
            self.assertEqual(body["provider"], "open")
            self.assertEqual(body["model"], "dashboard-model-under-test")
            self.assertEqual(seen["api_base"], "https://inference.baseten.co/v1")
            self.assertEqual(seen["model"], "dashboard-model-under-test")
        finally:
            spark_client.complete_json = fake_complete
            os.environ.pop("BASETEN_API_KEY", None)
            os.environ.pop("BASETEN_MODEL", None)

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
        self.assertIn("automation/reload", SERVICE_CALLS)
        SERVICE_CALLS.clear()
        again = self.client.post(
            f"/api/automations/{prop['proposal_id']}/approve").json()
        self.assertTrue(again.get("already"))

    def test_approve_unknown_is_404(self):
        r = self.client.post("/api/automations/999999/approve")
        self.assertEqual(r.status_code, 404)

    def test_banned_intent_units(self):
        self.assertEqual(proxy._banned_intent("unlock the front door"), "unlock")
        self.assertEqual(proxy._banned_intent("Lock it at night"), "lock")
        self.assertIsNone(proxy._banned_intent("only after sunset"))
        self.assertIsNone(proxy._banned_intent(""))
        self.assertIsNone(proxy._banned_intent("open when the patio door opens"))

    def test_lock_text_rejected_before_model_or_store(self):
        async def must_not_run(*a, **k):
            raise AssertionError("Spark must not be called for banned intent")

        spark_client.complete_json = must_not_run
        try:
            pid = make_bound_photo(self.client, w=732)
            before = self.client.get(
                f"/api/automations/proposals?photo_id={pid}").json()["proposals"]
            r = self.client.post("/api/automations/propose",
                                 json={"photo_id": pid, "source_object_id": "door",
                                       "target_object_id": "lamp",
                                       "text": "unlock the front door"})
            self.assertEqual(r.status_code, 422)
            self.assertIn("allowlist", r.json()["detail"])
            after = self.client.get(
                f"/api/automations/proposals?photo_id={pid}").json()["proposals"]
            self.assertEqual(len(after), len(before))
        finally:
            spark_client.complete_json = fake_complete

    def test_reset_deletes_deployed_rules(self):
        pid = make_bound_photo(self.client, w=748)
        prop = self.client.post("/api/automations/propose",
                                json={"photo_id": pid, "source_object_id": "door",
                                      "target_object_id": "lamp", "text": ""}).json()
        self.client.post(f"/api/automations/{prop['proposal_id']}/approve")
        aid = f"hometwin_{prop['proposal_id']}"
        self.assertIn(aid, DEPLOYED)
        body = self.client.post("/api/reset").json()
        self.assertIn(aid, body["automations_cleared"])
        self.assertNotIn(aid, DEPLOYED)
        listed = self.client.get(
            f"/api/automations/proposals?photo_id={pid}").json()["proposals"]
        self.assertEqual(listed, [])
        self.assertGreaterEqual(body["history_cleared"], 1)
        graph = self.client.get(f"/api/photos/{pid}/graph").json()
        self.assertEqual(graph["bindings"], {})
        self.assertGreaterEqual(body["bindings_cleared"], 2)
        self.assertTrue(graph["regions"])
        again = self.client.post("/api/reset").json()
        self.assertEqual(again["automations_cleared"], [])
        SERVICE_CALLS.clear()

    def test_tap_toggles_bindable_switch_and_rejects_helpers(self):
        pid = make_bound_photo(self.client, w=764)
        self.client.post(f"/api/photos/{pid}/regions",
                         json={"label": "tv", "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2})
        r = self.client.post(f"/api/photos/{pid}/bindings",
                             json={"object_id": "tv",
                                   "entity_id": "input_boolean.lamp_floor_on"})
        self.assertEqual(r.status_code, 422)
        r = self.client.post(f"/api/photos/{pid}/bindings",
                             json={"object_id": "tv",
                                   "entity_id": "input_boolean.tv_on"})
        self.assertTrue(r.json()["ok"])
        body = self.client.post(f"/api/photos/{pid}/tap",
                                json={"object_id": "tv"}).json()
        self.assertEqual(body["action"], "toggle")
        self.assertIn("input_boolean/toggle", SERVICE_CALLS)
        SERVICE_CALLS.clear()

    def test_index_never_caches_with_versioned_assets(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("no-store", r.headers.get("cache-control", ""))
        self.assertRegex(r.text, r"/static/app\.js\?v=\d+")
        self.assertRegex(r.text, r"/static/app\.css\?v=\d+")

    def test_proposals_filtered_by_photo(self):
        pid_a = make_bound_photo(self.client, w=700)
        pid_b = make_bound_photo(self.client, w=716)
        for pid in (pid_a, pid_b):
            self.client.post("/api/automations/propose",
                             json={"photo_id": pid, "source_object_id": "door",
                                   "target_object_id": "lamp", "text": ""})
        only_a = self.client.get(
            f"/api/automations/proposals?photo_id={pid_a}").json()["proposals"]
        self.assertTrue(only_a)
        self.assertTrue(all(p["photo_id"] == pid_a for p in only_a))
        all_props = self.client.get("/api/automations/proposals").json()["proposals"]
        self.assertGreaterEqual(len(all_props), len(only_a) + 1)


class WhatIfTest(unittest.TestCase):
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

    def _proposal(self, w):
        pid = make_bound_photo(self.client, w=w)
        return self.client.post("/api/automations/propose",
                                json={"photo_id": pid, "source_object_id": "door",
                                      "target_object_id": "lamp", "text": ""}).json()

    def test_lists_proposals_with_summaries(self):
        prop = self._proposal(600)
        body = self.client.get("/api/automations/proposals").json()
        match = [p for p in body["proposals"] if p["id"] == prop["proposal_id"]]
        self.assertEqual(len(match), 1)
        self.assertIn("binary_sensor.patio_door", match[0]["summary"])

    def test_daytime_no_condition_fires(self):
        prop = self._proposal(616)
        body = self.client.post("/api/whatif",
                                json={"proposal_id": prop["proposal_id"],
                                      "door": "on", "sun": "day"}).json()
        self.assertTrue(body["simulated"])
        self.assertTrue(body["fires"])
        self.assertEqual(len(body["action"]), 1)

    def test_closed_door_never_fires(self):
        prop = self._proposal(632)
        body = self.client.post("/api/whatif",
                                json={"proposal_id": prop["proposal_id"],
                                      "door": "off", "sun": "night"}).json()
        self.assertFalse(body["fires"])
        self.assertFalse(body["trigger_match"])

    def test_sunset_gates_on_night(self):
        async def sunset_complete(system, user, schema, model="x",
                                  api_base=None, api_key=None):
            ir = dict(valid_ir())
            ir["condition"] = {"sun": "after_sunset"}
            return ir

        spark_client.complete_json = sunset_complete
        try:
            prop = self._proposal(664)
        finally:
            spark_client.complete_json = fake_complete
        day = self.client.post("/api/whatif",
                               json={"proposal_id": prop["proposal_id"],
                                     "door": "on", "sun": "day"}).json()
        night = self.client.post("/api/whatif",
                                 json={"proposal_id": prop["proposal_id"],
                                       "door": "on", "sun": "night"}).json()
        self.assertFalse(day["fires"])
        self.assertTrue(day["condition_pass"] is False)
        self.assertTrue(night["fires"])

    def test_bad_inputs_rejected(self):
        prop = self._proposal(648)
        r = self.client.post("/api/whatif",
                             json={"proposal_id": prop["proposal_id"],
                                   "door": "ajar", "sun": "day"})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/whatif",
                             json={"proposal_id": 999999, "door": "on", "sun": "day"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
