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
        import io
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (400, 300), (0, 0, 0)).save(buf, "JPEG")
        pid = self.client.post(
            "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")}
        ).json()["photo_id"]
        body = self.client.post(
            f"/api/photos/{pid}/segment", json={"phrase": "smart display"}
        ).json()
        self.assertEqual(body["matched_phrase"], "display")
        self.assertEqual(len(body["regions"]), 1)
        self.assertEqual(body["regions"][0]["object_id"], "display")

    def test_total_miss_returns_note(self):
        import io
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (400, 300), (0, 0, 0)).save(buf, "JPEG")
        pid = self.client.post(
            "/api/photos", files={"file": ("r.jpg", buf.getvalue(), "image/jpeg")}
        ).json()["photo_id"]
        body = self.client.post(
            f"/api/photos/{pid}/segment", json={"phrase": "no such thing here"}
        ).json()
        self.assertIsNone(body["matched_phrase"])
        self.assertEqual(body["regions"], [])
        self.assertIn("manually", body["note"])


def tearDownModule():
    shutil.rmtree(TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
