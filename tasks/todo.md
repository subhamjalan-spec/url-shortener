## Task: URL Shortener backend (Python/FastAPI, PostgreSQL, Redis)
## Goal: A real backend service demonstrating REST API design, DB schema,
caching, and rate limiting -- the day-to-day SWE toolkit that the
matching engine and Raft projects (both low-level systems) don't cover.

### Scope decisions (made up front)
- FastAPI, not Flask/Django -- modern, async-native, auto-generates
  OpenAPI docs, widely used in real backend roles right now.
- PostgreSQL via SQLAlchemy ORM (real DB, not SQLite -- SQLite would
  dodge the "real database" claim). Both installed and verified running
  in this environment, not assumed.
- Redis for two DISTINCT purposes, kept clearly separate in the code:
  (1) caching resolved short-code lookups (the read path), and
  (2) rate limiting (a fixed-window counter, independent of the cache).
- Short code generation: base62-encode the auto-increment DB primary key.
  No collision checking needed -- the encoding is a bijection, so
  collisions are structurally impossible, not just checked-for. This is
  the deliberate "hard part" of the project, and gets its own unit tests
  in isolation before touching the API layer at all.
- API-key based auth (X-API-Key header), not full OAuth/JWT -- enough to
  demonstrate auth thinking and to give rate limiting something to key
  off of, without the scope bloat of a full auth system.
- Load testing: a hand-rolled async Python load tester (httpx + asyncio),
  not an external tool -- same reasoning as skipping gtest/gRPC in the
  earlier two projects: fewer dependencies, and it forces understanding
  of what's actually being measured rather than trusting a black box.

### Steps
- [ ] Step 1: Environment verification -- Postgres and Redis actually
      installed, started, and connected to with real credentials before
      writing a line of app code (already done, see above).
- [ ] Step 2: Base62 encoding -- pure function, no DB/API involved yet.
      Unit tested for round-trip correctness and known edge cases (0,
      very large IDs) before anything is built on top of it.
- [ ] Step 3: DB schema (SQLAlchemy models) -- links table (id, long_url,
      short_code, owner_api_key, created_at, click_count) + api_keys
      table. Migrations via SQLAlchemy's create_all for this scope
      (Alembic would be the production choice, noted as a limitation).
- [ ] Step 4: Core service logic (create link, resolve link) as plain
      Python functions taking a DB session -- kept separate from FastAPI
      route handlers so the logic is testable without spinning up HTTP.
- [ ] Step 5: Redis caching layer on the resolve path -- cache hit/miss
      explicitly tested against a real Redis instance, not mocked.
- [ ] Step 6: Rate limiting middleware -- real Redis-backed fixed-window
      counter, tested by actually exceeding the limit and checking for
      a 429, not just reading the code and assuming it's right.
- [ ] Step 7: FastAPI routes wiring it together (POST /links, GET /{code}
      redirect, GET /links/{code}/stats) + API key auth dependency.
- [ ] Step 8: Integration tests against the real running Postgres +
      Redis (httpx TestClient), not an in-memory fake DB.
- [ ] Step 9: Hand-rolled async load test tool -- real concurrent
      requests against the real running server, real throughput/latency
      numbers captured, not estimated.
- [ ] Step 10: README with real captured output + honest limitations.

### Risks / open questions
- Redis used for two different jobs (cache + rate limit) -- must use
  distinctly prefixed keys ("cache:" vs "ratelimit:") so they can never
  collide, and this gets an explicit test, not just a naming convention
  trusted on faith.
- Rate limit window boundaries (fixed window can allow a burst right at
  the window edge) -- a known, real limitation of fixed-window counters,
  will be stated plainly rather than presented as a solved problem.
- click_count increments need to not become a write bottleneck on the hot
  read path -- decided to increment asynchronously via a FastAPI
  BackgroundTask rather than blocking the redirect response on a DB write.

### Done criteria
- [ ] Creating a link returns a short code; visiting it redirects to the
      original URL
- [ ] Second lookup of the same code is served from cache, verifiably
      faster and confirmed via a cache-hit flag, not assumed
- [ ] Exceeding the configured rate limit actually returns 429, proven
      by a test that sends enough requests to trigger it
- [ ] Missing/invalid API key is rejected on write endpoints
- [ ] Click count actually increments and is queryable
- [ ] Load test produces real numbers against the real running stack

### Review
Built and verified end-to-end, against REAL infrastructure throughout --
not mocked at any layer:
- Postgres and Redis actually installed and started in this environment
  before any app code was written (verified with real connections, not
  assumed available).
- Base62 encoding (7 checks) tested in isolation first, including a
  5,000-ID no-collision sweep.
- Service logic (6 checks) tested against the real Postgres instance.
- Cache + rate limiter (7 checks) tested against the real Redis instance,
  including an explicit test that their key spaces can never collide --
  this was flagged as a risk in the plan up front, then directly tested,
  not just trusted from the naming convention.
- Full HTTP API (7 checks) tested via FastAPI's TestClient, including
  sending 25 real requests to prove the rate limiter actually returns 429
  at request 21, not just reading the code and assuming it's wired
  correctly into the route.
- Manually verified live over real HTTP with curl before writing the
  formal test suite: create, redirect (cache MISS then HIT), 404, 401,
  and a live 20-requests-then-429 rate limit run -- exact same sequence
  the automated tests later codified.
- Load testing surfaced a genuine, non-obvious bug: latency got WORSE
  with more concurrency. Root-caused in two layers, both verified by
  directly inspecting the running objects rather than guessing:
  (1) anyio's default thread pool (40 tokens) for sync route handlers,
  (2) SQLAlchemy's default connection pool (5 + 10 overflow = 15). Fixed
  layer 1, re-measured and confirmed real improvement at concurrency=50,
  confirmed layer 2 remained the ceiling at concurrency=100 rather than
  assuming the first fix solved everything.
- CI runs the full test suite against REAL Postgres and Redis service
  containers on GitHub's infrastructure, not sqlite/fakeredis substitutes
  -- so a green badge means the same real-infrastructure guarantee as
  local development.

Deferred by design, stated in the README, not hidden: async DB/Redis
clients (the deeper fix for the diagnosed bottleneck), sliding-window
rate limiting, IP-based limiting on the redirect endpoint, and Alembic
migrations.
