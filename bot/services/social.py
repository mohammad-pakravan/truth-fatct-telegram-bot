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


def players_were_in_game(session: Session, game_id: int, user_a_id: int, user_b_id: int) -> bool:
    from bot.models import GamePlayer

    ids = {
        r[0]
        for r in session.query(GamePlayer.user_id).filter(GamePlayer.session_id == game_id).all()
    }
    return user_a_id in ids and user_b_id in ids
