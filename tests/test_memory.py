"""State-memory tests: snapshots, retention, history endpoint, recorder tick.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import asyncio
import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hometwin-test-mem-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as proxy  # noqa: E402
import store as store_module  # noqa: E402

HA_STATES = [
    {"entity_id": "light.reading_light", "state": "on", "attributes": {}},
    {"entity_id": "light.floor_lamp", "state": "off", "attributes": {}},
    {"entity_id": "binary_sensor.patio_door", "state": "off", "attributes": {}},
    {"entity_id": "input_boolean.tv_on", "state": "on",
     "attributes": {"friendly_name": "TV power"}},
    {"entity_id": "sun.sun", "state": "above_horizon", "attributes": {}},
    {"entity_id": "zone.home", "state": "0", "attributes": {}},
    {"entity_id": "person.hometwin_owner", "state": "unknown", "attributes": {}},
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
        return FakeResp(200, HA_STATES)


class SnapshotStoreTest(unittest.TestCase):
    def test_record_and_read_oldest_first(self):
        now = time.time()
        store_module.record_snapshot([(now, "mem-probe-light", "on"),
                                      (now - 10, "mem-probe-light", "off")])
        rows = store_module.snapshot_history(entity_id="mem-probe-light")
        self.assertEqual([r["state"] for r in rows[-2:]], ["off", "on"])

    def test_prune_keeps_recent_only(self):
        now = time.time()
        store_module.record_snapshot([(now - 99999, "mem-probe-old", "on"),
                                      (now, "mem-probe-old", "off")])
        self.assertEqual(store_module.prune_snapshots(now - 100), 1)
        rows = store_module.snapshot_history(entity_id="mem-probe-old")
        self.assertEqual([r["state"] for r in rows], ["off"])

    def test_empty_record_is_noop(self):
        self.assertEqual(store_module.record_snapshot([]), 0)


class MemoryRecorderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        cls.client = TestClient(proxy.app)

    def setUp(self):
        self._saved_client = proxy.httpx.AsyncClient
        self._saved_token = proxy.HA_TOKEN
        proxy.httpx.AsyncClient = FakeAsyncClient
        proxy.HA_TOKEN = "test-token"

    def tearDown(self):
        proxy.httpx.AsyncClient = self._saved_client
        proxy.HA_TOKEN = self._saved_token

    def test_memorable_scope(self):
        self.assertTrue(proxy._memorable("light.reading_light"))
        self.assertTrue(proxy._memorable("binary_sensor.patio_door"))
        self.assertTrue(proxy._memorable("input_boolean.tv_on"))
        self.assertTrue(proxy._memorable("sun.sun"))
        self.assertFalse(proxy._memorable("zone.home"))
        self.assertFalse(proxy._memorable("person.hometwin_owner"))
        self.assertFalse(proxy._memorable("input_boolean.patio_door_open"))

    def test_tick_records_only_memorable(self):
        n = asyncio.run(
            proxy._record_snapshot_once())
        self.assertEqual(n, 5)
        rows = store_module.snapshot_history()
        ids = {r["entity_id"] for r in rows}
        self.assertNotIn("zone.home", ids)
        self.assertIn("light.reading_light", ids)

    def test_history_endpoint_filters(self):
        asyncio.run(
            proxy._record_snapshot_once())
        body = self.client.get("/api/history",
                               params={"entity_id": "sun.sun"}).json()
        self.assertTrue(body["snapshots"])
        self.assertTrue(all(s["entity_id"] == "sun.sun"
                            for s in body["snapshots"]))
        body = self.client.get("/api/history",
                               params={"minutes": 1, "limit": 2}).json()
        self.assertLessEqual(len(body["snapshots"]), 2)


if __name__ == "__main__":
    unittest.main()
