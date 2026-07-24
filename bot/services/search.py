from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from bot.models import User


def search_partners(
    session: Session,
    me: User,
    *,
    gender: str,
    provinces: list[str],
    age_from: Optional[int],
    age_to: Optional[int],
    last_seen_hours: Optional[int],
    sort_by: str,
    limit: int = 10,
) -> list[User]:
    q = session.query(User).filter(
        User.id != me.id,
        User.allow_stranger_requests.is_(True),
        User.gender == gender,
    )
    if provinces and len(provinces) < 31:
        q = q.filter(User.province.in_(provinces))
    if age_from is not None:
        q = q.filter(User.age >= age_from)
    if age_to is not None:
        q = q.filter(User.age <= age_to)
    if last_seen_hours is not None:
        cutoff = datetime.utcnow() - timedelta(hours=last_seen_hours)
        q = q.filter(User.last_active_at.isnot(None), User.last_active_at >= cutoff)

    rows = q.all()

    def sort_key(u: User):
        if sort_by == "online":
            return u.last_active_at or datetime.min
        if sort_by == "age_asc":
            return u.age or 999
        if sort_by == "age_desc":
            return -(u.age or 0)
        if sort_by == "near":
            # same province first
            same = 0 if (u.province and me.province and u.province == me.province) else 1
            return (same, u.last_active_at or datetime.min)
        return u.last_active_at or datetime.min

    reverse = sort_by in ("online", "near", "age_desc")
    if sort_by == "age_asc":
        reverse = False
    if sort_by == "online":
        reverse = True
    if sort_by == "near":
        rows.sort(key=sort_key)
    elif sort_by == "age_asc":
        rows.sort(key=lambda u: u.age or 999)
    elif sort_by == "age_desc":
        rows.sort(key=lambda u: u.age or 0, reverse=True)
    else:
        rows.sort(key=lambda u: u.last_active_at or datetime.min, reverse=True)

    return rows[:limit]


def filters_summary(prefs: dict[str, Any]) -> str:
    gender_map = {"male": "پسر 👦", "female": "دختر 👧"}
    gender = gender_map.get(prefs.get("gender", ""), "—")

    provinces = prefs.get("provinces") or []
    if not provinces or len(provinces) >= 31:
        province_txt = "همه ایران 🇮🇷"
    elif len(provinces) <= 3:
        province_txt = "، ".join(provinces)
    else:
        province_txt = f"{len(provinces)} استان انتخاب‌شده"

    age_from = prefs.get("age_from")
    age_to = prefs.get("age_to")
    if (age_from is None and age_to is None) or (age_from in (0, None) and age_to in (100, None)):
        age_txt = "مهم نیست ✨"
    else:
        left = "بدون حد" if age_from is None else str(age_from)
        right = "بدون حد" if age_to is None else str(age_to)
        age_txt = f"{left} تا {right}"

    hours = prefs.get("last_seen_hours")
    last_map = {
        1: "تا ۱ ساعت پیش",
        6: "تا ۶ ساعت پیش",
        24: "تا ۱ روز پیش",
        48: "تا ۲ روز پیش",
        72: "تا ۳ روز پیش",
        168: "تا ۱ هفته پیش",
    }
    last_txt = last_map.get(hours, "—") if hours else "—"

    sort_map = {
        "online": "آخرین آنلاین",
        "near": "نزدیک‌ترین",
        "age_desc": "بیشترین سن",
        "age_asc": "کمترین سن",
    }
    sort_txt = sort_map.get(prefs.get("sort_by", ""), "")

    lines = [
        "✨ فیلترهای انتخابی تو",
        "",
        f"🚻  جنسیت: {gender}",
        f"🗺  استان: {province_txt}",
    ]
    if age_from is not None or age_to is not None or prefs.get("age_step_done"):
        lines.append(f"🎂  بازه سنی: {age_txt}")
    if hours:
        lines.append(f"🟢  آخرین حضور: {last_txt}")
    if sort_txt:
        lines.append(f"📊  ترتیب نمایش: {sort_txt}")
    return "\n".join(lines)
