import os
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# Falls back to the local dev credentials used throughout this project's
# README/tests if DATABASE_URL isn't set -- so `pytest` and `uvicorn` keep
# working out of the box for anyone cloning the repo, while still
# demonstrating the real practice of not hardcoding credentials: a real
# deployment would set DATABASE_URL as an actual environment variable and
# never touch this file.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://urlshort:urlshort_dev@127.0.0.1:5432/urlshortener"
)


class Base(DeclarativeBase):
    pass


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Link(Base):
    __tablename__ = "links"

    # This id IS the value base62-encoded into the public short code --
    # see app/service.py. Using the DB's own auto-increment guarantees
    # uniqueness structurally, rather than generating a random code and
    # hoping/checking for collisions.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    long_url: Mapped[str] = mapped_column(String(2048))
    owner_api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    click_count: Mapped[int] = mapped_column(BigInteger, default=0)


def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


def get_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine):
    Base.metadata.create_all(engine)
