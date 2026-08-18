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
        # Fill a blank name from Telegram — never overwrite one the user typed.
        if full_name and not (user.display_name or "").strip():
            user.display_name = full_name[:128]
        user.last_active_at = datetime.utcnow()
        # Stash for callers that can send Telegram notifies
        user._became_online = was_offline  # type: ignore[attr-defined]
        return user

    user = User(
        telegram_id=telegram_id,
        username=username,
        display_name=(full_name or username or f"user_{telegram_id}")[:128],
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
    from bot.services.textfmt import format_profile_card

    apply_privacy = viewer_settings is not None
    text = format_profile_card(
        user,
        apply_privacy=apply_privacy,
        own=not apply_privacy,
        show_likes=True,
        show_status=True,
        html=False,
    )
    show_id = False if not apply_privacy else user.show_private_id
    if show_id and user.username:
        from bot.services.textfmt import rtl

        text += "\n" + rtl(f"@{user.username}")
    return text


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
    "account_private",
    "notify_profile_visit",
    "notify_follow",
}


def toggle_setting(user: User, field: str) -> bool:
    if field not in SETTING_FIELDS:
        raise ValueError(field)
    current = bool(getattr(user, field, False))
    setattr(user, field, not current)
    # Keep stranger-search gate in sync with private account.
    if field == "account_private":
        user.allow_stranger_requests = not bool(user.account_private)
    return bool(getattr(user, field))


def set_account_private(user: User, private: bool = True) -> None:
    user.account_private = bool(private)
    user.allow_stranger_requests = not bool(private)


def is_account_private(user: User) -> bool:
    return bool(getattr(user, "account_private", False))
