from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        options["isolation_level"] = "READ COMMITTED"
        options["pool_recycle"] = 1800
    result = create_engine(url, **options)
    if url.startswith("sqlite"):
        @event.listens_for(result, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
    return result


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def lock_state(db):
    """All directory, permission and ledger writers share this short transaction lock.

    MySQL serializes writers with SELECT FOR UPDATE; SQLite is for single-process
    local demos and functional tests only, not production concurrency.
    """
    from .models import SystemState
    return db.scalar(select(SystemState).where(SystemState.id == 1).with_for_update())


def get_db():
    with SessionLocal() as db:
        yield db
