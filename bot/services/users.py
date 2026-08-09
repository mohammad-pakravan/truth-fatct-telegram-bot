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
    from bot.services.presence import is_online

    user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
    if user:
        was_offline = not is_online(user.last_active_at)
        if username is not None:
            user.username = username
        # Keep Telegram account name for users who never finished onboarding
        if full_name and not profile_complete(user):
            user.display_name = full_name[:64]
        user.last_active_at = datetime.utcnow()
        # Stash for callers that can send Telegram notifies
        user._became_online = was_offline  # type: ignore[attr-defined]
        return user

    user = User(
        telegram_id=telegram_id,
        username=username,
        display_name=(full_name or username or f"user_{telegram_id}")[:64],
        last_active_at=datetime.utcnow(),
    )
    user._became_online = False  # type: ignore[attr-defined]
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

    likes = int(getattr(user, "likes_count", 0) or 0)
    lines.append(f"❤️ لایک: {likes}")

    from bot.services.presence import format_last_seen

    lines.append(format_last_seen(getattr(user, "last_active_at", None)))

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
