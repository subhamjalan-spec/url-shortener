import pytest

from app.cache import cache_key, get_cached_url, get_redis_client, invalidate_cache, set_cached_url
from app.ratelimit import check_and_increment, rate_limit_key


@pytest.fixture
def redis_client():
    client = get_redis_client()
    yield client
    for key in client.keys("cache:link:test-*"):
        client.delete(key)
    for key in client.keys("ratelimit:test-*"):
        client.delete(key)


def test_cache_miss_returns_none(redis_client):
    assert get_cached_url(redis_client, "test-nonexistent") is None


def test_cache_set_and_get_round_trips(redis_client):
    set_cached_url(redis_client, "test-abc", "https://example.com/cached")
    assert get_cached_url(redis_client, "test-abc") == "https://example.com/cached"


def test_cache_invalidate_actually_removes_it(redis_client):
    set_cached_url(redis_client, "test-xyz", "https://example.com/x")
    invalidate_cache(redis_client, "test-xyz")
    assert get_cached_url(redis_client, "test-xyz") is None


def test_rate_limit_allows_up_to_the_limit(redis_client):
    key = "test-key-rl-1"
    for i in range(5):
        allowed = check_and_increment(redis_client, key, limit_per_minute=5)
        assert allowed is True, f"request {i+1} should be allowed within a limit of 5"


def test_rate_limit_actually_blocks_over_the_limit(redis_client):
    # The test that actually proves the rate limiter works -- sending
    # real requests until the limit is genuinely exceeded, not just
    # reading the code and assuming it's correct.
    key = "test-key-rl-2"
    for _ in range(3):
        check_and_increment(redis_client, key, limit_per_minute=3)
    blocked = check_and_increment(redis_client, key, limit_per_minute=3)
    assert blocked is False, "4th request within the same window must be rejected"


def test_cache_and_ratelimit_keys_never_collide(redis_client):
    # Directly verifies the risk flagged in tasks/todo.md: cache and rate
    # limit share one Redis instance, so their key prefixes must never
    # produce the same literal key for the same identifier.
    same_identifier = "test-shared-identifier"
    c_key = cache_key(same_identifier)
    r_key = rate_limit_key(same_identifier)
    assert c_key != r_key
    assert c_key.startswith("cache:")
    assert r_key.startswith("ratelimit:")


def test_rate_limit_window_carries_a_ttl(redis_client):
    key = "test-key-rl-ttl"
    check_and_increment(redis_client, key, limit_per_minute=10)
    ttl = redis_client.ttl(rate_limit_key(key))
    assert 0 < ttl <= 60
