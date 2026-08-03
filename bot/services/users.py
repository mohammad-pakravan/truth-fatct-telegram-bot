from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from bot.models import User


def get_or_create_user(
    session: Session,
    telegram_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
) -> User:
    user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
    if user:
        if username is not None:
            user.username = username
        user.last_active_at = datetime.utcnow()
        return user

    user = User(
        telegram_id=telegram_id,
        username=username,
        display_name=full_name or (username or f"user_{telegram_id}"),
        last_active_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def profile_complete(user: User) -> bool:
    return bool(
        user.display_name
        and user.province
        and user.city
        and user.gender
        and user.age
    )


def format_profile(user: User, viewer_settings: Optional[User] = None) -> str:
    """
    Format a user's profile for another player.
    When viewer_settings is not None, apply subject's privacy flags.
    """
    apply_privacy = viewer_settings is not None
    lines = [f"نام: {user.display_name or '—'}"]

    if user.nickname:
        lines.append(f"لقب: {user.nickname}")

    show_identity = True if not apply_privacy else user.show_identity
    show_age = True if not apply_privacy else user.show_age
    show_id = False if not apply_privacy else user.show_private_id

    if show_identity:
        gender_map = {"male": "پسر", "female": "دختر"}
        lines.append(f"جنسیت: {gender_map.get(user.gender or '', '—')}")
        lines.append(f"استان: {user.province or '—'}")
        lines.append(f"شهر: {user.city or '—'}")
    else:
        lines.append("هویت: مخفی")

    if show_age and user.age:
        lines.append(f"سن: {user.age}")

    if show_id and user.username:
        lines.append(f"آیدی: @{user.username}")

    return "\n".join(lines)


def may_show_photo(user: User, *, for_opponent: bool = True) -> bool:
    """Whether this user's photo may be shown to an opponent."""
    if not for_opponent:
        return True
    return bool(user.show_photo and (user.profile_photo_file_id or user.profile_photo_key))


def public_name(user: User, mode: str = "real", custom: Optional[str] = None) -> str:
    if mode == "anonymous":
        return "کاربر ناشناس"
    if mode == "nickname":
        return custom or user.nickname or user.display_name or "بازیکن"
    return user.display_name or user.nickname or "بازیکن"


SETTING_FIELDS = {
    "allow_stranger_requests",
    "allow_anonymous_requests",
    "show_identity",
    "show_age",
    "show_photo",
    "show_private_id",
}


def toggle_setting(user: User, field: str) -> bool:
    if field not in SETTING_FIELDS:
        raise ValueError(field)
    current = getattr(user, field)
    setattr(user, field, not current)
    return getattr(user, field)
