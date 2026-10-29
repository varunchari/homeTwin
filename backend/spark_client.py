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
BASETEN_BASE_URL = "https://inference.baseten.co/v1"


def open_provider_config() -> tuple[str, str, str]:
    """Baseten open-weight config, from host env only — never hard-coded.

    The exact model string must come from the Baseten dashboard
    (BASETEN_MODEL). An unverified dated label from an email is not a
    safe default, so a missing value is a configuration error, not a
    silent fallback to a possibly wrong model id. Returns
    (api_base, model, api_key).
    """
    api_key = os.environ.get("BASETEN_API_KEY", "")
    if not api_key:
        raise SparkError("BASETEN_API_KEY is not configured on the host")
    model = os.environ.get("BASETEN_MODEL", "")
    if not model:
        raise SparkError(
            "BASETEN_MODEL is not configured on the host — set it to the "
            "exact model string shown in the Baseten dashboard")
    return BASETEN_BASE_URL, model, api_key


class SparkError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MODEL_API_KEY", "")
    if not key:
        raise SparkError("MODEL_API_KEY is not configured")
    return key


async def complete_json(system: str, user: str, schema: dict,
                        model: str = SPARK_MODEL,
                        api_base: str | None = None,
                        api_key: str | None = None) -> dict:
    """One chat completion constrained to `schema`. Returns parsed JSON.

    `api_base`/`api_key` override the Meta Model API defaults — the Baseten
    A/B path passes the open-weight endpoint here. Same prompt, same schema.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=api_base or SPARK_BASE_URL,
                         api_key=api_key or _api_key())
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
