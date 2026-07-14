![CI](https://github.com/subhamjalan-spec/url-shortener/actions/workflows/ci.yml/badge.svg)
<!-- Replace YOUR_USERNAME/YOUR_REPO once pushed, or the badge will be broken. -->

# URL Shortener (FastAPI, PostgreSQL, Redis)

A backend service demonstrating REST API design, database schema design,
caching, rate limiting, and authorization -- the day-to-day SWE toolkit
that the matching engine and Raft KV store (both low-level C++ systems
projects) intentionally don't cover.

## The one deliberately hard part: short code generation

Every link's public code is a **base62 encoding of its own database
auto-increment ID** (`app/base62.py`). This is a genuine bijection --
every ID maps to exactly one code and back -- so collisions are
structurally impossible, not just checked for and retried. The naive
approach (generate a random string, query if it's taken, retry on
collision) works but adds an avoidable database round-trip on every
single link creation; this approach doesn't need it. Tested in complete
isolation (`tests/test_base62.py`) before any DB or API code touched it,
including a test that 5,000 sequential IDs never produce the same code.

## Architecture

**Read path**: a redirect request checks Redis first; only on a genuine
cache miss does it query Postgres. This matters because a URL shortener
is read-heavy -- a link is created once and clicked many times, so the
hot path should almost never touch the database.

**Two independent uses of the same Redis instance**, kept in distinctly
prefixed key spaces (`cache:` vs `ratelimit:`) so they can never collide
-- verified directly with a test (`test_cache_and_ratelimit_keys_never_collide`),
not just assumed from the naming convention.

**Rate limiting**: a real Redis-backed fixed-window counter on link
creation (20/minute per API key). Verified by actually sending 25 real
requests over HTTP and confirming exactly 20 succeed and 5 return 429 --
not by reading the code and assuming it's wired correctly.

**Authorization, not just authentication**: the stats endpoint checks
both "is this a valid API key" AND "does this key actually own this
link" -- a different, valid key gets a 403, not just anyone with any key
seeing anyone's data. Directly tested (`test_stats_requires_ownership_not_just_auth`).

**Click tracking runs off the hot path**: incrementing a link's click
count happens via a FastAPI `BackgroundTask`, after the redirect response
has already been sent -- a slow analytics write should never make a user
wait longer for their redirect.

## A real, diagnosed performance bottleneck (found by actually load testing)

The hand-rolled load tester (`loadtest/run.py`, same "measure it, don't
estimate it" philosophy as the matching engine's benchmark) surfaced a
genuine problem: latency got *worse*, not better, as concurrency
increased.

**First measurement** (before any fix):
```
concurrency=10:  122 req/s,  p50=68ms
concurrency=50:   74 req/s,  p50=629ms
concurrency=100:  96 req/s,  p50=972ms
```

**Root cause, layer 1 (verified, not guessed):** route handlers here are
synchronous (`def`, not `async def`) because the Postgres driver
(psycopg2) and redis-py client are both blocking calls. FastAPI runs sync
handlers through a bounded worker thread pool. Checked the actual default
directly:
```python
>>> anyio.to_thread.current_default_thread_limiter().total_tokens
40
```
Concurrency above 40 means requests queue for a free thread -- which
lines up exactly with where latency started climbing above.

**Fix attempted:** raised the thread pool to 200 tokens at startup
(`app/main.py`). Re-measured:
```
concurrency=50:   97 req/s,  p50=392ms   (was 629ms -- real improvement)
concurrency=100:  88 req/s,  p50=1062ms  (barely changed)
```

**Root cause, layer 2 (also verified, not guessed):** concurrency=50
improved but concurrency=100 didn't, which means something else caps out
around there. Checked SQLAlchemy's actual connection pool directly:
```python
>>> engine.pool.size()
5
>>> engine.pool._max_overflow
10
```
15 total database connections available, regardless of how many threads
are free to run. That's the real ceiling at high concurrency here, not
the thread pool.

**Why this is written up instead of just fixed and hidden:** this is the
same category of finding as the matching engine's single-mutex bottleneck
-- a real, load-test-discovered limitation, explained precisely rather
than glossed over. The correct next step (switching to an async DB driver
like `asyncpg` and an async Redis client, so requests stop needing a
dedicated OS thread and connection each) is a real architectural change,
not a config tweak, so it's named here as the next step rather than
rushed in.

## Build & run

```bash
python3 -m venv venv
./venv/bin/pip install fastapi uvicorn "sqlalchemy>=2.0" psycopg2-binary redis pydantic pytest httpx pytest-asyncio
```

Requires PostgreSQL and Redis running locally:

```bash
sudo service postgresql start
sudo -u postgres psql -c "CREATE USER urlshort WITH PASSWORD 'urlshort_dev' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE urlshortener OWNER urlshort;"
redis-server --daemonize yes --port 6379

./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Interactive API docs (auto-generated by FastAPI): `http://127.0.0.1:8000/docs`

## Test suite

```
tests/test_base62.py               7/7  -- pure encoding logic, no I/O
tests/test_service.py              6/6  -- against the real running Postgres
tests/test_cache_and_ratelimit.py  7/7  -- against the real running Redis
tests/test_api_integration.py      7/7  -- full HTTP stack via FastAPI's TestClient
```
**27/27 passing**, all against real infrastructure -- no mocked DB, no
mocked Redis.
```bash
./venv/bin/python -m pytest tests/ -v
```

## Load test

```bash
./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &
./venv/bin/python loadtest/run.py
```

Real captured output (concurrency=10):
```
=== Load test: 500 requests, concurrency=10 ===
Total time:   4.112s
Throughput:   122 requests/sec
Latency p50:  68.50 ms
Latency p99:  239.43 ms
```

## Known limitations (stated plainly)

- **Synchronous DB/Redis clients** cap real concurrent throughput, as
  diagnosed above. An async rewrite (asyncpg + redis.asyncio) is the
  correct fix, not implemented in this version.
- **Fixed-window rate limiting** allows a burst of up to 2x the limit
  right at a window boundary. A sliding-window-log or token-bucket
  algorithm would close this; documented tradeoff, not an oversight.
- **No IP-based rate limiting on the public redirect endpoint** -- only
  the authenticated create-link endpoint is rate limited.
- **Migrations via `create_all`**, not Alembic -- fine for this scope,
  not how a real production schema would be evolved over time.

## Layout

```
app/         base62.py, models.py, service.py, cache.py, ratelimit.py,
             auth.py, main.py (FastAPI routes)
tests/       one file per layer, each testing against real infrastructure
loadtest/    hand-rolled async load tester
```
