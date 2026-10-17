from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


def now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Timezone required")
            return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


def database(url: str):
    if url.startswith("sqlite:///./"):
        Path(url.removeprefix("sqlite:///./")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 30}
        if url.startswith("sqlite")
        else {"connect_timeout": 5, "options": "-clock_timeout=5000 -cstatement_timeout=30000"},
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_setup(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")

    return engine, sessionmaker(engine, expire_on_commit=False)


def transaction(factory) -> Iterator[Session]:
    with factory() as db:
        with db.begin():
            yield db
