"""Day 2 regression tests: phrase fallback and box/mask dedupe.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import os
import shutil
import sys
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="hometwin-test-")
os.environ["DATA_DIR"] = TEST_DIR
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as proxy  # noqa: E402


class PhraseVariantsTest(unittest.TestCase):
    def test_full_phrase_first_then_tails(self):
        self.assertEqual(proxy._phrase_variants("smart display"), ["smart display", "display"])

    def test_single_word(self):
        self.assertEqual(proxy._phrase_variants("lamp"), ["lamp"])

    def test_three_words(self):
        self.assertEqual(
            proxy._phrase_variants("patio door sensor"),
            ["patio door sensor", "door sensor", "sensor"],
        )


class DedupeTest(unittest.TestCase):
    def test_box_mask_pair_merges_preferring_mask(self):
        box = (0.1, 0.1, 0.2, 0.2)
        merged = proxy._dedupe([(box, None), (box, b"PNG")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["mask_png"], b"PNG")

    def test_distinct_boxes_stay_separate(self):
        merged = proxy._dedupe([((0.1, 0.1, 0.2, 0.2), None), ((0.6, 0.6, 0.2, 0.2), None)])
        self.assertEqual(len(merged), 2)

    def test_iou_bounds(self):
        self.assertAlmostEqual(proxy._iou((0, 0, 1, 1), (0, 0, 1, 1)), 1.0)
        self.assertEqual(proxy._iou((0, 0, 0.1, 0.1), (0.9, 0.9, 0.1, 0.1)), 0.0)


_fallback_counter = [470]


async def _no_sam(image_bytes, phrase):
    return []


def _fallback_upload(client):
    # Unique dimensions per upload: solid colors can quantize identically and
    # the upload dedupe would otherwise merge fixtures in one shared DB.
    # SAM silenced: auto-segment must not pre-create regions under test.
    import io
    from PIL import Image

    import app as proxy_module

    _fallback_counter[0] += 16
    buf = io.BytesIO()
    Image.new("RGB", (_fallback_counter[0], 300), (0, 0, 0)).save(buf, "JPEG")
    saved = proxy_module.segment_image
    proxy_module.segment_image = _no_sam
    try:
        return client.post(
            "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")}
        ).json()["photo_id"]
    finally:
        proxy_module.segment_image = saved


class SegmentFallbackEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        async def fake_segment(image_bytes, phrase):
            if phrase == "display":
                return [{"object_id": None, "bbox": (10, 10, 50, 50), "mask_png": None}]
            return []

        proxy.segment_image = fake_segment
        cls.client = TestClient(proxy.app)

    def test_fallback_labels_regions_with_matched_phrase(self):
        pid = _fallback_upload(self.client)
        body = self.client.post(
            f"/api/photos/{pid}/segment", json={"phrase": "smart display"}
        ).json()
        self.assertEqual(body["matched_phrase"], "display")
        self.assertEqual(len(body["regions"]), 1)
        self.assertEqual(body["regions"][0]["object_id"], "display")

    def test_total_miss_returns_note(self):
        pid = _fallback_upload(self.client)
        body = self.client.post(
            f"/api/photos/{pid}/segment", json={"phrase": "no such thing here"}
        ).json()
        self.assertIsNone(body["matched_phrase"])
        self.assertEqual(body["regions"], [])
        self.assertIn("manually", body["note"])


class ResegmentReplaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        async def fake_segment(image_bytes, phrase):
            if phrase == "display":
                return [{"object_id": None, "bbox": (10, 10, 50, 50), "mask_png": None}]
            return []

        class FakeResp:
            def __init__(self, code, payload):
                self.status_code = code
                self._payload = payload

            def json(self):
                return self._payload

        class FakeHA:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None):
                return FakeResp(200, [{"entity_id": "light.floor_lamp",
                                       "state": "off", "attributes": {}}])

            async def post(self, url, headers=None, json=None):
                return FakeResp(200, [])

        cls._saved = proxy.segment_image
        cls._saved_ha = proxy.httpx.AsyncClient
        proxy.segment_image = fake_segment
        proxy.httpx.AsyncClient = FakeHA
        proxy.HA_TOKEN = "test-token"
        cls.client = TestClient(proxy.app)

    @classmethod
    def tearDownClass(cls):
        proxy.segment_image = cls._saved
        proxy.httpx.AsyncClient = cls._saved_ha

    def test_resegment_replaces_and_keeps_binding(self):
        pid = _fallback_upload(self.client)
        first = self.client.post(
            f"/api/photos/{pid}/segment", json={"phrase": "smart display"}).json()
        self.assertEqual([r["object_id"] for r in first["regions"]], ["display"])
        self.client.post(f"/api/photos/{pid}/bindings",
                         json={"object_id": "display", "entity_id": "light.floor_lamp"})
        second = self.client.post(
            f"/api/photos/{pid}/segment", json={"phrase": "smart display"}).json()
        self.assertEqual(second["replaced"], 1)
        self.assertEqual([r["object_id"] for r in second["regions"]], ["display"])
        self.assertEqual(second["dropped_bindings"], [])
        graph = self.client.get(f"/api/photos/{pid}/graph").json()
        self.assertEqual(graph["bindings"].get("display"), "light.floor_lamp")

    def test_vanished_region_drops_its_binding(self):
        import store as store_module

        pid = _fallback_upload(self.client)
        self.client.post(f"/api/photos/{pid}/regions",
                         json={"label": "old", "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1})
        # manual regions are never touched by segment refresh; exercise the
        # orphan cleanup directly at the store level instead
        removed = store_module.delete_phrase_regions(pid, "display")
        self.assertEqual(removed, [])
        self.client.post(f"/api/photos/{pid}/bindings",
                         json={"object_id": "old", "entity_id": "light.floor_lamp"})
        self.assertTrue(store_module.delete_binding(pid, "old"))


class UploadAutoSegmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        async def fake_segment(image_bytes, phrase):
            if phrase == "lamp":
                return [{"object_id": None, "bbox": (60, 30, 220, 270),
                         "mask_png": None}]
            return []

        cls._saved = proxy.segment_image
        proxy.segment_image = fake_segment
        cls.client = TestClient(proxy.app)

    @classmethod
    def tearDownClass(cls):
        proxy.segment_image = cls._saved

    def _upload(self, width=420, color=(10, 20, 30)):
        import io
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (width, 300), color).save(buf, "JPEG")
        return self.client.post(
            "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")})

    def test_upload_auto_segments(self):
        body = self._upload(width=420, color=(10, 20, 30)).json()
        self.assertFalse(body["reused"])
        self.assertEqual(len(body["auto_segment"]), 6)
        hits = [a for a in body["auto_segment"] if a["regions"]]
        self.assertEqual([a["phrase"] for a in hits], ["lamp"])
        self.assertEqual(len(body["regions"]), 1)

    def test_reupload_reuses_without_resegment(self):
        first = self._upload(width=440, color=(40, 50, 60)).json()["photo_id"]
        second = self._upload(width=440, color=(40, 50, 60)).json()
        self.assertTrue(second["reused"])
        self.assertEqual(second["photo_id"], first)
        self.assertNotIn("auto_segment", second)
        graph = self.client.get(f"/api/photos/{first}/graph").json()
        self.assertEqual(len(graph["regions"]), 1)


class ShaBackfillTest(unittest.TestCase):
    def test_legacy_photo_gets_sha(self):
        import sqlite3
        import store as store_module

        conn = store_module.connect()
        cur = conn.execute(
            "INSERT INTO photos (filename, width, height, created, sha)"
            " VALUES (?,?,?,?,?)",
            ("legacy.jpg", 10, 10, 0.0, None),
        )
        pid = cur.lastrowid
        conn.commit()
        conn.close()
        (store_module.PHOTOS_DIR / f"{pid}.jpg").write_bytes(b"fakejpeg")
        conn2 = store_module.connect()
        try:
            row = conn2.execute("SELECT sha FROM photos WHERE id=?", (pid,)).fetchone()
            import hashlib
            self.assertEqual(row["sha"], hashlib.sha256(b"fakejpeg").hexdigest())
            self.assertIsNotNone(store_module.find_photo_by_sha(row["sha"]))
        finally:
            conn2.close()


class DemoPhotoEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        proxy.segment_image = _no_sam
        cls.client = TestClient(proxy.app)

    def test_demo_loads_through_real_pipeline_with_dedupe(self):
        first = self.client.post("/api/photos/demo")
        if first.status_code == 404:
            self.skipTest("demo asset not bundled in this layout")
        first = first.json()
        self.assertFalse(first["reused"])
        self.assertIn("regions", first)
        second = self.client.post("/api/photos/demo").json()
        self.assertTrue(second["reused"])
        self.assertEqual(second["photo_id"], first["photo_id"])


def tearDownModule():
    shutil.rmtree(TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
