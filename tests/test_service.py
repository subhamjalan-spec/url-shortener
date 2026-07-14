import pytest

from app.models import ApiKey, Link, get_engine, get_session_factory, init_db
from app.service import create_link, get_stats, increment_click_count, resolve_link


@pytest.fixture
def db_session():
    engine = get_engine()
    init_db(engine)
    Session = get_session_factory(engine)
    session = Session()
    api_key = ApiKey(key=f"test-key-{id(session)}", owner_name="pytest")
    session.add(api_key)
    session.commit()
    session.refresh(api_key)
    yield session, api_key.id
    # Clean up rows created by this test so runs don't pile up on the real DB.
    session.query(Link).filter_by(owner_api_key_id=api_key.id).delete()
    session.query(ApiKey).filter_by(id=api_key.id).delete()
    session.commit()
    session.close()


def test_create_link_returns_a_short_code(db_session):
    session, api_key_id = db_session
    result = create_link(session, "https://example.com/some/long/path", api_key_id)
    assert result.short_code
    assert result.long_url == "https://example.com/some/long/path"


def test_resolve_link_returns_the_original_url(db_session):
    session, api_key_id = db_session
    created = create_link(session, "https://example.com/page", api_key_id)
    link = resolve_link(session, created.short_code)
    assert link is not None
    assert link.long_url == "https://example.com/page"


def test_resolve_unknown_code_returns_none_not_error(db_session):
    session, _ = db_session
    assert resolve_link(session, "ZZZZZZ") is None


def test_resolve_malformed_code_returns_none_not_crash(db_session):
    session, _ = db_session
    assert resolve_link(session, "not valid! chars") is None


def test_click_count_starts_at_zero_and_increments(db_session):
    session, api_key_id = db_session
    created = create_link(session, "https://example.com/x", api_key_id)
    link = resolve_link(session, created.short_code)
    assert link.click_count == 0

    increment_click_count(session, created.short_code)
    increment_click_count(session, created.short_code)

    stats = get_stats(session, created.short_code)
    assert stats.click_count == 2


def test_different_links_get_different_codes(db_session):
    session, api_key_id = db_session
    a = create_link(session, "https://example.com/a", api_key_id)
    b = create_link(session, "https://example.com/b", api_key_id)
    assert a.short_code != b.short_code
