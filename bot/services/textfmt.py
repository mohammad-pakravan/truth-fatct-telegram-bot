from __future__ import annotations

from html import escape
from typing import Optional

from bot.models import User

RLM = "\u200f"
LRI = "\u2066"
PDI = "\u2069"
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


def rtl(text: str) -> str:
    """Force a line to stay right-aligned on Telegram mobile."""
    return f"{RLM}{text}"


def btn(emoji: str, label: str) -> str:
    """Inline-button label: emoji stays on the right in RTL."""
    return f"{RLM}{emoji}  {label}"


def _esc(text: str, *, html: bool) -> str:
    return escape(text, quote=False) if html else text


def _name(text: str, *, html: bool) -> str:
    raw = (text or "").strip() or "—"
    if any(c.isascii() and (c.isalnum() or c in "@._-") for c in raw):
        wrapped = f"{LRI}{_esc(raw, html=html)}{PDI}"
    else:
        wrapped = _esc(raw, html=html)
    return wrapped


def format_profile_card(
    user: User,
    *,
    apply_privacy: bool = True,
    own: bool = False,
    in_game: bool = False,
    intro: Optional[str] = None,
    html: bool = False,
    show_likes: Optional[bool] = None,
    show_status: Optional[bool] = None,
) -> str:
    """
    Compact RTL profile block for Telegram captions.

    محمد
    دختر · ۲۳ ساله
    📍 اردبیل، سقز
    """
    if show_likes is None:
        show_likes = False
    if show_status is None:
        show_status = not own
    gender_map = {"male": "پسر", "female": "دختر"}
    show_identity = True if not apply_privacy else bool(user.show_identity)
    show_age = True if not apply_privacy else bool(user.show_age)

    lines: list[str] = []
    if intro:
        lines.append(rtl(_esc(intro.strip(), html=html)))
        lines.append("")

    name = _name(user.display_name or "—", html=html)
    title = f"<b>{RLM}{name}</b>" if html else rtl(name)
    lines.append(title)

    nick = (user.nickname or "").strip()
    if nick:
        lines.append(rtl(f"«{_esc(nick, html=html)}»"))

    meta: list[str] = []
    if show_identity:
        gender = gender_map.get(user.gender or "", "")
        if gender:
            meta.append(gender)
    if show_age and user.age is not None:
        meta.append(f"{fa_num(user.age)} ساله")
    if meta:
        lines.append(rtl(" · ".join(meta)))
    elif not show_identity:
        lines.append(rtl("هویت مخفی"))

    if show_identity:
        parts = [p for p in (user.province, user.city) if p]
        if parts:
            loc = "، ".join(_esc(p, html=html) for p in parts)
            lines.append(rtl(f"📍 {loc}"))

    if show_status or show_likes:
        from bot.services.presence import presence_label

        status = presence_label(last_active_at=user.last_active_at, in_game=in_game)
        extra: list[str] = []
        if show_status:
            extra.append(status)
        if show_likes:
            likes = int(getattr(user, "likes_count", 0) or 0)
            extra.append(f"❤️ {fa_num(likes)}")
        if extra:
            lines.append("")
            lines.append(rtl("  ·  ".join(extra)))

    return "\n".join(lines)
