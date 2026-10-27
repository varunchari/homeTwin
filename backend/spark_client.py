"""Minimal Muse Spark client (Meta Model API, Chat Completions).

Used for model-driven matching (auto-binding) now and AutomationIR on Day 4.
Constrained JSON output via response_format=json_schema. Raises SparkError
on any failure. Timed and logged by callers for the evidence log.
"""

from __future__ import annotations

import json
import os

SPARK_BASE_URL = "https://api.meta.ai/v1"
SPARK_MODEL = os.environ.get("SPARK_MODEL", "muse-spark-1.3")


class SparkError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MODEL_API_KEY", "")
    if not key:
        raise SparkError("MODEL_API_KEY is not configured")
    return key


async def complete_json(system: str, user: str, schema: dict,
                        model: str = SPARK_MODEL) -> dict:
    """One chat completion constrained to `schema`. Returns parsed JSON."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=SPARK_BASE_URL, api_key=_api_key())
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "hometwin_result", "schema": schema},
            },
        )
    except SparkError:
        raise
    except Exception as e:
        raise SparkError(f"Spark request failed: {type(e).__name__}: {e}") from e
    finally:
        await client.close()
    try:
        content = resp.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception as e:
        raise SparkError(f"Spark returned bad JSON: {e}") from e
