from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from bot.models import User, UserReport, UserRestriction
from bot.texts import fa as T

# Preset durations for admin actions (hours). None = permanent.
RESTRICTION_PRESETS: list[tuple[str, Optional[int]]] = [
    ("1h", 1),
    ("6h", 6),
    ("24h", 24),
    ("7d", 24 * 7),
    ("30d", 24 * 30),
    ("perm", None),
]

REASON_LABELS = {
    "abuse": "رفتار نامناسب",
    "sexual": "محتوای جنسی",
    "spam": "اسپم / تبلیغات",
    "other": "سایر",
}


def _now() -> datetime:
    return datetime.utcnow()


def active_restriction(session: Session, user: User) -> Optional[UserRestriction]:
    """Return the active restriction if play is blocked, else None. Auto-lifts expired temps."""
    rows = (
        session.query(UserRestriction)
        .filter(UserRestriction.user_id == user.id, UserRestriction.active.is_(True))
        .order_by(UserRestriction.id.desc())
        .all()
    )
    now = _now()
    for row in rows:
        if row.kind == "permanent" or row.until is None:
            return row
        if row.until > now:
            return row
        row.active = False
        row.lifted_at = now
    return None


def is_restricted(session: Session, user: User) -> bool:
    return active_restriction(session, user) is not None


def restriction_message(session: Session, user: User) -> Optional[str]:
    row = active_restriction(session, user)
    if not row:
        return None
    reason = (row.reason or "").strip() or "—"
    if row.kind == "permanent" or row.until is None:
        return T.RESTRICTED_PERMANENT.format(reason=reason)
    until = row.until.strftime("%Y-%m-%d %H:%M") if row.until else "—"
    return T.RESTRICTED_TEMP.format(until=until, reason=reason)


def format_restriction_line(row: UserRestriction, user: User | None = None) -> str:
    who = ""
    if user:
        who = f"tg:`{user.telegram_id}` {user.display_name or user.username or ''}\n"
    if row.kind == "permanent" or row.until is None:
        when = "دائمی"
    else:
        when = f"تا {row.until.strftime('%Y-%m-%d %H:%M')}" if row.until else "?"
    reason = (row.reason or "—").strip()
    flag = "✅" if row.active else "⏸"
    return f"{flag} #{row.id} {who}محدودیت: {when}\nدلیل: {reason}"


def create_report(
    session: Session,
    *,
    reporter: User,
    reported: User,
    reason_code: str,
    reason_text: str | None = None,
    session_id: int | None = None,
) -> tuple[UserReport | None, str]:
    if reporter.id == reported.id:
        return None, "self"
    code = reason_code if reason_code in REASON_LABELS else "other"
    if session_id is not None:
        dup = (
            session.query(UserReport)
            .filter(
                UserReport.reporter_id == reporter.id,
                UserReport.reported_id == reported.id,
                UserReport.session_id == session_id,
            )
            .first()
        )
        if dup:
            return None, "duplicate"
    row = UserReport(
        reporter_id=reporter.id,
        reported_id=reported.id,
        session_id=session_id,
        reason_code=code,
        reason_text=(reason_text or "").strip()[:500] or None,
        status="open",
    )
    session.add(row)
    session.flush()
    return row, "ok"


def list_open_reports(session: Session, *, limit: int = 20, offset: int = 0) -> list[UserReport]:
    return (
        session.query(UserReport)
        .filter(UserReport.status == "open")
        .order_by(UserReport.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_open_reports(session: Session) -> int:
    return session.query(UserReport).filter(UserReport.status == "open").count()


def count_reports_against(session: Session, user_id: int) -> int:
    return session.query(UserReport).filter(UserReport.reported_id == user_id).count()


def get_report(session: Session, report_id: int) -> Optional[UserReport]:
    return session.get(UserReport, report_id)


def set_report_status(
    session: Session,
    report: UserReport,
    status: str,
    *,
    admin_tg: int | None = None,
    note: str | None = None,
) -> None:
    report.status = status
    report.reviewed_by = admin_tg
    report.reviewed_at = _now()
    if note is not None:
        report.admin_note = note[:500]


def apply_restriction(
    session: Session,
    user: User,
    *,
    hours: int | None,
    reason: str | None,
    admin_tg: int | None,
    report_id: int | None = None,
) -> UserRestriction:
    # Lift previous actives so one clear restriction is in force
    for old in (
        session.query(UserRestriction)
        .filter(UserRestriction.user_id == user.id, UserRestriction.active.is_(True))
        .all()
    ):
        old.active = False
        old.lifted_at = _now()

    if hours is None:
        kind = "permanent"
        until = None
    else:
        kind = "temp"
        until = _now() + timedelta(hours=int(hours))

    row = UserRestriction(
        user_id=user.id,
        kind=kind,
        until=until,
        reason=(reason or "").strip()[:500] or None,
        active=True,
        created_by=admin_tg,
        report_id=report_id,
    )
    session.add(row)
    session.flush()

    if report_id:
        rep = session.get(UserReport, report_id)
        if rep:
            set_report_status(session, rep, "actioned", admin_tg=admin_tg)

    return row


def lift_restriction(session: Session, restriction_id: int) -> bool:
    row = session.get(UserRestriction, restriction_id)
    if not row or not row.active:
        return False
    row.active = False
    row.lifted_at = _now()
    return True


def list_active_restrictions(session: Session, *, limit: int = 30) -> list[UserRestriction]:
    now = _now()
    rows = (
        session.query(UserRestriction)
        .filter(UserRestriction.active.is_(True))
        .order_by(UserRestriction.id.desc())
        .limit(limit)
        .all()
    )
    active: list[UserRestriction] = []
    for row in rows:
        if row.kind == "permanent" or row.until is None or row.until > now:
            active.append(row)
        else:
            row.active = False
            row.lifted_at = now
    return active


def reason_label(code: str) -> str:
    return REASON_LABELS.get(code, code)


def format_report_detail(session: Session, report: UserReport) -> str:
    reporter = report.reporter or session.get(User, report.reporter_id)
    reported = report.reported or session.get(User, report.reported_id)
    n = count_reports_against(session, report.reported_id)
    restr = active_restriction(session, reported) if reported else None
    restr_line = "بدون محدودیت فعال"
    if restr:
        if restr.kind == "permanent" or restr.until is None:
            restr_line = "محدودیت دائمی فعال"
        else:
            restr_line = f"محدود تا {restr.until.strftime('%Y-%m-%d %H:%M')}"

    def _u(u: User | None, uid: int) -> str:
        if not u:
            return f"id={uid}"
        return f"tg:`{u.telegram_id}` — {u.display_name or u.username or '—'}"

    return (
        f"🚩 گزارش #{report.id}\n"
        f"وضعیت: {report.status}\n"
        f"دلیل: {reason_label(report.reason_code)}\n"
        f"{('توضیح: ' + report.reason_text) if report.reason_text else ''}\n"
        f"گزارش‌دهنده: {_u(reporter, report.reporter_id)}\n"
        f"گزارش‌شده: {_u(reported, report.reported_id)}\n"
        f"کل گزارش‌ها علیه این کاربر: {n}\n"
        f"وضعیت فعلی: {restr_line}\n"
        f"بازی: {report.session_id or '—'}\n"
        f"زمان: {report.created_at.strftime('%Y-%m-%d %H:%M') if report.created_at else '—'}"
    )
