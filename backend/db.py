"""Database engine and session management (SQLite via DATABASE_URL)."""
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from backend import config

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False}
    if config.DATABASE_URL.startswith("sqlite")
    else {},
)


if config.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):
        """SQLite ignores FK constraints unless this pragma is on."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


def get_db():
    """FastAPI dependency yielding a session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """Context manager committing/rolling back a unit of work."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables and seed default system settings."""
    from backend import models  # noqa: F401  (register mappers)
    from backend.settings import DEFAULT_SETTINGS

    Base.metadata.create_all(engine)

    with session_scope() as db:
        for key, (value, description) in DEFAULT_SETTINGS.items():
            exists = db.query(models.SystemSetting).filter_by(key=key).first()
            if not exists:
                db.add(models.SystemSetting(key=key, value=value, description=description))
