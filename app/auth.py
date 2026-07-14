from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.models import ApiKey


def require_api_key(x_api_key: str = Header(...)) -> str:
    """FastAPI dependency: just validates the header is present. The
    actual DB lookup happens in resolve_api_key, kept separate so this
    stays a thin, easily-testable presence check."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    return x_api_key


def resolve_api_key(session: Session, key: str) -> ApiKey:
    api_key = session.query(ApiKey).filter_by(key=key).first()
    if not api_key:
        raise HTTPException(status_code=401, detail="invalid API key")
    return api_key
