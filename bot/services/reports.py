from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from bot.models import AnalyticsEvent, GameSession, MatchQueue, SponsoredChannel, User

EVENT_JOIN_CLICK = "sponsor_join_click"
EVENT_CHECK = "sponsor_check"
EVENT_VERIFIED = "sponsor_verified"

TEHRAN = ZoneInfo("Asia/Tehran")


def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def period_since(key: str) -> tuple[str, datetime]:
    """
    Periods in Asia/Tehran, returned as UTC-naive for DB compare.
    minute = last 1 minute
    hour   = last 60 minutes
    day    = from local midnight today
    week   = from local midnight 6 days ago (7 calendar days including today)
    month  = from local midnight on the 1st of this month
    """
    now_local = datetime.now(TEHRAN)
    if key == "minute":
        start_local = now_local - timedelta(minutes=1)
        label = "۱ دقیقه اخیر"
    elif key == "hour":
        start_local = now_local - timedelta(hours=1)
        label = "۱ ساعت اخیر"
    elif key == "week":
        start_local = (now_local - timedelta(days=6)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        label = "۷ روز اخیر"
    elif key == "month":
        start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = f"ماه جاری ({start_local.strftime('%Y/%m')})"
    else:
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        label = f"امروز ({start_local.strftime('%Y/%m/%d')})"
    return label, _to_utc_naive(start_local)


def log_event(
    session: Session,
    event_type: str,
    *,
    telegram_id: Optional[int] = None,
    channel_id: Optional[int] = None,
    province: Optional[str] = None,
) -> None:
    session.add(
        AnalyticsEvent(
            event_type=event_type,
            telegram_id=telegram_id,
            channel_id=channel_id,
            province=(province or None),
        )
    )
    session.flush()


def _count_users_since(session: Session, since: datetime) -> int:
    return (
        session.query(func.count(User.id))
        .filter(User.created_at >= since)
        .scalar()
        or 0
    )


def _count_active_since(session: Session, since: datetime) -> int:
    return (
        session.query(func.count(User.id))
        .filter(User.last_active_at.isnot(None), User.last_active_at >= since)
        .scalar()
        or 0
    )


def _count_returning_since(session: Session, since: datetime) -> int:
    """Active in period but registered before the period started."""
    return (
        session.query(func.count(User.id))
        .filter(
            User.last_active_at.isnot(None),
            User.last_active_at >= since,
            User.created_at < since,
        )
        .scalar()
        or 0
    )


def _count_events_since(
    session: Session, event_type: str, since: datetime, channel_id: Optional[int] = None
) -> int:
    q = session.query(func.count(AnalyticsEvent.id)).filter(
        AnalyticsEvent.event_type == event_type,
        AnalyticsEvent.created_at >= since,
    )
    if channel_id is not None:
        q = q.filter(AnalyticsEvent.channel_id == channel_id)
    return q.scalar() or 0


def overview_report(session: Session, period_key: str) -> str:
    label, since = period_since(period_key)
    total_users = session.query(func.count(User.id)).scalar() or 0
    new_users = _count_users_since(session, since)
    active = _count_active_since(session, since)
    returning = _count_returning_since(session, since)
    complete = (
        session.query(func.count(User.id))
        .filter(
            User.province.isnot(None),
            User.city.isnot(None),
            User.gender.isnot(None),
            User.age.isnot(None),
        )
        .scalar()
        or 0
    )
    males = session.query(func.count(User.id)).filter(User.gender == "male").scalar() or 0
    females = session.query(func.count(User.id)).filter(User.gender == "female").scalar() or 0

    games_started = (
        session.query(func.count(GameSession.id))
        .filter(GameSession.created_at >= since)
        .scalar()
        or 0
    )
    games_finished = (
        session.query(func.count(GameSession.id))
        .filter(
            GameSession.status == "finished",
            and_(
                GameSession.finished_at.isnot(None),
                GameSession.finished_at >= since,
            ),
        )
        .scalar()
        or 0
    )
    waiting_queue = (
        session.query(func.count(MatchQueue.id))
        .filter(MatchQueue.status == "waiting")
        .scalar()
        or 0
    )
    matched_queue = (
        session.query(func.count(MatchQueue.id))
        .filter(MatchQueue.status == "matched", MatchQueue.updated_at >= since)
        .scalar()
        or 0
    )

    clicks = _count_events_since(session, EVENT_JOIN_CLICK, since)
    checks = _count_events_since(session, EVENT_CHECK, since)
    verified = _count_events_since(session, EVENT_VERIFIED, since)

    return (
        f"📊 گزارش کلی — {label}\n"
        f"⏱ ساعت تهران\n"
        f"{'─' * 18}\n\n"
        f"👥 کاربران\n"
        f"• کل: {total_users:,}\n"
        f"• ثبت‌نام جدید: {new_users:,}\n"
        f"• کاربران فعال: {active:,}\n"
        f"  ↳ تازه‌وارد: {max(0, active - returning):,} | بازگشتی: {returning:,}\n"
        f"• پروفایل کامل: {complete:,}\n"
        f"• 👨 {males:,}  |  👩 {females:,}\n\n"
        f"📢 اسپانسر\n"
        f"• کلیک عضویت: {clicks:,}\n"
        f"• بررسی عضویت: {checks:,}\n"
        f"• عضویت تأییدشده: {verified:,}\n\n"
        f"🎮 بازی و مچ\n"
        f"• بازی شروع‌شده: {games_started:,}\n"
        f"• بازی تمام‌شده: {games_finished:,}\n"
        f"• مچ موفق: {matched_queue:,}\n"
        f"• الان در صف: {waiting_queue:,}"
    )


def users_period_report(session: Session) -> str:
    _, since_minute = period_since("minute")
    _, since_hour = period_since("hour")
    _, since_day = period_since("day")
    _, since_week = period_since("week")
    _, since_month = period_since("month")
    day_label, _ = period_since("day")
    now_local = datetime.now(TEHRAN)

    total = session.query(func.count(User.id)).scalar() or 0
    oldest = session.query(func.min(User.created_at)).scalar()

    def block(title: str, since: datetime) -> str:
        new = _count_users_since(session, since)
        active = _count_active_since(session, since)
        returning = _count_returning_since(session, since)
        active_new = max(0, active - returning)
        return (
            f"{title}\n"
            f"• ثبت‌نام جدید: {new:,}\n"
            f"• کاربران فعال: {active:,}\n"
            f"  ↳ تازه‌وارد: {active_new:,} | بازگشتی: {returning:,}"
        )

    oldest_txt = ""
    if oldest:
        oldest_local = oldest.replace(tzinfo=timezone.utc).astimezone(TEHRAN)
        oldest_txt = f"\nاولین کاربر: {oldest_local.strftime('%Y/%m/%d')}"

    return (
        f"🆕 کاربران فعال — ساعت تهران\n"
        f"⏱ الان: {now_local.strftime('%Y/%m/%d %H:%M')}\n"
        f"{'─' * 18}\n\n"
        f"{block('⏱ ۱ دقیقه اخیر', since_minute)}\n\n"
        f"{block('🕐 ۱ ساعت اخیر', since_hour)}\n\n"
        f"{block(f'📅 {day_label}', since_day)}\n\n"
        f"{block('📅 ۷ روز اخیر', since_week)}\n\n"
        f"{block('📅 ماه جاری', since_month)}\n\n"
        f"📦 کل کاربران ثبت‌شده: {total:,}"
        f"{oldest_txt}\n\n"
        f"ℹ️ «فعال» یعنی در آن بازه با ربات تعامل داشته "
        f"(منو، چت، بازی، جستجو و … — بر اساس last_active)."
    )


def provinces_report(session: Session, limit: int = 25) -> str:
    rows = (
        session.query(User.province, func.count(User.id))
        .filter(User.province.isnot(None), User.province != "")
        .group_by(User.province)
        .order_by(func.count(User.id).desc())
        .limit(limit)
        .all()
    )
    unknown = (
        session.query(func.count(User.id))
        .filter((User.province.is_(None)) | (User.province == ""))
        .scalar()
        or 0
    )
    if not rows and not unknown:
        return "📍 هنوز کاربری با استان ثبت‌شده نداریم."

    lines = [f"📍 کاربران به تفکیک استان (تاپ {limit})", "─" * 18, ""]
    for i, (prov, n) in enumerate(rows, 1):
        bar = "▓" * min(10, max(1, n // max(1, rows[0][1] // 10))) if rows else ""
        lines.append(f"{i}. {prov}: {n:,}  {bar}")
    if unknown:
        lines.append(f"\n❓ بدون استان: {unknown:,}")
    return "\n".join(lines)


def sponsors_report(session: Session, period_key: str) -> str:
    label, since = period_since(period_key)
    channels = (
        session.query(SponsoredChannel)
        .order_by(SponsoredChannel.province, SponsoredChannel.id)
        .all()
    )
    if not channels:
        return "📢 هنوز کانال اسپانسری ثبت نشده."

    total_clicks = _count_events_since(session, EVENT_JOIN_CLICK, since)
    total_checks = _count_events_since(session, EVENT_CHECK, since)
    total_ok = _count_events_since(session, EVENT_VERIFIED, since)

    lines = [
        f"📢 گزارش اسپانسر — {label}",
        "─" * 18,
        f"جمع: کلیک {total_clicks:,} | بررسی {total_checks:,} | تأیید {total_ok:,}",
        "",
    ]
    for ch in channels:
        title = (ch.title or "بدون‌نام").strip()
        if title.lstrip("-").isdigit():
            title = "کانال اسپانسری"
        clicks = _count_events_since(session, EVENT_JOIN_CLICK, since, ch.id)
        checks = _count_events_since(session, EVENT_CHECK, since, ch.id)
        ok = _count_events_since(session, EVENT_VERIFIED, since, ch.id)
        flag = "✅" if ch.active else "⏸"
        lines.append(
            f"{flag} [{ch.province or '—'}] «{title}»\n"
            f"   👆 {clicks:,}  ·  🔍 {checks:,}  ·  ✨ {ok:,}"
        )
    return "\n".join(lines)


def games_report(session: Session, period_key: str) -> str:
    label, since = period_since(period_key)
    by_type = (
        session.query(GameSession.game_type, func.count(GameSession.id))
        .filter(GameSession.created_at >= since)
        .group_by(GameSession.game_type)
        .order_by(func.count(GameSession.id).desc())
        .all()
    )
    by_status = (
        session.query(GameSession.status, func.count(GameSession.id))
        .filter(GameSession.created_at >= since)
        .group_by(GameSession.status)
        .all()
    )
    queue_modes = (
        session.query(MatchQueue.queue_mode, func.count(MatchQueue.id))
        .filter(MatchQueue.created_at >= since)
        .group_by(MatchQueue.queue_mode)
        .order_by(func.count(MatchQueue.id).desc())
        .all()
    )

    type_labels = {
        "friends": "دوستانه",
        "group": "گروهی",
        "channel": "کانال",
        "stranger": "غریبه",
        "fake_identity": "هویت جعلی",
        "anonymous": "ناشناس",
        "nearby": "نزدیک",
        "advanced": "پیشرفته",
    }
    mode_labels = {
        "stranger": "غریبه",
        "anonymous": "ناشناس",
        "nearby": "نزدیک",
        "advanced": "پیشرفته",
        "fake": "هویت جعلی",
    }

    lines = [f"🎮 بازی‌ها — {label}", "─" * 18, "", "نوع بازی:"]
    if by_type:
        for gt, n in by_type:
            lines.append(f"• {type_labels.get(gt, gt)}: {n:,}")
    else:
        lines.append("• هیچی")

    lines.append("\nوضعیت:")
    if by_status:
        for st, n in by_status:
            lines.append(f"• {st}: {n:,}")
    else:
        lines.append("• هیچی")

    lines.append("\nورود به صف مچ:")
    if queue_modes:
        for mode, n in queue_modes:
            lines.append(f"• {mode_labels.get(mode, mode)}: {n:,}")
    else:
        lines.append("• هیچی")

    return "\n".join(lines)
