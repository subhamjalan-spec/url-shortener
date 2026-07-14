"""Hand-rolled async load tester, same philosophy as the matching engine's
benchmark.cpp: measure real numbers against the real running service, not
an estimate. No external load-testing tool (wrk/k6) -- this forces
understanding of what's actually being measured, and keeps the whole
project dependency-light, consistent with the other two.

Usage:
    python loadtest/run.py
"""
import asyncio
import sys
import time

import httpx

sys.path.insert(0, ".")

BASE_URL = "http://127.0.0.1:8000"
API_KEY = "loadtest-key"


async def setup_api_key():
    from app.models import ApiKey, get_engine, get_session_factory, init_db

    engine = get_engine()
    init_db(engine)
    Session = get_session_factory(engine)
    with Session() as s:
        existing = s.query(ApiKey).filter_by(key=API_KEY).first()
        if not existing:
            s.add(ApiKey(key=API_KEY, owner_name="loadtest"))
            s.commit()


async def create_test_link(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        f"{BASE_URL}/links",
        headers={"X-API-Key": API_KEY},
        json={"long_url": "https://example.com/loadtest-target"},
    )
    return resp.json()["short_code"]


async def hit_redirect(client: httpx.AsyncClient, short_code: str) -> float:
    start = time.perf_counter()
    await client.get(f"{BASE_URL}/{short_code}", follow_redirects=False)
    return (time.perf_counter() - start) * 1000  # ms


async def run_load_test(short_code: str, total_requests: int, concurrency: int):
    latencies_ms = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_hit():
            async with semaphore:
                latency = await hit_redirect(client, short_code)
                latencies_ms.append(latency)

        start = time.perf_counter()
        await asyncio.gather(*[bounded_hit() for _ in range(total_requests)])
        total_time = time.perf_counter() - start

    latencies_ms.sort()
    p50 = latencies_ms[len(latencies_ms) // 2]
    p99 = latencies_ms[int(len(latencies_ms) * 0.99)]
    throughput = total_requests / total_time

    print(f"=== Load test: {total_requests} requests, concurrency={concurrency} ===")
    print(f"Total time:   {total_time:.3f}s")
    print(f"Throughput:   {throughput:.0f} requests/sec")
    print(f"Latency p50:  {p50:.2f} ms")
    print(f"Latency p99:  {p99:.2f} ms")
    print(f"Latency max:  {max(latencies_ms):.2f} ms")
    print(f"Latency min:  {min(latencies_ms):.2f} ms")
    print()


async def main():
    await setup_api_key()
    async with httpx.AsyncClient(timeout=10.0) as client:
        short_code = await create_test_link(client)
        print(f"Created test link with short_code={short_code}\n")

    # This link gets hit repeatedly, so after the first request every
    # subsequent one is served from cache -- this measures the cache-hit
    # read path specifically, the realistic hot path for a read-heavy
    # service like a URL shortener.
    await run_load_test(short_code, total_requests=500, concurrency=10)
    await run_load_test(short_code, total_requests=500, concurrency=50)
    await run_load_test(short_code, total_requests=1000, concurrency=100)


if __name__ == "__main__":
    asyncio.run(main())
