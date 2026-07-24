from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from bot.config import IDENTITIES_PATH
from bot.models import FakeIdentity
from bot.texts import fa as T


def seed_from_json(session: Session, path: Optional[Path] = None) -> int:
    path = path or Path(IDENTITIES_PATH)
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig") as f:
        items = json.load(f)
    count = 0
    existing = session.query(FakeIdentity).count()
    if existing > 0:
        return 0
    for item in items:
        fi = FakeIdentity(
            name=item["name"],
            gender=item["gender"],
            age=int(item["age"]),
            city=item["city"],
            job=item["job"],
            bio=item["bio"],
            personality=item["personality"],
            dislikes=item["dislikes"],
        )
        session.add(fi)
        count += 1
    session.flush()
    return count


def acquire(
    session: Session,
    gender: Optional[str] = None,
    exclude_ids: Optional[set[int]] = None,
) -> Optional[FakeIdentity]:
    q = session.query(FakeIdentity).filter_by(active=True)
    if gender in ("male", "female"):
        q = q.filter_by(gender=gender)
    rows = q.all()
    if exclude_ids:
        rows = [r for r in rows if r.id not in exclude_ids]
    if not rows:
        return None
    # prefer less-used
    rows.sort(key=lambda r: (r.used_count, random.random()))
    chosen = rows[0]
    chosen.used_count += 1
    session.flush()
    return chosen


def format_card(fi: FakeIdentity) -> str:
    gender_map = {"male": "پسر", "female": "دختر"}
    return T.FAKE_CARD.format(
        name=fi.name,
        gender=gender_map.get(fi.gender, fi.gender),
        age=fi.age,
        city=fi.city,
        job=fi.job,
        bio=fi.bio,
        personality=fi.personality,
        dislikes=fi.dislikes,
    )
