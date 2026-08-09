from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from bot.models import User, UserContact, UserLike


def like_user(
    session: Session,
    liker: User,
    liked: User,
    *,
    session_id: int | None = None,
) -> tuple[str, int]:
    """
    Toggle like. Returns (status, likes_count) where status is liked|unliked|self.
    Likes always attach to the real User row (fake personas map to that user).
    """
    if liker.id == liked.id:
        return "self", int(liked.likes_count or 0)

    existing = (
        session.query(UserLike)
        .filter(UserLike.liker_id == liker.id, UserLike.liked_id == liked.id)
        .one_or_none()
    )
    if existing:
        session.delete(existing)
        liked.likes_count = max(0, int(liked.likes_count or 0) - 1)
        session.flush()
        return "unliked", int(liked.likes_count or 0)

    session.add(
        UserLike(
            liker_id=liker.id,
            liked_id=liked.id,
            session_id=session_id,
            created_at=datetime.utcnow(),
        )
    )
    liked.likes_count = int(liked.likes_count or 0) + 1
    session.flush()
    return "liked", int(liked.likes_count or 0)


def add_contact(
    session: Session,
    owner: User,
    contact: User,
    *,
    session_id: int | None = None,
) -> str:
    if owner.id == contact.id:
        return "self"
    existing = (
        session.query(UserContact)
        .filter(UserContact.owner_id == owner.id, UserContact.contact_id == contact.id)
        .one_or_none()
    )
    if existing:
        return "exists"
    session.add(
        UserContact(
            owner_id=owner.id,
            contact_id=contact.id,
            session_id=session_id,
            created_at=datetime.utcnow(),
        )
    )
    session.flush()
    return "added"


def remove_contact(session: Session, owner: User, contact_user_id: int) -> bool:
    row = (
        session.query(UserContact)
        .filter(
            UserContact.owner_id == owner.id,
            UserContact.contact_id == contact_user_id,
        )
        .one_or_none()
    )
    if not row:
        return False
    session.delete(row)
    session.flush()
    return True


def list_contacts(session: Session, owner: User, *, limit: int = 50) -> list[UserContact]:
    return (
        session.query(UserContact)
        .filter(UserContact.owner_id == owner.id)
        .order_by(UserContact.id.desc())
        .limit(limit)
        .all()
    )


def list_liked_users(session: Session, liker: User, *, limit: int = 50) -> list[User]:
    """Users this person liked, newest likes first; prefer recently active."""
    rows = (
        session.query(User)
        .join(UserLike, UserLike.liked_id == User.id)
        .filter(UserLike.liker_id == liker.id)
        .order_by(UserLike.id.desc())
        .limit(limit)
        .all()
    )
    # Prefer recently active in Python (portable across SQLite/Postgres)
    rows.sort(key=lambda u: u.last_active_at or datetime.min, reverse=True)
    return rows


def list_contact_users(session: Session, owner: User, *, limit: int = 50) -> list[User]:
    rows = (
        session.query(User)
        .join(UserContact, UserContact.contact_id == User.id)
        .filter(UserContact.owner_id == owner.id)
        .order_by(UserContact.id.desc())
        .limit(limit)
        .all()
    )
    rows.sort(key=lambda u: u.last_active_at or datetime.min, reverse=True)
    return rows


def has_liked(session: Session, liker: User, liked_id: int) -> bool:
    return (
        session.query(UserLike.id)
        .filter(UserLike.liker_id == liker.id, UserLike.liked_id == liked_id)
        .first()
        is not None
    )


def has_contact(session: Session, owner: User, contact_id: int) -> bool:
    return (
        session.query(UserContact.id)
        .filter(UserContact.owner_id == owner.id, UserContact.contact_id == contact_id)
        .first()
        is not None
    )


def is_blocked(session: Session, blocker: User, blocked_id: int) -> bool:
    from bot.models import UserBlock

    return (
        session.query(UserBlock.id)
        .filter(UserBlock.blocker_id == blocker.id, UserBlock.blocked_id == blocked_id)
        .first()
        is not None
    )


def either_blocked(session: Session, a: User, b: User) -> bool:
    return is_blocked(session, a, b.id) or is_blocked(session, b, a.id)


def toggle_block(session: Session, blocker: User, blocked: User) -> str:
    """Returns blocked|unblocked|self."""
    from bot.models import UserBlock

    if blocker.id == blocked.id:
        return "self"
    row = (
        session.query(UserBlock)
        .filter(UserBlock.blocker_id == blocker.id, UserBlock.blocked_id == blocked.id)
        .one_or_none()
    )
    if row:
        session.delete(row)
        session.flush()
        return "unblocked"
    session.add(UserBlock(blocker_id=blocker.id, blocked_id=blocked.id))
    session.flush()
    return "blocked"


def has_online_notify(session: Session, watcher: User, target_id: int) -> bool:
    from bot.models import OnlineNotify

    return (
        session.query(OnlineNotify.id)
        .filter(OnlineNotify.watcher_id == watcher.id, OnlineNotify.target_id == target_id)
        .first()
        is not None
    )


def toggle_online_notify(session: Session, watcher: User, target: User) -> str:
    """Returns on|off|self."""
    from bot.models import OnlineNotify

    if watcher.id == target.id:
        return "self"
    row = (
        session.query(OnlineNotify)
        .filter(OnlineNotify.watcher_id == watcher.id, OnlineNotify.target_id == target.id)
        .one_or_none()
    )
    if row:
        session.delete(row)
        session.flush()
        return "off"
    session.add(OnlineNotify(watcher_id=watcher.id, target_id=target.id))
    session.flush()
    return "on"


def collect_online_watchers(
    session: Session,
    user: User,
    *,
    was_offline: bool,
) -> list[int]:
    """
    If user just came online, return telegram_ids of watchers to notify
    and stamp last_notified_at.
    """
    if not was_offline:
        return []
    from bot.models import OnlineNotify, User as UserModel

    rows = (
        session.query(OnlineNotify, UserModel)
        .join(UserModel, UserModel.id == OnlineNotify.watcher_id)
        .filter(OnlineNotify.target_id == user.id)
        .all()
    )
    now = datetime.utcnow()
    out: list[int] = []
    for watch, watcher in rows:
        # Avoid spam: at most once per 30 minutes
        if watch.last_notified_at and (now - watch.last_notified_at).total_seconds() < 1800:
            continue
        watch.last_notified_at = now
        if watcher.telegram_id:
            out.append(int(watcher.telegram_id))
    session.flush()
    return out


def players_were_in_game(session: Session, game_id: int, user_a_id: int, user_b_id: int) -> bool:
    from bot.models import GamePlayer

    ids = {
        r[0]
        for r in session.query(GamePlayer.user_id).filter(GamePlayer.session_id == game_id).all()
    }
    return user_a_id in ids and user_b_id in ids
