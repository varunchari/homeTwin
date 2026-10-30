"""Muse Image client (Meta Model API).

Model: muse-image-1.0 via https://api.meta.ai/v1, $0.01/image.
Endpoints follow the OpenAI-compatible image API:
- POST /v1/images/generations — text prompt in, image out.
- POST /v1/images/edits — prompt plus an input image, image out.

The calls use httpx directly (not the OpenAI SDK's image resource) so
the request shape is explicit and testable. Responses are expected in
the OpenAI image shape: data[0].b64_json (preferred) or data[0].url.
Any other shape raises ImageError — the UI must show that failure,
never a placeholder picture presented as a Muse Image preview.
"""

from __future__ import annotations

import base64
import os

IMAGE_BASE_URL = "https://api.meta.ai/v1"
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "muse-image-1.0")


class ImageError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MODEL_API_KEY", "")
    if not key:
        raise ImageError("MODEL_API_KEY is not configured")
    return key


def _extract_image_bytes(payload: dict) -> bytes:
    import httpx

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        raise ImageError(f"Image API returned an unexpected shape: {sorted(payload) if isinstance(payload, dict) else type(payload).__name__}")
    first = data[0] or {}
    if first.get("b64_json"):
        try:
            return base64.b64decode(first["b64_json"])
        except Exception as e:
            raise ImageError(f"Image API returned undecodable image data: {e}") from e
    if first.get("url"):
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(first["url"])
            if resp.status_code != 200:
                raise ImageError(f"Image download failed: {resp.status_code}")
            return resp.content
        except ImageError:
            raise
        except Exception as e:
            raise ImageError(f"Image download failed: {type(e).__name__}: {e}") from e
    raise ImageError(f"Image API returned no image data (keys: {sorted(first)})")


async def generate_image(prompt: str) -> bytes:
    """Text-to-image preview. Raises ImageError on any failure."""
    import httpx

    if not prompt.strip():
        raise ImageError("empty image prompt")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{IMAGE_BASE_URL}/images/generations",
                headers={"Authorization": f"Bearer {_api_key()}",
                         "Content-Type": "application/json"},
                json={"model": IMAGE_MODEL, "prompt": prompt})
    except ImageError:
        raise
    except Exception as e:
        raise ImageError(f"Image generation failed: {type(e).__name__}: {e}") from e
    if resp.status_code != 200:
        raise ImageError(f"Image generation failed: {resp.status_code}: {resp.text[:200]}")
    try:
        return _extract_image_bytes(resp.json())
    except ImageError:
        raise
    except Exception as e:
        raise ImageError(f"Image generation returned unreadable JSON: {e}") from e


async def edit_image(image_bytes: bytes, prompt: str) -> bytes:
    """Image-to-image edit of the given room photo. Raises on failure."""
    import httpx

    if not image_bytes:
        raise ImageError("empty input image")
    if not prompt.strip():
        raise ImageError("empty image prompt")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{IMAGE_BASE_URL}/images/edits",
                headers={"Authorization": f"Bearer {_api_key()}"},
                files={"image": ("room.jpg", image_bytes, "image/jpeg")},
                data={"model": IMAGE_MODEL, "prompt": prompt})
    except ImageError:
        raise
    except Exception as e:
        raise ImageError(f"Image edit failed: {type(e).__name__}: {e}") from e
    if resp.status_code != 200:
        raise ImageError(f"Image edit failed: {resp.status_code}: {resp.text[:200]}")
    try:
        return _extract_image_bytes(resp.json())
    except ImageError:
        raise
    except Exception as e:
        raise ImageError(f"Image edit returned unreadable JSON: {e}") from e
