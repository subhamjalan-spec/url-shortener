from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.base62 import decode, encode
from app.models import Link


@dataclass
class CreateLinkResult:
    short_code: str
    long_url: str


def create_link(session: Session, long_url: str, api_key_id: int) -> CreateLinkResult:
    """Creates a new link and returns its base62 short code.

    The short code is derived from the row's own auto-increment id AFTER
    insert (flush, not commit -- we need the DB-assigned id but don't want
    to finalize the transaction until we're sure encoding succeeded).
    """
    link = Link(long_url=long_url, owner_api_key_id=api_key_id)
    session.add(link)
    session.flush()  # assigns link.id via the DB sequence without committing yet
    short_code = encode(link.id)
    session.commit()
    return CreateLinkResult(short_code=short_code, long_url=long_url)


def resolve_link(session: Session, short_code: str) -> Optional[Link]:
    """Looks up a link by its short code. Returns None if not found rather
    than raising -- "not found" is an expected, normal outcome for a
    redirect endpoint, not an error condition."""
    try:
        link_id = decode(short_code)
    except ValueError:
        return None
    return session.get(Link, link_id)


def increment_click_count(session: Session, short_code: str) -> None:
    try:
        link_id = decode(short_code)
    except ValueError:
        return
    link = session.get(Link, link_id)
    if link:
        link.click_count += 1
        session.commit()


def get_stats(session: Session, short_code: str) -> Optional[Link]:
    return resolve_link(session, short_code)
