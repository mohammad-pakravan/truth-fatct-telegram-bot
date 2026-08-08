from __future__ import annotations

from datetime import datetime
from typing import Optional

# Considered "online" if active within this window
ONLINE_WINDOW_SECONDS = 5 * 60


def is_online(dt: Optional[datetime], *, now: Optional[datetime] = None) -> bool:
    if not dt:
        return False
    now = now or datetime.utcnow()
    secs = int((now - dt).total_seconds())
    return 0 <= secs < ONLINE_WINDOW_SECONDS


def online_emoji(dt: Optional[datetime], *, now: Optional[datetime] = None) -> str:
    """🟢 online / 🔴 offline for list UIs (no in-game check)."""
    return "🟢" if is_online(dt, now=now) else "🔴"


def presence_badge(
    *,
    last_active_at: Optional[datetime],
    in_game: bool = False,
    now: Optional[datetime] = None,
) -> str:
    """Short badge for lists: in-game / online / offline."""
    if in_game:
        return "🎮"
    return online_emoji(last_active_at, now=now)


def presence_label(
    *,
    last_active_at: Optional[datetime],
    in_game: bool = False,
    now: Optional[datetime] = None,
) -> str:
    """Full status line for profiles / captions."""
    if in_game:
        return "🎮 در حال بازی"
    if is_online(last_active_at, now=now):
        return "🟢 آنلاین"
    return format_last_seen(last_active_at, now=now)


def format_last_seen(dt: Optional[datetime], *, now: Optional[datetime] = None) -> str:
    """Human-readable last-seen / online status in Persian."""
    if not dt:
        return "🔴 آخرین بازدید: نامشخص"
    now = now or datetime.utcnow()
    secs = int((now - dt).total_seconds())
    if secs < 0:
        secs = 0
    if secs < ONLINE_WINDOW_SECONDS:
        return "🟢 آنلاین"
    if secs < 60 * 60:
        m = max(1, secs // 60)
        return f"🔴 آخرین بازدید: {m} دقیقه پیش"
    if secs < 24 * 60 * 60:
        h = max(1, secs // 3600)
        return f"🔴 آخرین بازدید: {h} ساعت پیش"
    if secs < 7 * 24 * 60 * 60:
        d = max(1, secs // 86400)
        return f"🔴 آخرین بازدید: {d} روز پیش"
    return f"🔴 آخرین بازدید: {dt.strftime('%Y-%m-%d')}"
