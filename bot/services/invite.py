from __future__ import annotations

import secrets
from typing import Optional

from sqlalchemy.orm import Session

from bot.config import BOT_USERNAME
from bot.models import InviteLink, User
from bot.services.users import public_name


def create_invite(
    session: Session,
    owner: User,
    display_mode: str,
    custom_label: Optional[str] = None,
) -> InviteLink:
    token = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:16]
    invite = InviteLink(
        token=token,
        owner_id=owner.id,
        display_mode=display_mode,
        custom_label=custom_label,
        active=True,
    )
    session.add(invite)
    session.flush()
    return invite


def invite_link_url(token: str) -> str:
    username = BOT_USERNAME or "YourBot"
    return f"https://t.me/{username}?start=inv_{token}"


def get_invite(session: Session, token: str) -> Optional[InviteLink]:
    return (
        session.query(InviteLink)
        .filter_by(token=token, active=True)
        .one_or_none()
    )


def inviter_label(invite: InviteLink) -> str:
    return public_name(invite.owner, invite.display_mode, invite.custom_label)
