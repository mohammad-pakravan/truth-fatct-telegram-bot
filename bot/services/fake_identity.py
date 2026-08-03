from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from bot.config import (
    FAKE_ASSIGNMENT_COOLDOWN_DAYS,
    FAKE_POOLS_PATH,
    IDENTITIES_PATH,
)
from bot.models import FakeIdentity, UserFakeAssignment
from bot.texts import fa as T

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_pools() -> dict:
    path = Path(FAKE_POOLS_PATH)
    if not path.exists():
        logger.warning("fake pools missing at %s", path)
        return {}
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def pool_stats() -> dict:
    """Rough combinatorial capacity of the generator."""
    p = _load_pools()
    if not p:
        return {"approx_combos": 0}
    n_names = max(len(p.get("male_names", [])), len(p.get("female_names", [])))
    n_city = len(p.get("cities", [])) or 1
    n_age = len(p.get("ages", [])) or 1
    n_job = max(len(p.get("jobs_male", [])), len(p.get("jobs_female", []))) or 1
    n_hobby = len(p.get("hobbies", [])) or 1
    n_trait = len(p.get("traits", [])) or 1
    n_dislike = len(p.get("dislikes", [])) or 1
    approx = n_names * n_city * n_age * n_job * n_hobby * n_trait * n_dislike
    return {
        "names": n_names,
        "cities": n_city,
        "ages": n_age,
        "jobs": n_job,
        "approx_combos": approx,
    }


def seed_from_json(session: Session, path: Optional[Path] = None) -> int:
    """Optional legacy seed — generator does not require it."""
    path = path or Path(IDENTITIES_PATH)
    if not path.exists():
        return 0
    existing = session.query(FakeIdentity).filter_by(generated=False).count()
    if existing > 0:
        return 0
    with path.open(encoding="utf-8-sig") as f:
        items = json.load(f)
    count = 0
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
            generated=False,
            fingerprint=_fingerprint(
                item["name"], item["gender"], int(item["age"]), item["city"], item["job"], item.get("bio", "")
            ),
        )
        session.add(fi)
        count += 1
    session.flush()
    return count


def _fingerprint(name: str, gender: str, age: int, city: str, job: str, bio: str = "") -> str:
    # Include bio snippet so two same name/city/job mixes still differ
    raw = f"{name}|{gender}|{age}|{city}|{job}|{bio[:48]}".strip().lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _pick(seq: list, rng: random.Random):
    return rng.choice(seq) if seq else ""


def _pick_n(seq: list, n: int, rng: random.Random) -> list:
    if not seq:
        return []
    if len(seq) <= n:
        return list(seq)
    return rng.sample(seq, n)


def generate_persona(gender: Optional[str] = None, *, rng: Optional[random.Random] = None) -> dict:
    """
    Build a mixed persona from component pools (names, ages, cities, templates + emoji).
    gender: male | female | None (random)
    """
    rng = rng or random.Random()
    pools = _load_pools()
    if not pools:
        raise RuntimeError("fake_pools_empty")

    if gender not in ("male", "female"):
        gender = rng.choice(["male", "female"])

    names = pools["male_names"] if gender == "male" else pools["female_names"]
    jobs = pools["jobs_male"] if gender == "male" else pools["jobs_female"]

    name = _pick(names, rng)
    age = _pick(pools.get("ages") or list(range(18, 36)), rng)
    city = _pick(pools.get("cities") or ["تهران"], rng)
    job = _pick(jobs or ["آزاد"], rng)
    hobby = _pick(pools.get("hobbies") or ["کافه"], rng)
    habit = _pick(pools.get("habits") or ["آروم زندگی می‌کنه"], rng)
    traits = _pick_n(pools.get("traits") or ["آروم"], 2, rng)
    while len(traits) < 2:
        traits.append(traits[0] if traits else "آروم")
    quirk = _pick(pools.get("quirks") or ["جزئیات‌گراست"], rng)
    dislikes = _pick_n(pools.get("dislikes") or ["ترافیک"], 3, rng)
    while len(dislikes) < 3:
        dislikes.append(dislikes[0] if dislikes else "تأخیر")
    emojis = pools.get("emojis") or ["✨"]
    e1, e2 = _pick(emojis, rng), _pick(emojis, rng)

    bio_t = _pick(pools.get("bio_templates") or ["{e1} {hobby}."], rng)
    pers_t = _pick(pools.get("personality_templates") or ["{t1} و {t2}."], rng)
    d_t = _pick(pools.get("dislike_templates") or ["{d1}، {d2}، {d3}"], rng)

    bio = bio_t.format(e1=e1, e2=e2, hobby=hobby, habit=habit)
    personality = pers_t.format(
        t1=traits[0], t2=traits[1], quirk=quirk, e1=e1, e2=e2
    )
    dislike_text = d_t.format(d1=dislikes[0], d2=dislikes[1], d3=dislikes[2])

    # Keep readable length (not too short / not essay-long)
    if len(bio) < 40:
        bio = f"{bio} {e2} اهل جزئیاته."
    if len(bio) > 180:
        bio = bio[:177] + "…"
    if len(personality) > 160:
        personality = personality[:157] + "…"
    if len(dislike_text) > 120:
        dislike_text = dislike_text[:117] + "…"

    return {
        "name": name,
        "gender": gender,
        "age": int(age),
        "city": city,
        "job": job,
        "bio": bio,
        "personality": personality,
        "dislikes": dislike_text,
        "fingerprint": _fingerprint(name, gender, int(age), city, job, bio),
    }


def _blocked_fingerprints(session: Session, user_id: int) -> set[str]:
    cutoff = datetime.utcnow() - timedelta(days=FAKE_ASSIGNMENT_COOLDOWN_DAYS)
    rows = (
        session.query(UserFakeAssignment.fingerprint)
        .filter(
            UserFakeAssignment.user_id == user_id,
            UserFakeAssignment.revealed_at.is_(None),
            UserFakeAssignment.assigned_at >= cutoff,
        )
        .all()
    )
    return {r[0] for r in rows}


def acquire(
    session: Session,
    gender: Optional[str] = None,
    exclude_ids: Optional[set[int]] = None,
    *,
    user_id: Optional[int] = None,
    max_tries: int = 40,
) -> Optional[FakeIdentity]:
    """
    Generate a fresh mixed identity and persist it.
    Avoids fingerprints this user already has (until revealed / cooldown).
    """
    blocked: set[str] = set()
    if user_id is not None:
        blocked = _blocked_fingerprints(session, user_id)

    exclude_ids = exclude_ids or set()
    last_err = None
    for _ in range(max_tries):
        try:
            persona = generate_persona(gender)
        except RuntimeError as exc:
            last_err = exc
            break
        if persona["fingerprint"] in blocked:
            continue

        fi = FakeIdentity(
            name=persona["name"],
            gender=persona["gender"],
            age=persona["age"],
            city=persona["city"],
            job=persona["job"],
            bio=persona["bio"],
            personality=persona["personality"],
            dislikes=persona["dislikes"],
            fingerprint=persona["fingerprint"],
            generated=True,
            used_count=1,
            active=True,
        )
        session.add(fi)
        session.flush()

        if fi.id in exclude_ids:
            # extremely unlikely for new row; regenerate
            session.delete(fi)
            session.flush()
            continue

        if user_id is not None:
            # Upsert-like: if unique constraint hits, retry
            existing = (
                session.query(UserFakeAssignment)
                .filter_by(user_id=user_id, fingerprint=persona["fingerprint"])
                .one_or_none()
            )
            if existing and existing.revealed_at is None:
                session.delete(fi)
                session.flush()
                blocked.add(persona["fingerprint"])
                continue
            if existing and existing.revealed_at is not None:
                existing.fake_identity_id = fi.id
                existing.assigned_at = datetime.utcnow()
                existing.revealed_at = None
            else:
                session.add(
                    UserFakeAssignment(
                        user_id=user_id,
                        fake_identity_id=fi.id,
                        fingerprint=persona["fingerprint"],
                    )
                )
            session.flush()

        return fi

    logger.warning("fake acquire failed after tries user_id=%s err=%s", user_id, last_err)
    return None


def reveal_for_user(session: Session, user_id: int, fake_identity_id: Optional[int]) -> None:
    """Mark assignment revealed so this mix can return later."""
    if not fake_identity_id:
        return
    now = datetime.utcnow()
    rows = (
        session.query(UserFakeAssignment)
        .filter_by(user_id=user_id, fake_identity_id=fake_identity_id)
        .all()
    )
    if not rows:
        fi = session.get(FakeIdentity, fake_identity_id)
        if fi and fi.fingerprint:
            rows = (
                session.query(UserFakeAssignment)
                .filter_by(user_id=user_id, fingerprint=fi.fingerprint)
                .all()
            )
    for row in rows:
        if row.revealed_at is None:
            row.revealed_at = now
    session.flush()


def reveal_game_fakes(session: Session, players) -> None:
    """After final guess phase, free each player's used fake for future reuse."""
    for p in players:
        if p.identity_mode == "fake" and p.fake_identity_id:
            reveal_for_user(session, p.user_id, p.fake_identity_id)


def _gender_fa(gender: str) -> str:
    return {"male": "پسر", "female": "دختر"}.get(gender, gender)


def format_card(fi: FakeIdentity) -> str:
    return T.FAKE_CARD.format(
        name=fi.name,
        gender=_gender_fa(fi.gender),
        age=fi.age,
        city=fi.city,
        job=fi.job,
        bio=fi.bio,
        personality=fi.personality,
        dislikes=fi.dislikes,
    )


def format_card_public(fi: FakeIdentity) -> str:
    return T.FAKE_CARD_PUBLIC.format(
        name=fi.name,
        gender=_gender_fa(fi.gender),
        age=fi.age,
        city=fi.city,
        job=fi.job,
        bio=fi.bio,
        personality=fi.personality,
        dislikes=fi.dislikes,
    )


def format_card_body(fi: FakeIdentity) -> str:
    return format_card_public(fi)
