from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Literal, Optional

from sqlalchemy.orm import Session

from bot.config import QUESTIONS_PATH
from bot.models import QuestionBankItem, UserSubmittedQuestion

Kind = Literal["truth", "dare"]

BUCKETS = ("female", "female_18", "male", "male_18")
BUCKET_LABELS = {
    "female": "👧 دختر",
    "female_18": "👩 دختر +۱۸",
    "male": "👦 پسر",
    "male_18": "👨 پسر +۱۸",
}

# Group/friends category keys → (kind, bucket_mode, label)
# bucket_mode: female|female_18|male|male_18|normal|lucky
CATEGORIES: dict[str, tuple[str, str, str]] = {
    "tf18": ("truth", "female_18", "👩🏻 حقیقت دختر +18"),
    "tm18": ("truth", "male_18", "👨🏻 حقیقت پسر +18"),
    "df18": ("dare", "female_18", "🙅‍♀️ جرعت دختر +18"),
    "dm18": ("dare", "male_18", "🙅‍♂️ جرعت پسر +18"),
    "tn": ("truth", "normal", "🙃 حقیقت عادی"),
    "dn": ("dare", "normal", "🤙 جرعت عادی"),
    "lucky": ("any", "lucky", "😈 شانسی"),
}

_DEFAULT = {
    "truth": [
        "آخرین باری که دروغ گفتی چی بود؟",
        "بزرگ‌ترین ترس زندگیت چیه؟",
        "اگه فردا همه پول‌دار بشی اولین کارت چیه؟",
        "یکی از خجالت‌آورترین خاطراتت رو بگو.",
        "آخرین کسی که بهش پیام دادی کی بود و چی گفتی؟",
        "بیشتر از همه از کدوم عادتت خجالت می‌کشی؟",
        "اگه می‌تونستی یه چیز از گذشته‌ت عوض کنی چی بود؟",
        "تا حالا عاشق کسی شدی که بهت نگفته باشه؟",
        "بدترین هدیه‌ای که گرفتی چی بوده؟",
        "یه راز کوچیک که هیچ‌کس نمی‌دونه بگو.",
    ],
    "dare": [
        "یه ایموجی رندم بفرست و بگو چرا همون رو انتخاب کردی.",
        "اسمت رو برعکس بنویس و با همون خودت رو معرفی کن.",
        "یه تعریف اغراق‌آمیز از طرف مقابلت بگو.",
        "۳۰ ثانیه فقط با سوال حرف بزن.",
        "یه جوک بد بگو عمداً.",
        "بگو اگه حیوون بودی چی بودی و چرا.",
        "یه قانون مسخره برای ادامه بازی بساز.",
        "آخرین استیکری که ذخیره کردی رو بفرست.",
        "با لحن رسمی و جدی یه جمله خیلی پیش‌پاافتاده بگو.",
        "یه چالش دو دقیقه‌ای برای طرف مقابل پیشنهاد بده.",
    ],
}


def _pick_from_pool(pool: list[str], exclude: set[str] | None = None) -> str:
    exclude = {x.strip() for x in (exclude or set()) if x and x.strip()}
    usable = [p for p in pool if p and p.strip() and p.strip() not in exclude]
    if usable:
        return random.choice(usable)
    usable = [p for p in pool if p and p.strip()]
    return random.choice(usable)


def resolve_bucket(gender: Optional[str], age: Optional[int]) -> str:
    adult = bool(age is not None and int(age) >= 18)
    if gender == "female":
        return "female_18" if adult else "female"
    if gender == "male":
        return "male_18" if adult else "male"
    # Unknown gender: prefer adult pool if age known, else male as generic fallback
    if adult:
        return "male_18"
    return "male"


def parse_question_list(raw: str) -> list[str]:
    """Split on Persian/Arabic/Latin commas and newlines; trim empties."""
    parts = re.split(r"[،,,\n]+", raw or "")
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        q = " ".join(p.strip().split())
        if len(q) < 2:
            continue
        if q in seen:
            continue
        seen.add(q)
        out.append(q[:500])
    return out


def count_bucket(session: Session, bucket: str, *, kind: str | None = None) -> int:
    q = session.query(QuestionBankItem).filter(
        QuestionBankItem.bucket == bucket,
        QuestionBankItem.active.is_(True),
    )
    if kind and kind != "any":
        q = q.filter(QuestionBankItem.kind.in_([kind, "any"]))
    return q.count()


def counts_summary(session: Session) -> dict[str, int]:
    return {b: count_bucket(session, b) for b in BUCKETS}


def add_questions(
    session: Session,
    *,
    bucket: str,
    questions: list[str],
    kind: str = "any",
    created_by: int | None = None,
    replace: bool = False,
) -> int:
    if bucket not in BUCKETS:
        raise ValueError("bad_bucket")
    if replace:
        (
            session.query(QuestionBankItem)
            .filter(QuestionBankItem.bucket == bucket, QuestionBankItem.kind == kind)
            .update({"active": False}, synchronize_session=False)
        )
    n = 0
    for text in questions:
        session.add(
            QuestionBankItem(
                bucket=bucket,
                kind=kind,
                text=text,
                active=True,
                created_by=created_by,
            )
        )
        n += 1
    session.flush()
    return n


def clear_bucket(session: Session, bucket: str) -> int:
    rows = (
        session.query(QuestionBankItem)
        .filter(QuestionBankItem.bucket == bucket, QuestionBankItem.active.is_(True))
        .all()
    )
    for r in rows:
        r.active = False
    session.flush()
    return len(rows)


def list_bucket(session: Session, bucket: str, *, limit: int = 30) -> list[str]:
    rows = (
        session.query(QuestionBankItem.text)
        .filter(QuestionBankItem.bucket == bucket, QuestionBankItem.active.is_(True))
        .order_by(QuestionBankItem.id.desc())
        .limit(limit)
        .all()
    )
    return [r[0] for r in rows]


def log_user_submitted_question(
    session: Session,
    *,
    session_id: int | None,
    round_id: int | None,
    submitter_user_id: int | None,
    target_user_id: int | None,
    kind: str,
    suggested_bucket: str | None,
    text: str,
) -> UserSubmittedQuestion:
    row = UserSubmittedQuestion(
        session_id=session_id,
        round_id=round_id,
        submitter_user_id=submitter_user_id,
        target_user_id=target_user_id,
        kind=kind,
        suggested_bucket=suggested_bucket,
        text=text[:500],
    )
    session.add(row)
    session.flush()
    return row


def list_user_submitted(session: Session, *, limit: int = 20) -> list[UserSubmittedQuestion]:
    return (
        session.query(UserSubmittedQuestion)
        .filter(UserSubmittedQuestion.added_to_bank.is_(False))
        .order_by(UserSubmittedQuestion.id.desc())
        .limit(limit)
        .all()
    )


def count_user_submitted_pending(session: Session) -> int:
    return (
        session.query(UserSubmittedQuestion)
        .filter(UserSubmittedQuestion.added_to_bank.is_(False))
        .count()
    )


def get_user_submitted(session: Session, question_id: int) -> UserSubmittedQuestion | None:
    return session.get(UserSubmittedQuestion, question_id)


def add_submitted_to_bank(
    session: Session,
    *,
    submitted_id: int,
    admin_tg: int | None,
) -> tuple[UserSubmittedQuestion | None, QuestionBankItem | None]:
    row = session.get(UserSubmittedQuestion, submitted_id)
    if not row or row.added_to_bank:
        return None, None
    bucket = row.suggested_bucket or "male"
    if bucket not in BUCKETS:
        bucket = "male"
    item = QuestionBankItem(
        bucket=bucket,
        kind=row.kind if row.kind in ("truth", "dare") else "any",
        text=row.text,
        active=True,
        created_by=admin_tg,
    )
    session.add(item)
    session.flush()
    row.added_to_bank = True
    row.added_bucket = bucket
    row.added_bank_item_id = item.id
    row.reviewed_by = admin_tg
    from datetime import datetime

    row.reviewed_at = datetime.utcnow()
    session.flush()
    return row, item


def _file_bank() -> dict:
    path = Path(QUESTIONS_PATH)
    if path.exists():
        with path.open(encoding="utf-8-sig") as f:
            data = json.load(f)
        return {
            "truth": data.get("truth") or _DEFAULT["truth"],
            "dare": data.get("dare") or _DEFAULT["dare"],
        }
    return _DEFAULT


def random_prompt(
    kind: Kind,
    *,
    gender: Optional[str] = None,
    age: Optional[int] = None,
    session: Session | None = None,
    bucket: str | None = None,
    exclude: set[str] | None = None,
) -> str:
    """Pick a prompt: prefer gender DB bank, else legacy JSON / defaults."""
    exclude = {x.strip() for x in (exclude or set()) if x and x.strip()}

    if bucket and bucket in BUCKETS:
        resolved = bucket
    else:
        resolved = resolve_bucket(gender, age)
    if session is not None:
        rows = (
            session.query(QuestionBankItem.text)
            .filter(
                QuestionBankItem.bucket == resolved,
                QuestionBankItem.active.is_(True),
                QuestionBankItem.kind.in_([kind, "any"]),
            )
            .all()
        )
        pool = [r[0] for r in rows if r[0]]
        if pool:
            return _pick_from_pool(pool, exclude)
        # Soft fallback: same gender other age band
        alt = {
            "female": "female_18",
            "female_18": "female",
            "male": "male_18",
            "male_18": "male",
        }.get(resolved)
        if alt:
            rows = (
                session.query(QuestionBankItem.text)
                .filter(
                    QuestionBankItem.bucket == alt,
                    QuestionBankItem.active.is_(True),
                    QuestionBankItem.kind.in_([kind, "any"]),
                )
                .all()
            )
            pool = [r[0] for r in rows if r[0]]
            if pool:
                return _pick_from_pool(pool, exclude)

    bank = _file_bank()
    return _pick_from_pool(bank.get(kind) or _DEFAULT[kind], exclude)


def prompt_for_category(
    session: Session, cat_key: str, *, exclude: set[str] | None = None
) -> tuple[str, str, str]:
    """Return (kind, category_label, prompt_text) for a group category key."""
    meta = CATEGORIES.get(cat_key)
    if not meta:
        meta = CATEGORIES["lucky"]
        cat_key = "lucky"
    kind, mode, label = meta
    if mode == "lucky":
        kind = random.choice(["truth", "dare"])
        bucket = random.choice(list(BUCKETS))
        text = random_prompt(
            kind, session=session, bucket=bucket, exclude=exclude
        )  # type: ignore[arg-type]
        return kind, label, text
    if mode == "normal":
        pools: list[str] = []
        for bucket in ("female", "male"):
            rows = (
                session.query(QuestionBankItem.text)
                .filter(
                    QuestionBankItem.bucket == bucket,
                    QuestionBankItem.active.is_(True),
                    QuestionBankItem.kind.in_([kind, "any"]),
                )
                .all()
            )
            pools.extend(r[0] for r in rows if r[0])
        if pools:
            return kind, label, _pick_from_pool(pools, exclude)
        text = random_prompt(kind, session=session, exclude=exclude)  # type: ignore[arg-type]
        return kind, label, text
    text = random_prompt(
        kind, session=session, bucket=mode, exclude=exclude
    )  # type: ignore[arg-type]
    return kind, label, text
