import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.models import ApiKey, get_engine, get_session_factory, init_db

client = TestClient(app)


def make_api_key() -> str:
    """Creates a fresh, unique API key per test so rate-limit state and
    ownership checks never bleed across tests sharing the same Redis/DB."""
    engine = get_engine()
    init_db(engine)
    Session = get_session_factory(engine)
    key = f"test-{uuid.uuid4().hex[:12]}"
    with Session() as s:
        s.add(ApiKey(key=key, owner_name="pytest"))
        s.commit()
    return key


def test_create_link_and_full_redirect_flow():
    key = make_api_key()
    resp = client.post("/links", headers={"X-API-Key": key},
                        json={"long_url": "https://example.com/full-flow-test"})
    assert resp.status_code == 201
    short_code = resp.json()["short_code"]

    r1 = client.get(f"/{short_code}", follow_redirects=False)
    assert r1.status_code == 307
    assert r1.headers["location"] == "https://example.com/full-flow-test"
    assert r1.headers["x-cache"] == "MISS"

    r2 = client.get(f"/{short_code}", follow_redirects=False)
    assert r2.status_code == 307
    assert r2.headers["location"] == "https://example.com/full-flow-test"
    assert r2.headers["x-cache"] == "HIT"


def test_missing_api_key_is_rejected():
    resp = client.post("/links", json={"long_url": "https://example.com"})
    assert resp.status_code == 422  # FastAPI's own required-header validation


def test_invalid_api_key_is_rejected():
    resp = client.post("/links", headers={"X-API-Key": "not-a-real-key"},
                        json={"long_url": "https://example.com"})
    assert resp.status_code == 401


def test_unknown_short_code_returns_404():
    resp = client.get("/ZZZZZZZZ", follow_redirects=False)
    assert resp.status_code == 404


def test_stats_requires_ownership_not_just_auth():
    owner_key = make_api_key()
    other_key = make_api_key()

    created = client.post("/links", headers={"X-API-Key": owner_key},
                           json={"long_url": "https://example.com/owned"})
    short_code = created.json()["short_code"]

    denied = client.get(f"/links/{short_code}/stats", headers={"X-API-Key": other_key})
    assert denied.status_code == 403

    allowed = client.get(f"/links/{short_code}/stats", headers={"X-API-Key": owner_key})
    assert allowed.status_code == 200
    assert allowed.json()["long_url"] == "https://example.com/owned"


def test_click_count_increments_after_redirects():
    key = make_api_key()
    created = client.post("/links", headers={"X-API-Key": key},
                           json={"long_url": "https://example.com/click-count-test"})
    short_code = created.json()["short_code"]

    client.get(f"/{short_code}", follow_redirects=False)
    client.get(f"/{short_code}", follow_redirects=False)
    client.get(f"/{short_code}", follow_redirects=False)

    stats = client.get(f"/links/{short_code}/stats", headers={"X-API-Key": key})
    assert stats.json()["click_count"] == 3


def test_rate_limit_actually_returns_429_over_http():
    key = make_api_key()
    statuses = []
    for i in range(25):
        resp = client.post("/links", headers={"X-API-Key": key},
                            json={"long_url": f"https://example.com/rl-{i}"})
        statuses.append(resp.status_code)
    assert statuses.count(201) == 20
    assert statuses.count(429) == 5
