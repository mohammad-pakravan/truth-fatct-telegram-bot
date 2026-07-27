from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
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
    _migrate_match_queue_columns()
    _migrate_location_columns()


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
        if "latitude" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN latitude FLOAT")
        if "longitude" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN longitude FLOAT")
        if "location_updated_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN location_updated_at DATETIME")


def _migrate_location_columns() -> None:
    """Add location columns on users + radius on match_queue (Postgres)."""
    user_cols = [
        ("latitude", "DOUBLE PRECISION"),
        ("longitude", "DOUBLE PRECISION"),
        ("location_updated_at", "TIMESTAMP"),
    ]
    queue_cols = [("radius_km", "INTEGER")]

    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(match_queue)").fetchall()
            cols = {r[1] for r in rows}
            if "radius_km" not in cols:
                conn.exec_driver_sql("ALTER TABLE match_queue ADD COLUMN radius_km INTEGER")
        return

    if "postgresql" not in DATABASE_URL:
        return

    for name, ddl in user_cols:
        try:
            with engine.begin() as conn:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'users' AND column_name = :col"
                    ),
                    {"col": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
        except Exception:
            pass

    for name, ddl in queue_cols:
        try:
            with engine.begin() as conn:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'match_queue' AND column_name = :col"
                    ),
                    {"col": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE match_queue ADD COLUMN {name} {ddl}"))
        except Exception:
            pass


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
    for sql in alters:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception:
            pass


def _migrate_match_queue_columns() -> None:
    """Add queue management columns on existing DBs."""
    additions = [
        ("status", "VARCHAR(16) DEFAULT 'waiting'"),
        ("queue_mode", "VARCHAR(16) DEFAULT 'stranger'"),
        ("provinces_json", "TEXT"),
        ("matched_game_id", "INTEGER"),
        ("expires_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
    ]

    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(match_queue)").fetchall()
            cols = {r[1] for r in rows}
            for name, ddl in additions:
                if name not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE match_queue ADD COLUMN {name} {ddl}")
        return

    if "postgresql" not in DATABASE_URL:
        return

    for name, ddl in additions:
        try:
            with engine.begin() as conn:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'match_queue' AND column_name = :col"
                    ),
                    {"col": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE match_queue ADD COLUMN {name} {ddl}"))
        except Exception:
            pass

    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE match_queue SET status = 'waiting' WHERE status IS NULL"))
    except Exception:
        pass

    for idx_sql in (
        "CREATE INDEX IF NOT EXISTS ix_match_queue_status ON match_queue (status)",
        "CREATE INDEX IF NOT EXISTS ix_match_queue_expires_at ON match_queue (expires_at)",
        "CREATE INDEX IF NOT EXISTS ix_match_queue_created_at ON match_queue (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_match_queue_queue_mode ON match_queue (queue_mode)",
    ):
        try:
            with engine.begin() as conn:
                conn.execute(text(idx_sql))
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
