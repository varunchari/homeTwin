"""Public-demo rate limit tests: model endpoints only, generous, per-IP.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from rate_limit import check_model_rate, client_ip, reset_model_rate  # noqa: E402


class FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, forwarded=None, host="1.2.3.4"):
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
        self.client = FakeClient(host)


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        reset_model_rate()

    def test_allows_up_to_limit_then_blocks(self):
        ip = "10.0.0.1"
        for _ in range(3):
            self.assertTrue(check_model_rate(ip, now=1000.0, limit=3, window_s=600))
        self.assertFalse(check_model_rate(ip, now=1001.0, limit=3, window_s=600))

    def test_rejected_calls_do_not_consume_budget(self):
        ip = "10.0.0.2"
        self.assertTrue(check_model_rate(ip, now=1000.0, limit=1, window_s=600))
        self.assertFalse(check_model_rate(ip, now=1001.0, limit=1, window_s=600))
        # Window slides: old call expires, budget returns.
        self.assertTrue(check_model_rate(ip, now=2000.0, limit=1, window_s=600))

    def test_per_ip_isolation(self):
        self.assertTrue(check_model_rate("10.0.0.3", now=1000.0, limit=1, window_s=600))
        self.assertTrue(check_model_rate("10.0.0.4", now=1000.0, limit=1, window_s=600))

    def test_client_ip_prefers_forwarded_for(self):
        self.assertEqual(client_ip(FakeRequest(forwarded="9.9.9.9, 1.2.3.4")),
                         "9.9.9.9")
        self.assertEqual(client_ip(FakeRequest(host="1.2.3.4")), "1.2.3.4")
        self.assertEqual(client_ip(None), "unknown")


class EndpointLimitTest(unittest.TestCase):
    def setUp(self):
        reset_model_rate()

    def test_limit_helper_raises_429_when_budget_spent(self):
        import tempfile

        os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hometwin-test-rate-"))
        import app as proxy
        from fastapi import HTTPException
        from rate_limit import MODEL_RATE_LIMIT

        ip = "5.5.5.5"
        for _ in range(MODEL_RATE_LIMIT):
            self.assertTrue(check_model_rate(ip, limit=MODEL_RATE_LIMIT))
        with self.assertRaises(HTTPException) as ctx:
            proxy._limit_model(FakeRequest(forwarded=ip))
        self.assertEqual(ctx.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
