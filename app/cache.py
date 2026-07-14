"""Caching layer for resolved links. Uses a distinctly prefixed key space
("cache:") so it can never collide with the rate limiter's keys
("ratelimit:"), which share the same Redis instance -- see app/ratelimit.py.
This separation is tested explicitly in tests/test_cache.py, not just
assumed from the naming convention.
"""
import redis

CACHE_TTL_SECONDS = 300


def get_redis_client() -> redis.Redis:
    return redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)


def cache_key(short_code: str) -> str:
    return f"cache:link:{short_code}"


def get_cached_url(client: redis.Redis, short_code: str):
    return client.get(cache_key(short_code))


def set_cached_url(client: redis.Redis, short_code: str, long_url: str) -> None:
    client.set(cache_key(short_code), long_url, ex=CACHE_TTL_SECONDS)


def invalidate_cache(client: redis.Redis, short_code: str) -> None:
    client.delete(cache_key(short_code))
