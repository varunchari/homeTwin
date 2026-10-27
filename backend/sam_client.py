"""Hosted SAM 3.1 client (Meta Model API, Day 2).

Contract (Meta docs: dev.meta.ai/docs/sam/segmenting):
- OpenAI-compatible Responses API streaming, ``model="sam-3.1"``.
- One short noun phrase per request + one image (base64 data URL).
- Output text stream carries boxes + encoded masks; decoded here with
  ``meta-sam-parser`` (image format).
- Text prompts only on the hosted API (no point/box prompts for P0).

Raises ``SamError`` on any failure so callers can fall back to the
manual-region path. Every call is timed by the caller for the evidence log.
"""

from __future__ import annotations

import base64
import os

SAM_BASE_URL = "https://api.meta.ai/v1"
SAM_MODEL = os.environ.get("SAM_MODEL", "sam-3.1")


class SamError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MODEL_API_KEY", "")
    if not key:
        raise SamError("MODEL_API_KEY is not configured")
    return key


def image_data_url(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64," + base64.b64encode(image_bytes).decode()


async def segment_image(image_bytes: bytes, phrase: str) -> list[dict]:
    """Segment one concept phrase. Returns [{object_id, bbox, mask_png}]."""
    from openai import AsyncOpenAI
    from meta_sam_parser import (
        decode_mask_to_raster,
        image_segmentation_format,
        parse_responses_stream,
    )

    phrase = " ".join(phrase.split())
    if not phrase:
        raise SamError("empty concept phrase")
    client = AsyncOpenAI(base_url=SAM_BASE_URL, api_key=_api_key())
    data_url = image_data_url(image_bytes)
    try:
        async with client.responses.stream(
            model=SAM_MODEL,
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": phrase},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        ) as stream:
            parsed = parse_responses_stream(stream, image_segmentation_format())
            result = await parsed.final_result()
    except SamError:
        raise
    except Exception as e:
        raise SamError(f"SAM request failed: {type(e).__name__}: {e}") from e
    finally:
        await client.close()

    records = getattr(result, "records", []) or []
    out = []
    for i, rec in enumerate(records):
        kind = getattr(rec, "kind", "")
        if kind == "box":
            out.append({
                "object_id": getattr(rec, "object_id", None) or f"obj-{i}",
                "bbox": (rec.left, rec.top, rec.right, rec.bottom),
                "mask_png": None,
            })
        elif kind == "mask":
            mask = getattr(rec, "mask", None)
            bounds = getattr(rec, "bounds", None)
            out.append({
                "object_id": getattr(rec, "object_id", None) or f"obj-{i}",
                "bbox": (
                    (bounds.left, bounds.top, bounds.right, bounds.bottom)
                    if bounds is not None else None
                ),
                "mask_png": decode_mask_to_raster(mask) if mask is not None else None,
            })
    return out
