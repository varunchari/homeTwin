"""Voice: push-to-talk transcription into the existing typed pipeline.
Voice is a second input, never a second pipeline. A transcript that
matches one of the supported utterances below is either:
- copied into the Automate instruction box (automation patterns), so
  the user still reviews it and clicks Generate plan, then approves
  before any HA write, exactly as typed input does; or
- shown as an explicit direct-control button (tap-control), which
  the user clicks to turn a light on — the same live action as
  tapping a pin, not an automation.

Anything else returns "not supported yet" and is never executed.
There are no spoken replies: Voice Transcribe is speech-to-text
only. Audio is sent once for transcription and is not stored on
disk; only the transcript text is logged, for evidence.

Supported set, chosen per the mapping of 3 automation patterns plus
one tap-control utterance. The refined-plan query utterance
("are the patio lights on?") is deliberately not in the set: a
status question has no AutomationIR / approval / execute path, so
it cannot pass the exit test for this feature.
"""

from __future__ import annotations

import json
import os
import re

TRANSCRIBE_BASE_URL = "https://api.meta.ai/v1"
TRANSCRIBE_MODEL = os.environ.get("TRANSCRIBE_MODEL", "muse-voice-transcribe-1.0")


class TranscribeError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MODEL_API_KEY", "")
    if not key:
        raise TranscribeError("MODEL_API_KEY is not configured")
    return key


def extract_transcript(payload: dict) -> str:
    """Pull transcript text out of a Transcribe response, any shape."""
    if not isinstance(payload, dict):
        raise TranscribeError("Transcribe returned an unexpected response")
    for key in ("text", "transcript", "transcription"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("text") or value.get("transcript")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    for turn in payload.get("turns") or []:
        if isinstance(turn, dict):
            value = turn.get("text")
            if isinstance(value, str) and value.strip():
                return value.strip()
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0] or {}
        for key in ("text", "transcript"):
            value = first.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise TranscribeError(
        f"Transcribe returned no transcript text (keys: {sorted(payload)})")


def _require_wav(audio_bytes: bytes) -> None:
    if len(audio_bytes) < 16 or not audio_bytes.startswith(b"RIFF") \
            or b"WAVE" not in audio_bytes[8:16]:
        raise TranscribeError(
            "audio must be mono 16-bit WAV at 16 or 24 kHz "
            "(the browser converts recordings before upload)")


async def transcribe_audio(audio_bytes: bytes, mime: str = "audio/wav") -> str:
    """Transcribe one push-to-talk recording. Audio is never written
    to disk by this function; it is sent in memory only."""
    import httpx

    if not audio_bytes:
        raise TranscribeError("empty recording")
    _require_wav(audio_bytes)
    # The API requires two multipart parts: "request" (JSON incl. model
    # and audioEncoding) and "audio" (the recording). A single "file"
    # part is rejected, and only WAV is accepted for file uploads.
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{TRANSCRIBE_BASE_URL}/asr/transcribe",
                headers={"Authorization": f"Bearer {_api_key()}"},
                files={"audio": ("voice.wav", audio_bytes, "audio/wav")},
                data={"request": json.dumps({"model": TRANSCRIBE_MODEL,
                                             "audioEncoding": "WAV"})})
    except TranscribeError:
        raise
    except Exception as e:
        raise TranscribeError(f"Transcribe failed: {type(e).__name__}: {e}") from e
    if resp.status_code != 200:
        raise TranscribeError(
            f"Transcribe failed: {resp.status_code}: {resp.text[:200]}")
    try:
        return extract_transcript(resp.json())
    except TranscribeError:
        raise
    except Exception as e:
        raise TranscribeError(f"Transcribe returned unreadable JSON: {e}") from e


def normalize_transcript(text: str) -> str:
    """Lowercase, drop punctuation, collapse spaces. Exact-phrase
    matching on the result keeps the supported set closed."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


# Each entry: accepted normalized phrasings -> what the UI does next.
# Automation entries fill the Automate box (and its source/target
# dropdowns, from the bound entities); tap entries show a direct
# control button. Nothing here writes to HA on its own.
SUPPORTED_UTTERANCES = [
    {
        "key": "tap-reading-on",
        "kind": "tap-control",
        "examples": ["Turn the reading light on"],
        "phrasings": ["turn the reading light on", "turn on the reading light"],
        "entity_id": "light.reading_light",
        "service": "light.turn_on",
        "automate_text": None,
        "source_entity": None,
        "target_entity": None,
    },
    {
        "key": "pattern1-door-reading",
        "kind": "pattern1",
        "examples": ["When the door opens, turn the reading light on"],
        "phrasings": [
            "when the door opens turn the reading light on",
            "when the patio door opens turn the reading light on",
        ],
        "entity_id": None,
        "service": None,
        "automate_text": "when the door opens, turn the reading light on",
        "source_entity": "binary_sensor.patio_door",
        "target_entity": "light.reading_light",
    },
    {
        "key": "pattern2-sunset-string",
        "kind": "pattern2",
        "examples": ["When the door opens after sunset, turn the string lights on"],
        "phrasings": [
            "when the door opens after sunset turn the string lights on",
            "when the patio door opens after sunset turn the string lights on",
        ],
        "entity_id": None,
        "service": None,
        "automate_text": "when the door opens after sunset, turn the string lights on",
        "source_entity": "binary_sensor.patio_door",
        "target_entity": "light.string_lights",
    },
    {
        "key": "pattern3-delay-reading",
        "kind": "pattern3",
        "examples": ["When the door opens, turn the reading light on, off after a minute"],
        "phrasings": [
            "when the door opens turn the reading light on off after a minute",
            "when the patio door opens turn the reading light on off after a minute",
        ],
        "entity_id": None,
        "service": None,
        "automate_text": "when the door opens, turn the reading light on, off after a minute",
        "source_entity": "binary_sensor.patio_door",
        "target_entity": "light.reading_light",
    },
]


def match_utterance(transcript: str) -> dict | None:
    """Return the supported utterance for a transcript, or None."""
    normalized = normalize_transcript(transcript or "")
    for utterance in SUPPORTED_UTTERANCES:
        if normalized in utterance["phrasings"]:
            return utterance
    return None
