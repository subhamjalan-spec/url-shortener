"""Fixed-window rate limiter, backed by Redis. Uses a distinctly prefixed
key space ("ratelimit:") from the cache ("cache:") -- same Redis instance,
never-colliding key spaces, verified in tests/test_cache.py.

Known, honest limitation: fixed-window counters allow a burst of up to
2x the limit right at a window boundary (e.g. a client could send the
full limit at 0:59 and another full limit at 1:00, all within 1 second).
A sliding-window-log or token-bucket algorithm would fix this; not
implemented here since it's a documented tradeoff of the simpler
approach, not an oversight.
"""
import time

import redis


def rate_limit_key(api_key: str) -> str:
    window = int(time.time()) // 60  # 1-minute fixed windows
    return f"ratelimit:{api_key}:{window}"


def check_and_increment(client: redis.Redis, api_key: str, limit_per_minute: int) -> bool:
    """Returns True if the request is allowed, False if the limit is
    exceeded. Increments the counter as a side effect of checking --
    every call counts, including the one that gets rejected, matching
    how real rate limiters behave (rejected requests still cost quota
    in most real systems, to prevent a retry storm from being free)."""
    key = rate_limit_key(api_key)
    count = client.incr(key)
    if count == 1:
        client.expire(key, 60)  # only set TTL on the first request in this window
    return count <= limit_per_minute
