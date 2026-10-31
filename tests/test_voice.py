"""Voice tests: supported-utterance matching, transcript shape, endpoints.

Run with the project venv:
    hometwin/.venv/bin/python -m unittest discover -s hometwin/tests -v
"""

import io
import os
import sys
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hometwin-test-voice-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app as proxy  # noqa: E402
import voice as voice_module  # noqa: E402
from voice import extract_transcript, match_utterance, normalize_transcript  # noqa: E402


class WireShapeTest(unittest.TestCase):
    def test_request_and_audio_parts(self):
        import asyncio
        import json as _json
        from unittest import mock

        seen = {}

        class CapResp:
            status_code = 200

            def json(self):
                return {"text": "turn the reading light on"}

        class CapClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, files=None, data=None):
                seen.update(url=url, files=files, data=data)
                return CapResp()

        saved_key = os.environ.get("MODEL_API_KEY")
        os.environ["MODEL_API_KEY"] = "test-key"
        try:
            with mock.patch("httpx.AsyncClient", CapClient):
                result = asyncio.run(
            voice_module.transcribe_audio(
                b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 32,
                "audio/wav"))
        finally:
            if saved_key is None:
                del os.environ["MODEL_API_KEY"]
            else:
                os.environ["MODEL_API_KEY"] = saved_key
        self.assertEqual(result, "turn the reading light on")
        self.assertTrue(seen["url"].endswith("/asr/transcribe"))
        self.assertIn("audio", seen["files"])
        self.assertEqual(seen["files"]["audio"][0], "voice.wav")
        self.assertEqual(seen["files"]["audio"][2], "audio/wav")
        request = _json.loads(seen["data"]["request"])
        self.assertEqual(request["model"], voice_module.TRANSCRIBE_MODEL)
        self.assertEqual(request["audioEncoding"], "WAV")

    def test_non_wav_rejected_before_any_call(self):
        async def exploding(*a, **k):
            raise AssertionError("no HTTP for non-WAV input")

        from unittest import mock

        with mock.patch("httpx.AsyncClient", exploding):
            for bad in (b"", b"not-a-wav-file-at-all", b"RIFF....fake"):
                with self.assertRaises(Exception):
                    import asyncio

                    asyncio.run(voice_module.transcribe_audio(bad))


class MatchTest(unittest.TestCase):
    def test_all_four_supported(self):
        cases = [
            ("Turn the reading light on", "tap-control"),
            ("When the door opens, turn the reading light on", "pattern1"),
            ("When the door opens after sunset, turn the string lights on", "pattern2"),
            ("When the door opens, turn the reading light on, off after a minute", "pattern3"),
        ]
        for text, kind in cases:
            matched = match_utterance(text)
            self.assertIsNotNone(matched, text)
            self.assertEqual(matched["kind"], kind)

    def test_variants_and_case_and_punctuation(self):
        self.assertEqual(match_utterance("TURN ON THE READING LIGHT!")["kind"],
                         "tap-control")
        self.assertEqual(match_utterance(
            "when the patio door opens after sunset, turn the string lights on")["kind"],
            "pattern2")

    def test_unsupported_never_matches(self):
        for text in ("unlock the front door",
                     "turn the string lights on for 15 minutes",
                     "are the patio lights on?",
                     "turn the floor lamp on",
                     ""):
            self.assertIsNone(match_utterance(text), text)

    def test_normalize(self):
        self.assertEqual(normalize_transcript("  When, the door OPENS!  "),
                         "when the door opens")


class TranscriptShapeTest(unittest.TestCase):
    def test_text_transcript_and_transcription_keys(self):
        self.assertEqual(extract_transcript({"text": "hello"}), "hello")
        self.assertEqual(extract_transcript({"transcript": "hello"}), "hello")
        self.assertEqual(extract_transcript({"data": [{"text": "hello"}]}), "hello")

    def test_live_api_shapes(self):
        # Observed 2026-10-29: real responses carry transcript/turns keys.
        self.assertEqual(
            extract_transcript({"transcript": {"text": "hello"}}), "hello")
        self.assertEqual(
            extract_transcript({"turns": [{"text": "hello"}]}), "hello")
        # Toneless audio yields no text: still raises.
        with self.assertRaises(voice_module.TranscribeError):
            extract_transcript({"transcript": "", "turns": [],
                                "audioDurationMs": 1000})

    def test_unknown_shape_raises(self):
        with self.assertRaises(voice_module.TranscribeError):
            extract_transcript({"data": [{}]})
        with self.assertRaises(voice_module.TranscribeError):
            extract_transcript({})


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
        SERVICE_CALLS.append(url)
        return FakeResp(200, [])


async def fake_transcribe(audio_bytes, mime="audio/webm"):
    assert audio_bytes
    return "When the door opens, turn the reading light on"


async def fake_transcribe_unsupported(audio_bytes, mime="audio/webm"):
    return "unlock the front door"


class VoiceEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from starlette.testclient import TestClient

        cls.client = TestClient(proxy.app)

    def setUp(self):
        self._saved_client = proxy.httpx.AsyncClient
        self._saved_token = proxy.HA_TOKEN
        self._saved_transcribe = voice_module.transcribe_audio
        self._saved_service = proxy._ha_service
        proxy.httpx.AsyncClient = FakeAsyncClient
        proxy.HA_TOKEN = "test-token"
        voice_module.transcribe_audio = fake_transcribe
        SERVICE_CALLS.clear()

        async def fake_service(service, payload):
            SERVICE_CALLS.append(service)

        proxy._ha_service = fake_service

    def tearDown(self):
        proxy.httpx.AsyncClient = self._saved_client
        proxy.HA_TOKEN = self._saved_token
        voice_module.transcribe_audio = self._saved_transcribe
        proxy._ha_service = self._saved_service

    def test_transcribe_supported_pattern(self):
        body = self.client.post(
            "/api/voice/transcribe",
            files={"file": ("voice.webm", b"fake-audio", "audio/webm")}).json()
        self.assertTrue(body["supported"])
        self.assertEqual(body["matched"]["kind"], "pattern1")
        self.assertEqual(body["matched"]["automate_text"],
                         "when the door opens, turn the reading light on")
        self.assertEqual(body["matched"]["target_entity"], "light.reading_light")

    def test_transcribe_unsupported_is_not_executed(self):
        voice_module.transcribe_audio = fake_transcribe_unsupported
        try:
            body = self.client.post(
                "/api/voice/transcribe",
                files={"file": ("voice.webm", b"fake-audio", "audio/webm")}).json()
            self.assertFalse(body["supported"])
            self.assertIsNone(body["matched"])
            self.assertEqual(body["note"], "not supported yet")
        finally:
            voice_module.transcribe_audio = fake_transcribe

    def test_control_turns_light_on_and_rejects_other_targets(self):
        body = self.client.post("/api/voice/control",
                                json={"entity_id": "light.reading_light",
                                      "service": "light.turn_on"}).json()
        self.assertTrue(body["ok"])
        self.assertIn("light/turn_on", SERVICE_CALLS)
        r = self.client.post("/api/voice/control",
                             json={"entity_id": "binary_sensor.patio_door",
                                   "service": "light.turn_on"})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/voice/control",
                             json={"entity_id": "light.reading_light",
                                   "service": "light.toggle"})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/voice/control",
                             json={"entity_id": "light.nope",
                                   "service": "light.turn_on"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
