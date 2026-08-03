from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from bot.config import ADMIN_IDS
from bot.models import BotAdmin


def is_admin(session: Session, telegram_id: int) -> bool:
    if telegram_id in ADMIN_IDS:
        return True
    return (
        session.query(BotAdmin)
        .filter_by(telegram_id=telegram_id)
        .first()
        is not None
    )


def list_admin_ids(session: Session) -> list[int]:
    db_ids = [row.telegram_id for row in session.query(BotAdmin).order_by(BotAdmin.id).all()]
    # Env admins first, then DB extras (deduped)
    seen: set[int] = set()
    ordered: list[int] = []
    for tid in sorted(ADMIN_IDS) + db_ids:
        if tid not in seen:
            seen.add(tid)
            ordered.append(tid)
    return ordered


def is_env_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS


def add_admin(session: Session, telegram_id: int, added_by: Optional[int] = None) -> tuple[BotAdmin | None, str]:
    """
    Returns (row|None, status) where status is: added | exists | env_exists
    """
    if telegram_id in ADMIN_IDS:
        return None, "env_exists"
    existing = session.query(BotAdmin).filter_by(telegram_id=telegram_id).one_or_none()
    if existing:
        return existing, "exists"
    row = BotAdmin(telegram_id=telegram_id, added_by=added_by)
    session.add(row)
    session.flush()
    return row, "added"


def remove_admin(session: Session, telegram_id: int) -> str:
    """
    Returns: removed | env_protected | not_found
    Env admins cannot be removed from the panel.
    """
    if telegram_id in ADMIN_IDS:
        return "env_protected"
    row = session.query(BotAdmin).filter_by(telegram_id=telegram_id).one_or_none()
    if not row:
        return "not_found"
    session.delete(row)
    session.flush()
    return "removed"
