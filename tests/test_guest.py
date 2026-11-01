"""Guest view (sliced): tap-only, declared-guest header blocked elsewhere.

The guest page hides authoring panels; the backend guard in app.py
refuses authoring calls that carry X-HomeTwin-Guest: 1. This is NOT
authentication — the public demo has no accounts — so the tests assert
exactly that boundary: guest header allowed on read/tap/demo, 403 on
authoring, and no header still reaches the host path.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hometwin-test-guest-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from starlette.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402


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
        return FakeResp(200, [])

    async def post(self, url, headers=None, json=None):
        return FakeResp(200, [])


app_module.httpx.AsyncClient = FakeAsyncClient
app_module.HA_TOKEN = "test"

GUEST = {"X-HomeTwin-Guest": "1"}


class GuestGuardTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_guest_allowed_read(self):
        r = self.client.get("/api/entities", headers=GUEST)
        self.assertEqual(r.status_code, 200)

    def test_guest_blocked_authoring(self):
        for method, path in [
            ("POST", "/api/photos"),
            ("POST", "/api/photos/1/segment"),
            ("POST", "/api/photos/1/bindings"),
            ("DELETE", "/api/photos/1/bindings/patio-door"),
            ("POST", "/api/photos/1/suggest-bindings"),
            ("POST", "/api/automations/propose"),
            ("POST", "/api/automations/1/approve"),
            ("POST", "/api/whatif"),
            ("POST", "/api/advisor/suggest"),
            ("POST", "/api/voice/transcribe"),
            ("POST", "/api/photos/1/move-propose"),
            ("POST", "/api/scenes"),
            ("POST", "/api/reset"),
        ]:
            r = self.client.request(method, path, headers=GUEST, json={})
            self.assertEqual(r.status_code, 403, f"{method} {path}")
            self.assertIn("tap-only", r.json()["detail"])

    def test_no_header_not_guest_blocked(self):
        # Without the header, the guard does not fire: the request reaches
        # the host path (it may then fail on HA/model, but never 403-guest).
        r = self.client.post("/api/reset", json={})
        self.assertNotEqual(r.status_code, 403)

    def test_guest_page_marks_authoring_hidden(self):
        html = (Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text()
        self.assertIn('id="guest-banner"', html)
        self.assertIn("Guest view", html)
        for section in ("2 · Bind", "4 · Automate", "Voice", "5 · What-If",
                        "6 · Design Advisor", "7 · Rearrange", "8 · Scenes"):
            # Each authoring section must carry the guest-hide class.
            idx = html.find(section)
            start = html.rfind("<section", 0, idx)
            self.assertIn("guest-hide", html[start:idx + 20], section)


if __name__ == "__main__":
    unittest.main()
