from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy.orm import Session
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from bot.models import SponsoredChannel


MEMBER_OK = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.RESTRICTED,
    "member",
    "administrator",
    "creator",
    "restricted",
}
_owner = getattr(ChatMemberStatus, "OWNER", None)
_creator = getattr(ChatMemberStatus, "CREATOR", None)
if _owner:
    MEMBER_OK.add(_owner)
if _creator:
    MEMBER_OK.add(_creator)


def list_active_for_provinces(
    session: Session, provinces: Iterable[str]
) -> list[SponsoredChannel]:
    """Active sponsored channels linked to any of the given provinces."""
    provs = [p for p in provinces if p]
    if not provs:
        return []
    return (
        session.query(SponsoredChannel)
        .filter(
            SponsoredChannel.active.is_(True),
            SponsoredChannel.province.in_(provs),
        )
        .order_by(SponsoredChannel.sort_order, SponsoredChannel.id)
        .all()
    )


def list_active_for_province(session: Session, province: str) -> list[SponsoredChannel]:
    return list_active_for_provinces(session, [province] if province else [])


def list_all_channels(session: Session) -> list[SponsoredChannel]:
    return (
        session.query(SponsoredChannel)
        .order_by(SponsoredChannel.province, SponsoredChannel.sort_order, SponsoredChannel.id)
        .all()
    )


def add_channel(
    session: Session,
    chat_id: int,
    *,
    province: str,
    title: str = "",
    invite_link: Optional[str] = None,
    created_by: Optional[int] = None,
) -> SponsoredChannel:
    existing = session.query(SponsoredChannel).filter_by(chat_id=chat_id).one_or_none()
    if existing:
        existing.active = True
        existing.province = province[:64]
        if title:
            existing.title = title[:128]
        if invite_link:
            existing.invite_link = invite_link[:256]
        session.flush()
        return existing
    row = SponsoredChannel(
        chat_id=chat_id,
        province=province[:64],
        title=(title or str(chat_id))[:128],
        invite_link=invite_link[:256] if invite_link else None,
        active=True,
        created_by=created_by,
    )
    session.add(row)
    session.flush()
    return row


def set_channel_active(session: Session, channel_id: int, active: bool) -> Optional[SponsoredChannel]:
    row = session.get(SponsoredChannel, channel_id)
    if not row:
        return None
    row.active = active
    session.flush()
    return row


def delete_channel(session: Session, channel_id: int) -> bool:
    row = session.get(SponsoredChannel, channel_id)
    if not row:
        return False
    session.delete(row)
    session.flush()
    return True


async def is_member(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int
) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        status = member.status
        if status in MEMBER_OK:
            if status == ChatMemberStatus.RESTRICTED or status == "restricted":
                return bool(getattr(member, "is_member", True))
            return True
        return False
    except Exception:
        return False


async def missing_channels(
    context: ContextTypes.DEFAULT_TYPE,
    session: Session,
    user_id: int,
    provinces: Iterable[str],
) -> list[SponsoredChannel]:
    missing: list[SponsoredChannel] = []
    for ch in list_active_for_provinces(session, provinces):
        if not await is_member(context, ch.chat_id, user_id):
            missing.append(ch)
    return missing


def channel_label(ch: SponsoredChannel) -> str:
    title = (ch.title or "").strip()
    if title and title != str(ch.chat_id) and not title.lstrip("-").isdigit():
        return title
    return "کانال اسپانسری"


def _looks_like_chat_id(title: str | None, chat_id: int) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    if t == str(chat_id):
        return True
    return t.lstrip("-").isdigit()


async def refresh_channel_meta(
    context: ContextTypes.DEFAULT_TYPE, session: Session, channels: list[SponsoredChannel]
) -> None:
    """Fill missing/stale titles (and invite links) from Telegram."""
    for ch in channels:
        need_title = _looks_like_chat_id(ch.title, ch.chat_id)
        need_link = not ch.invite_link
        if not need_title and not need_link:
            continue
        try:
            chat = await context.bot.get_chat(ch.chat_id)
            if need_title:
                name = chat.title or getattr(chat, "username", None)
                if name:
                    ch.title = str(name)[:128]
            if need_link:
                link = getattr(chat, "invite_link", None)
                if not link:
                    try:
                        link = await context.bot.export_chat_invite_link(ch.chat_id)
                    except Exception:
                        link = None
                if link:
                    ch.invite_link = str(link)[:256]
        except Exception:
            continue
    session.flush()


def snapshot_channels(channels: list[SponsoredChannel]) -> list:
    return [
        type(
            "Ch",
            (),
            {
                "id": c.id,
                "chat_id": c.chat_id,
                "title": channel_label(c),
                "invite_link": c.invite_link,
                "province": c.province,
            },
        )()
        for c in channels
    ]
