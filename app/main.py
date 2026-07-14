from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.auth import require_api_key, resolve_api_key
from app.cache import get_cached_url, get_redis_client, set_cached_url
from app.models import get_engine, get_session_factory, init_db
from app.ratelimit import check_and_increment
from app.service import create_link, get_stats, increment_click_count, resolve_link

_engine = get_engine()
_session_factory = get_session_factory(_engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(_engine)
    # Route handlers here are synchronous (def, not async def) because the
    # DB driver (psycopg2) and redis-py client are both blocking. FastAPI
    # runs sync handlers through a bounded worker thread pool -- anyio's
    # default is 40 threads. Under load testing, throughput plateaued and
    # latency rose sharply exactly once concurrency exceeded that default,
    # which is what led to finding this rather than guessing at it (see
    # README for the before/after numbers). Raising it here is the direct
    # fix; the more thorough fix would be switching to async DB/Redis
    # clients so requests don't need a dedicated OS thread each -- noted
    # as a known next step, not implemented in this version.
    import anyio.to_thread
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = 200
    # This alone doesn't fully fix high-concurrency throughput -- see
    # README's load test section. The deeper, second bottleneck is
    # SQLAlchemy's default connection pool (5 + 10 overflow = 15 total DB
    # connections), verified directly against engine.pool rather than
    # assumed. Not raised here because pool size has to be tuned against
    # Postgres's own max_connections, not set arbitrarily high client-side.
    yield


app = FastAPI(title="URL Shortener", lifespan=lifespan)


def get_db():
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def get_redis():
    return get_redis_client()


CREATE_LINK_RATE_LIMIT_PER_MINUTE = 20


class CreateLinkRequest(BaseModel):
    long_url: HttpUrl


class CreateLinkResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str


class StatsResponse(BaseModel):
    short_code: str
    long_url: str
    click_count: int


@app.post("/links", response_model=CreateLinkResponse, status_code=201)
def create_link_endpoint(
    request: CreateLinkRequest,
    x_api_key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
    redis_client=Depends(get_redis),
):
    api_key = resolve_api_key(db, x_api_key)

    allowed = check_and_increment(redis_client, x_api_key, CREATE_LINK_RATE_LIMIT_PER_MINUTE)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"rate limit exceeded: max {CREATE_LINK_RATE_LIMIT_PER_MINUTE} link creations per minute",
        )

    result = create_link(db, str(request.long_url), api_key.id)
    return CreateLinkResponse(
        short_code=result.short_code,
        short_url=f"/{result.short_code}",
        long_url=result.long_url,
    )


@app.get("/{short_code}")
def redirect_endpoint(
    short_code: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    redis_client=Depends(get_redis),
):
    cached_url = get_cached_url(redis_client, short_code)
    if cached_url:
        background_tasks.add_task(increment_click_count, db, short_code)
        response = RedirectResponse(url=cached_url, status_code=307)
        response.headers["X-Cache"] = "HIT"
        return response

    link = resolve_link(db, short_code)
    if not link:
        raise HTTPException(status_code=404, detail="short link not found")

    set_cached_url(redis_client, short_code, link.long_url)
    background_tasks.add_task(increment_click_count, db, short_code)
    response = RedirectResponse(url=link.long_url, status_code=307)
    response.headers["X-Cache"] = "MISS"
    return response


@app.get("/links/{short_code}/stats", response_model=StatsResponse)
def stats_endpoint(
    short_code: str,
    x_api_key: str = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    api_key = resolve_api_key(db, x_api_key)
    link = get_stats(db, short_code)
    if not link:
        raise HTTPException(status_code=404, detail="short link not found")
    if link.owner_api_key_id != api_key.id:
        raise HTTPException(status_code=403, detail="you do not own this link")
    return StatsResponse(short_code=short_code, long_url=link.long_url, click_count=link.click_count)
