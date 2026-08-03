from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from bot.config import BOT_USERNAME
from bot.models import GameSession, InviteLink, Round, User
from bot.services import game_engine
from bot.services.users import public_name


@dataclass
class AcceptedInvite:
    game: GameSession
    round: Round
    label: str
    owner: User
    joiner: User


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


def owner_identity_mode(invite: InviteLink) -> str:
    mode = invite.display_mode or "real"
    if mode in ("real", "anonymous", "nickname"):
        return mode
    return "real"


def accept_invite(session: Session, joiner: User, token: str) -> AcceptedInvite:
    """
    Create a friends game from an invite token.
    Raises RuntimeError with codes: invalid | self | busy
    """
    inv = get_invite(session, token)
    if not inv:
        raise RuntimeError("invalid")
    if inv.owner_id == joiner.id:
        raise RuntimeError("self")

    owner = session.get(User, inv.owner_id)
    if not owner:
        raise RuntimeError("invalid")

    if game_engine.active_session_for_user(session, joiner) or game_engine.active_session_for_user(
        session, owner
    ):
        raise RuntimeError("busy")

    label = inviter_label(inv)
    mode = owner_identity_mode(inv)
    game = game_engine.create_session(session, "friends", starter=owner)
    game_engine.add_player(
        session,
        game,
        owner,
        identity_mode=mode,
        display_label=inv.custom_label if mode == "nickname" else None,
    )
    game_engine.add_player(session, game, joiner)
    rnd = game_engine.start_two_player(session, game)
    return AcceptedInvite(game=game, round=rnd, label=label, owner=owner, joiner=joiner)
