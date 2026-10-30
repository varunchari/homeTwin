"""Advisor + time-of-day tests: validation, presets, image shape, endpoints.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import io
import os
import sys
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hometwin-test-adv-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as proxy  # noqa: E402
import image_client  # noqa: E402
import spark_client  # noqa: E402
from advisor import (TIME_OF_DAY_PRESETS, validate_advisor_response,
                     validate_settings)  # noqa: E402

REGISTRY = {"light.floor_lamp", "light.string_lights", "light.reading_light",
            "binary_sensor.patio_door"}


def setting(name, actions):
    return {"name": name, "description": "test setting",
            "actions": [{"entity_id": e, "service": s} for e, s in actions]}


class ValidateTest(unittest.TestCase):
    def test_two_valid_settings_pass(self):
        settings = [
            setting("Cozy", [("light.reading_light", "light.turn_on"),
                             ("light.string_lights", "light.turn_on")]),
            setting("Bright", [("light.floor_lamp", "light.turn_on")]),
        ]
        self.assertEqual(validate_advisor_response(settings, REGISTRY), [])

    def test_advisor_must_propose_exactly_two(self):
        self.assertTrue(validate_advisor_response(
            [setting("Only", [("light.reading_light", "light.turn_on")])], REGISTRY))

    def test_rejects_unknown_nonlight_and_bad_service(self):
        bad = [setting("Bad", [("light.nope", "light.turn_on"),
                               ("binary_sensor.patio_door", "light.turn_on"),
                               ("light.reading_light", "light.toggle")])]
        reasons = validate_settings(bad, REGISTRY)
        self.assertTrue(any("Unknown" in r for r in reasons))
        self.assertTrue(any("not a light" in r for r in reasons))
        self.assertTrue(any("not allowed" in r for r in reasons))

    def test_rejects_duplicate_entity_in_one_setting(self):
        dup = [setting("Dup", [("light.reading_light", "light.turn_on"),
                               ("light.reading_light", "light.turn_off")])]
        self.assertTrue(any("twice" in r for r in validate_settings(dup, REGISTRY)))

    def test_presets_are_valid_and_deterministic(self):
        self.assertEqual(set(TIME_OF_DAY_PRESETS), {"morning", "sunset", "night"})
        for preset in TIME_OF_DAY_PRESETS.values():
            self.assertEqual(validate_settings(
                [{"name": preset["label"], "description": preset["description"],
                  "actions": preset["actions"]}], REGISTRY), [])
        morning = {a["entity_id"]: a["service"]
                   for a in TIME_OF_DAY_PRESETS["morning"]["actions"]}
        self.assertTrue(all(s == "light.turn_off" for s in morning.values()))
        sunset = {a["entity_id"]: a["service"]
                  for a in TIME_OF_DAY_PRESETS["sunset"]["actions"]}
        self.assertEqual(sunset["light.string_lights"], "light.turn_on")
        self.assertEqual(sunset["light.reading_light"], "light.turn_on")
        night = {a["entity_id"]: a["service"]
                 for a in TIME_OF_DAY_PRESETS["night"]["actions"]}
        self.assertEqual(night["light.reading_light"], "light.turn_on")
        self.assertEqual(night["light.floor_lamp"], "light.turn_off")


class ImageShapeTest(unittest.TestCase):
    def test_b64_json_decodes(self):
        import base64
        payload = {"data": [{"b64_json": base64.b64encode(b"fake-png").decode()}]}
        self.assertEqual(image_client._extract_image_bytes(payload), b"fake-png")

    def test_unknown_shape_raises(self):
        with self.assertRaises(image_client.ImageError):
            image_client._extract_image_bytes({"data": [{}]})
        with self.assertRaises(image_client.ImageError):
            image_client._extract_image_bytes({"data": []})


HA_STATES = [
    {"entity_id": "light.floor_lamp", "state": "off", "attributes": {}},
    {"entity_id": "light.string_lights", "state": "off", "attributes": {}},
    {"entity_id": "light.reading_light", "state": "off", "attributes": {}},
    {"entity_id": "binary_sensor.patio_door", "state": "off", "attributes": {}},
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
        SERVICE_CALLS.append(url.rsplit("/api/services/", 1)[-1]
                             if "/api/services/" in url else url)
        return FakeResp(200, [])


SUGGESTED = [
    setting("Cozy", [("light.reading_light", "light.turn_on"),
                     ("light.string_lights", "light.turn_on")]),
    setting("Bright", [("light.floor_lamp", "light.turn_on")]),
]


async def fake_complete(system, user, schema, model="x", api_base=None, api_key=None):
    assert "lighting settings" in system
    return {"settings": SUGGESTED}


async def fake_generate(prompt):
    assert "Cozy" in prompt
    return b"\x89PNGfake-preview"


async def fake_edit(image_bytes, prompt):
    assert image_bytes
    return b"\x89PNGfake-variant"


async def _no_sam(image_bytes, phrase):
    return []


def make_photo(client):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (500, 300), (5, 5, 5)).save(buf, "JPEG")
    saved = proxy.segment_image
    proxy.segment_image = _no_sam
    try:
        return client.post(
            "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")}
        ).json()["photo_id"]
    finally:
        proxy.segment_image = saved


class AdvisorEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        cls.client = TestClient(proxy.app)

    def setUp(self):
        self._saved_client = proxy.httpx.AsyncClient
        self._saved_token = proxy.HA_TOKEN
        self._saved_complete = spark_client.complete_json
        self._saved_generate = image_client.generate_image
        self._saved_edit = image_client.edit_image
        self._saved_service = proxy._ha_service
        proxy.httpx.AsyncClient = FakeAsyncClient
        proxy.HA_TOKEN = "test-token"
        spark_client.complete_json = fake_complete
        image_client.generate_image = fake_generate
        image_client.edit_image = fake_edit
        SERVICE_CALLS.clear()

        async def fake_service(service, payload):
            SERVICE_CALLS.append(service)

        proxy._ha_service = fake_service

    def tearDown(self):
        proxy.httpx.AsyncClient = self._saved_client
        proxy.HA_TOKEN = self._saved_token
        spark_client.complete_json = self._saved_complete
        image_client.generate_image = self._saved_generate
        image_client.edit_image = self._saved_edit
        proxy._ha_service = self._saved_service

    def test_suggest_preview_apply_and_decline_shape(self):
        pid = make_photo(self.client)
        body = self.client.post("/api/advisor/suggest",
                                json={"photo_id": pid,
                                      "request_text": "cozy evening"}).json()
        self.assertEqual(len(body["settings"]), 2)
        self.assertTrue(body["approval_required"])
        preview = self.client.post("/api/advisor/preview",
                                   json={"photo_id": pid,
                                         "setting": body["settings"][0],
                                         "request_text": "cozy evening"}).json()
        self.assertTrue(preview["illustrative"])
        self.assertTrue(preview["preview_url"].startswith("/api/advisor/previews/"))
        img = self.client.get(preview["preview_url"])
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img.content, b"\x89PNGfake-preview")
        applied = self.client.post("/api/advisor/apply",
                                   json={"setting": body["settings"][0]}).json()
        self.assertTrue(applied["ok"])
        self.assertIn("light/turn_on", SERVICE_CALLS)

    def test_suggest_rejects_bad_model_output(self):
        async def bad(system, user, schema, model="x", api_base=None, api_key=None):
            return {"settings": [setting("Bad", [("light.nope", "light.turn_on")])]}

        spark_client.complete_json = bad
        try:
            pid = make_photo(self.client)
            r = self.client.post("/api/advisor/suggest",
                                 json={"photo_id": pid, "request_text": "cozy"})
            self.assertEqual(r.status_code, 422)
        finally:
            spark_client.complete_json = fake_complete

    def test_time_of_day_preview_and_apply(self):
        pid = make_photo(self.client)
        body = self.client.post("/api/advisor/time-of-day",
                                json={"photo_id": pid, "variant": "sunset"}).json()
        self.assertEqual(body["label"], "Sunset")
        self.assertTrue(body["illustrative"])
        self.assertEqual(body["setting"]["actions"][0]["entity_id"],
                         "light.string_lights")
        img = self.client.get(body["preview_url"])
        self.assertEqual(img.content, b"\x89PNGfake-variant")
        applied = self.client.post("/api/advisor/apply",
                                   json={"setting": body["setting"]}).json()
        self.assertTrue(applied["ok"])
        r = self.client.post("/api/advisor/time-of-day",
                             json={"photo_id": pid, "variant": "dawn"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
