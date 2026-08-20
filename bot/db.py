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
    _migrate_game_player_display()
    _migrate_channel_columns()
    _migrate_fake_identity_columns()
    _migrate_sponsored_channel_province()
    _migrate_game_session_inline_message()
    _migrate_round_media_columns()
    _migrate_user_likes_count()
    _migrate_account_privacy_columns()
    _migrate_round_prompt_source()
    _migrate_game_idle_nudge()


def _migrate_game_idle_nudge() -> None:
    """last_idle_nudge_at on game_sessions."""
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(game_sessions)").fetchall()
            cols = {r[1] for r in rows}
            if "last_idle_nudge_at" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE game_sessions ADD COLUMN last_idle_nudge_at DATETIME"
                )
        return
    if "postgresql" not in DATABASE_URL:
        return
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'game_sessions' "
                    "AND column_name = 'last_idle_nudge_at'"
                )
            ).fetchone()
            if not exists:
                conn.execute(
                    text("ALTER TABLE game_sessions ADD COLUMN last_idle_nudge_at TIMESTAMP")
                )
    except Exception:
        pass


def _migrate_round_prompt_source() -> None:
    """Add prompt_source on rounds."""
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(rounds)").fetchall()
            cols = {r[1] for r in rows}
            if "prompt_source" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE rounds ADD COLUMN prompt_source VARCHAR(16)"
                )
        return
    if "postgresql" not in DATABASE_URL:
        return
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'rounds' AND column_name = 'prompt_source'"
                )
            ).fetchone()
            if not exists:
                conn.execute(text("ALTER TABLE rounds ADD COLUMN prompt_source VARCHAR(16)"))
    except Exception:
        pass


def _migrate_account_privacy_columns() -> None:
    """account_private / notify_profile_visit / notify_follow on users."""
    cols = [
        ("account_private", "BOOLEAN DEFAULT FALSE", "BOOLEAN DEFAULT FALSE"),
        ("notify_profile_visit", "BOOLEAN DEFAULT FALSE", "BOOLEAN DEFAULT FALSE"),
        ("notify_follow", "BOOLEAN DEFAULT FALSE", "BOOLEAN DEFAULT FALSE"),
    ]
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
            existing = {r[1] for r in rows}
            for name, sqlite_ddl, _pg in cols:
                if name not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE users ADD COLUMN {name} {sqlite_ddl}"
                    )
        return
    if "postgresql" not in DATABASE_URL:
        return
    try:
        with engine.begin() as conn:
            for name, _sqlite, pg_ddl in cols:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'users' AND column_name = :col"
                    ),
                    {"col": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {pg_ddl}"))
    except Exception:
        pass


def _migrate_user_likes_count() -> None:
    """Add likes_count on users."""
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
            cols = {r[1] for r in rows}
            if "likes_count" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE users ADD COLUMN likes_count INTEGER DEFAULT 0"
                )
        return

    if "postgresql" not in DATABASE_URL:
        return

    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'users' AND column_name = 'likes_count'"
                )
            ).fetchone()
            if not exists:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN likes_count INTEGER DEFAULT 0")
                )
    except Exception:
        pass


def _migrate_round_media_columns() -> None:
    """Add prompt/answer media columns on rounds."""
    cols = [
        ("prompt_media_type", "VARCHAR(16)"),
        ("prompt_file_id", "VARCHAR(256)"),
        ("answer_media_type", "VARCHAR(16)"),
        ("answer_file_id", "VARCHAR(256)"),
        ("category_key", "VARCHAR(16)"),
    ]

    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(rounds)").fetchall()
            existing = {r[1] for r in rows}
            for name, ddl in cols:
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE rounds ADD COLUMN {name} {ddl}")
        return

    if "postgresql" not in DATABASE_URL:
        return

    for name, ddl in cols:
        try:
            with engine.begin() as conn:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'rounds' AND column_name = :col"
                    ),
                    {"col": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE rounds ADD COLUMN {name} {ddl}"))
        except Exception:
            pass


def _migrate_game_session_inline_message() -> None:
    """Add inline_message_id to game_sessions for @bot inline starts."""
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(game_sessions)").fetchall()
            cols = {r[1] for r in rows}
            if cols and "inline_message_id" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE game_sessions ADD COLUMN inline_message_id VARCHAR(128)"
                )
        return

    if "postgresql" not in DATABASE_URL:
        return

    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'game_sessions' "
                    "AND column_name = 'inline_message_id'"
                )
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        "ALTER TABLE game_sessions "
                        "ADD COLUMN inline_message_id VARCHAR(128)"
                    )
                )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_game_sessions_inline_message_id "
                    "ON game_sessions (inline_message_id)"
                )
            )
    except Exception:
        pass


def _migrate_sponsored_channel_province() -> None:
    """Add province column to sponsored_channels if missing."""
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(sponsored_channels)").fetchall()
            cols = {r[1] for r in rows}
            if cols and "province" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE sponsored_channels ADD COLUMN province VARCHAR(64) DEFAULT ''"
                )
        return

    if "postgresql" not in DATABASE_URL:
        return

    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'sponsored_channels' "
                    "AND column_name = 'province'"
                )
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        "ALTER TABLE sponsored_channels "
                        "ADD COLUMN province VARCHAR(64) DEFAULT ''"
                    )
                )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_sponsored_channels_province "
                    "ON sponsored_channels (province)"
                )
            )
    except Exception:
        pass


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

        gp_rows = conn.exec_driver_sql("PRAGMA table_info(game_players)").fetchall()
        gp_cols = {r[1] for r in gp_rows}
        if "display_label" not in gp_cols:
            conn.exec_driver_sql(
                "ALTER TABLE game_players ADD COLUMN display_label VARCHAR(64)"
            )

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


def _migrate_game_player_display() -> None:
    """Widen identity_mode and add display_label for invite anonymity in-game."""
    if DATABASE_URL.startswith("sqlite"):
        return  # handled in _migrate_sqlite_columns

    if "postgresql" not in DATABASE_URL:
        return

    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'game_players' AND column_name = 'display_label'"
                )
            ).fetchone()
            if not exists:
                conn.execute(
                    text("ALTER TABLE game_players ADD COLUMN display_label VARCHAR(64)")
                )
    except Exception:
        pass

    try:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE game_players ALTER COLUMN identity_mode TYPE VARCHAR(16)")
            )
    except Exception:
        pass


def _migrate_channel_columns() -> None:
    """Channel prompt message id + widen vote value for comments."""
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(game_sessions)").fetchall()
            cols = {r[1] for r in rows}
            if "channel_prompt_message_id" not in cols:
                conn.exec_driver_sql(
                    "ALTER TABLE game_sessions ADD COLUMN channel_prompt_message_id BIGINT"
                )
        return

    if "postgresql" not in DATABASE_URL:
        return

    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'game_sessions' "
                    "AND column_name = 'channel_prompt_message_id'"
                )
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        "ALTER TABLE game_sessions "
                        "ADD COLUMN channel_prompt_message_id BIGINT"
                    )
                )
    except Exception:
        pass

    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE votes ALTER COLUMN value TYPE TEXT"))
    except Exception:
        pass


def _migrate_fake_identity_columns() -> None:
    """fingerprint/generated on fake_identities; user_fake_assignments via create_all."""
    cols = [
        ("fingerprint", "VARCHAR(64)"),
        ("generated", "BOOLEAN DEFAULT FALSE"),
        ("created_at", "TIMESTAMP"),
    ]

    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(fake_identities)").fetchall()
            existing = {r[1] for r in rows}
            for name, ddl in cols:
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE fake_identities ADD COLUMN {name} {ddl}")
        return

    if "postgresql" not in DATABASE_URL:
        return

    for name, ddl in cols:
        try:
            with engine.begin() as conn:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'fake_identities' AND column_name = :col"
                    ),
                    {"col": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE fake_identities ADD COLUMN {name} {ddl}"))
        except Exception:
            pass

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fake_identities_fingerprint "
                    "ON fake_identities (fingerprint)"
                )
            )
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
