"""Public-demo rate limiting for model-costly endpoints only.

The demo is a single shared Lightsail instance with a public URL, and
every model call spends real credits (SAM, Spark, Muse Image,
Transcribe). Tap, bind, What-If, approve and reset are local HA
operations and are NOT limited, so a rate-limited visitor can still
run the demo's non-model steps and retry the model step later.

Limits are per client address, in memory, with a sliding window.
Behind Caddy the direct peer is the proxy, so the real address is
taken from X-Forwarded-For when present (Caddy sets it), falling
back to the direct peer. This is a demo guard, not authentication:
it slows accidental or casual abuse, it does not stop a determined
attacker, and it is deliberately generous so a judge clicking
through the full demo in one sitting never hits it in normal use.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

MODEL_RATE_LIMIT = int(os.environ.get("MODEL_RATE_LIMIT_PER_10MIN", "30"))
MODEL_RATE_WINDOW_S = int(os.environ.get("MODEL_RATE_WINDOW_S", "600"))

# ip -> timestamps (seconds) of allowed model calls, oldest first.
_buckets: dict[str, deque] = defaultdict(deque)


def client_ip(request) -> str:
    """Best-effort client address for rate limiting."""
    forwarded = request.headers.get("x-forwarded-for") if request else None
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    return getattr(client, "host", "unknown") if client else "unknown"


def check_model_rate(ip: str, now: float | None = None,
                     limit: int = MODEL_RATE_LIMIT,
                     window_s: int = MODEL_RATE_WINDOW_S) -> bool:
    """Return True if this model call is allowed, False if limited.
    Only allowed calls consume budget; rejected calls do not."""
    now = time.time() if now is None else now
    bucket = _buckets[ip]
    while bucket and bucket[0] <= now - window_s:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def reset_model_rate() -> None:
    """Test helper: clear all buckets."""
    _buckets.clear()
