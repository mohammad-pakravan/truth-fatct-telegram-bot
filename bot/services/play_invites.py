from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from bot.models import PlayInvite, User

INVITE_TTL_SECONDS = 120


def create_invite(
    session: Session,
    *,
    from_user: User,
    to_user: User,
) -> PlayInvite:
    # Cancel older pending invites between the same pair (either direction)
    now = datetime.utcnow()
    old = (
        session.query(PlayInvite)
        .filter(
            PlayInvite.status == "pending",
            (
                ((PlayInvite.from_user_id == from_user.id) & (PlayInvite.to_user_id == to_user.id))
                | ((PlayInvite.from_user_id == to_user.id) & (PlayInvite.to_user_id == from_user.id))
            ),
        )
        .all()
    )
    for row in old:
        row.status = "cancelled"

    invite = PlayInvite(
        from_user_id=from_user.id,
        to_user_id=to_user.id,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(seconds=INVITE_TTL_SECONDS),
    )
    session.add(invite)
    session.flush()
    return invite


def get_invite(session: Session, invite_id: int) -> Optional[PlayInvite]:
    return session.get(PlayInvite, invite_id)


def set_status(session: Session, invite: PlayInvite, status: str) -> bool:
    if invite.status != "pending":
        return False
    invite.status = status
    session.flush()
    return True


def expire_if_needed(session: Session, invite: PlayInvite) -> bool:
    """Mark expired if past deadline while still pending. Returns True if expired now."""
    if invite.status != "pending":
        return False
    if invite.expires_at and invite.expires_at <= datetime.utcnow():
        invite.status = "expired"
        session.flush()
        return True
    return False


def pending_outgoing(session: Session, user: User) -> Optional[PlayInvite]:
    return (
        session.query(PlayInvite)
        .filter(
            PlayInvite.from_user_id == user.id,
            PlayInvite.status == "pending",
            PlayInvite.expires_at > datetime.utcnow(),
        )
        .order_by(PlayInvite.id.desc())
        .first()
    )
