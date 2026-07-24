from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from bot.config import DATABASE_URL, DATA_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    from bot import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()
    _migrate_postgres_bigint()


def _migrate_sqlite_columns() -> None:
    """Add new columns on existing SQLite DBs without wiping data."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        cols = {r[1] for r in rows}
        if "province" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN province VARCHAR(64)")
        if "last_active_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN last_active_at DATETIME")
        if "profile_photo_key" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN profile_photo_key VARCHAR(512)")


def _migrate_postgres_bigint() -> None:
    """Telegram IDs exceed 32-bit int; widen columns on existing Postgres DBs."""
    if "postgresql" not in DATABASE_URL:
        return
    alters = [
        "ALTER TABLE users ALTER COLUMN telegram_id TYPE BIGINT",
        "ALTER TABLE game_sessions ALTER COLUMN chat_id TYPE BIGINT",
        "ALTER TABLE game_sessions ALTER COLUMN channel_id TYPE BIGINT",
        "ALTER TABLE game_sessions ALTER COLUMN discussion_chat_id TYPE BIGINT",
        "ALTER TABLE votes ALTER COLUMN voter_telegram_id TYPE BIGINT",
    ]
    with engine.begin() as conn:
        for sql in alters:
            try:
                conn.exec_driver_sql(sql)
            except Exception:
                pass



@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()