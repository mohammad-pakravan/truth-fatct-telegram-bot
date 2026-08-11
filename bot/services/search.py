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


def admin_search_users(session: Session, query: str, *, limit: int = 25) -> list[User]:
    """Admin search by telegram id, @username, name, city, or province."""
    q = (query or "").strip()
    if not q:
        return []

    raw = q.lstrip("@")
    if raw.isdigit():
        tid = int(raw)
        row = session.query(User).filter(User.telegram_id == tid).one_or_none()
        return [row] if row else []

    like = f"%{q}%"
    rows = (
        session.query(User)
        .filter(
            (User.username.ilike(like))
            | (User.display_name.ilike(like))
            | (User.nickname.ilike(like))
            | (User.city.ilike(like))
            | (User.province.ilike(like))
        )
        .limit(limit * 2)
        .all()
    )
    rows.sort(key=lambda u: u.last_active_at or datetime.min, reverse=True)
    return rows[:limit]


def public_find_users(
    session: Session,
    me: User,
    *,
    gender: str | None,
    province: str | None,
    name_filter: str | None = None,
    limit: int = 30,
) -> list[User]:
    """Public inline/advanced-style find: gender + optional province."""
    from bot.services import users as user_svc

    q = session.query(User).filter(
        User.id != me.id,
        User.allow_stranger_requests.is_(True),
    )
    # Only complete profiles
    q = q.filter(
        User.display_name.isnot(None),
        User.display_name != "",
        User.province.isnot(None),
        User.city.isnot(None),
        User.gender.isnot(None),
        User.age.isnot(None),
    )
    if gender in ("male", "female"):
        q = q.filter(User.gender == gender)
    if province:
        q = q.filter(User.province == province)
    if name_filter:
        like = f"%{name_filter}%"
        q = q.filter(
            (User.display_name.ilike(like))
            | (User.nickname.ilike(like))
            | (User.city.ilike(like))
        )
    rows = q.all()
    rows = [u for u in rows if user_svc.profile_complete(u)]
    rows.sort(key=lambda u: u.last_active_at or datetime.min, reverse=True)
    return rows[:limit]


def parse_gender_province_query(qtext: str) -> dict[str, Any] | None:
    """
    Parse inline find queries like:
      پسر تهران | دختر اصفهان | male تهران | find پسر تهران | جستجو دختر
    Returns dict with gender, province, name_filter — or None if not a find query.
    """
    from bot.provinces import PROVINCES

    raw = (qtext or "").strip()
    if not raw:
        return None

    parts = raw.split()
    head = parts[0].lower()
    rest_parts = parts[1:] if head in (
        "find",
        "search",
        "جستجو",
        "کاربر",
        "users",
        "user",
    ) else parts
    if head in ("find", "search", "جستجو", "کاربر", "users", "user"):
        if not rest_parts:
            return {"gender": None, "province": None, "name_filter": None, "explicit": True}
        blob = " ".join(rest_parts)
    else:
        blob = raw
        # Must look like a gender/province find (not likes/contacts/شروع)
        gender_words = (
            "پسر", "پسرها", "پسران",
            "دختر", "دخترا", "دخترها", "دختران",
            "male", "female", "آقا", "خانم", "مرد", "زن",
        )
        if not any(w in blob for w in gender_words) and not any(
            p in blob for p in PROVINCES
        ):
            return None
        # Avoid stealing likes/contacts
        if head in ("likes", "like", "liked", "لایک", "contacts", "contact", "مخاطب", "مخاطبین"):
            return None

    gender = None
    gmap = {
        "پسرها": "male",
        "پسران": "male",
        "پسر": "male",
        "آقا": "male",
        "مرد": "male",
        "male": "male",
        "دخترها": "female",
        "دختران": "female",
        "دخترا": "female",
        "دختر": "female",
        "خانم": "female",
        "زن": "female",
        "female": "female",
    }
    # Longer keys first so «دخترا» wins over «دختر»
    gmap_items = sorted(gmap.items(), key=lambda kv: len(kv[0]), reverse=True)
    tokens = blob.replace("،", " ").split()
    leftover: list[str] = []
    province = None
    # Longest province match first
    sorted_provs = sorted(PROVINCES, key=len, reverse=True)
    remaining = blob
    for gword, gcode in gmap_items:
        if gword in tokens or gword in remaining:
            gender = gcode
            remaining = remaining.replace(gword, " ", 1)
            break
    remaining = " ".join(remaining.split())
    for prov in sorted_provs:
        if prov in remaining:
            province = prov
            remaining = remaining.replace(prov, " ", 1)
            break
    name_filter = " ".join(remaining.split()) or None

    # Require at least gender or province for implicit queries
    if gender is None and province is None and name_filter is None:
        return None
    if gender is None and province is None and head not in (
        "find",
        "search",
        "جستجو",
        "کاربر",
        "users",
        "user",
    ):
        # bare name without gender/province — don't hijack
        return None

    return {
        "gender": gender,
        "province": province,
        "name_filter": name_filter,
        "explicit": head in ("find", "search", "جستجو", "کاربر", "users", "user"),
    }
