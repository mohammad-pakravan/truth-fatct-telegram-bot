from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from bot.config import MATCH_BATCH_SIZE, MATCH_QUEUE_TTL_MINUTES
from bot.db import engine
from bot.models import MatchQueue, User
from bot.services import game_engine
from bot.services.geo import within_radius
from bot.services.users import profile_complete

logger = logging.getLogger(__name__)

STATUS_WAITING = "waiting"
STATUS_MATCHING = "matching"  # short-lived claim while pairing
STATUS_MATCHED = "matched"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"

# Postgres transaction-scoped advisory lock — serializes all match claims
_PG_MATCH_LOCK_KEY = 87429103
_SQLITE_MATCH_LOCK = threading.Lock()


@dataclass
class MatchResult:
    game_id: int
    user_a_id: int
    user_b_id: int
    user_a_tg: int
    user_b_tg: int


def _now() -> datetime:
    return datetime.utcnow()


def _expires_at() -> datetime:
    return _now() + timedelta(minutes=MATCH_QUEUE_TTL_MINUTES)


def _is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


def _provinces_list(row: MatchQueue) -> list[str]:
    if not row.provinces_json:
        return []
    try:
        data = json.loads(row.provinces_json)
        return [str(x) for x in data] if isinstance(data, list) else []
    except Exception:
        return []


def _dump_provinces(provinces: Optional[list[str]]) -> Optional[str]:
    if not provinces:
        return None
    return json.dumps(list(provinces), ensure_ascii=False)


@contextmanager
def match_section() -> Iterator[None]:
    """
    Wrap around the whole DB transaction for non-Postgres (SQLite).
    On Postgres, pg_advisory_xact_lock inside the transaction is enough
    (held until commit). On SQLite we hold a process mutex until after commit.
    """
    if _is_postgres():
        yield
        return
    with _SQLITE_MATCH_LOCK:
        yield


def _acquire_db_match_lock(session: Session) -> None:
    if _is_postgres():
        session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"),
            {"k": _PG_MATCH_LOCK_KEY},
        )


@contextmanager
def match_lock(session: Session) -> Iterator[None]:
    """Backward-compatible name: acquire DB-level match lock on this session."""
    _acquire_db_match_lock(session)
    yield


def is_waiting(session: Session, user: User) -> bool:
    row = (
        session.query(MatchQueue)
        .filter_by(user_id=user.id, status=STATUS_WAITING)
        .one_or_none()
    )
    if not row:
        return False
    if row.expires_at and row.expires_at < _now():
        row.status = STATUS_EXPIRED
        session.delete(row)
        return False
    return True


def waiting_count(session: Session) -> int:
    return (
        session.query(MatchQueue)
        .filter(
            MatchQueue.status == STATUS_WAITING,
            or_(MatchQueue.expires_at.is_(None), MatchQueue.expires_at >= _now()),
        )
        .count()
    )


def queue_position(session: Session, user: User) -> int:
    me = (
        session.query(MatchQueue)
        .filter_by(user_id=user.id, status=STATUS_WAITING)
        .one_or_none()
    )
    if not me:
        return 0
    older = (
        session.query(MatchQueue)
        .filter(
            MatchQueue.status == STATUS_WAITING,
            MatchQueue.created_at <= me.created_at,
            or_(MatchQueue.expires_at.is_(None), MatchQueue.expires_at >= _now()),
        )
        .count()
    )
    return max(1, older)


def enqueue(
    session: Session,
    user: User,
    *,
    same_city_only: bool,
    preferred_gender: Optional[str],
    age_from: Optional[int],
    age_to: Optional[int],
    require_identity: bool,
    play_anonymous: bool = False,
    use_fake_identity: bool = False,
    fake_identity_id: Optional[int] = None,
    identity_mode: str = "real",
    queue_mode: str = "stranger",
    provinces: Optional[list[str]] = None,
    radius_km: Optional[int] = None,
) -> MatchQueue:
    """Put user in waiting queue (replaces any previous queue row)."""
    if game_engine.active_session_for_user(session, user):
        raise RuntimeError("already_in_game")

    existing = session.query(MatchQueue).filter_by(user_id=user.id).one_or_none()
    if existing:
        # Never steal a row that another worker is mid-claiming
        if existing.status == STATUS_MATCHING:
            raise RuntimeError("match_in_progress")
        session.delete(existing)
        session.flush()

    row = MatchQueue(
        user_id=user.id,
        status=STATUS_WAITING,
        queue_mode=queue_mode,
        same_city_only=same_city_only,
        preferred_gender=preferred_gender or "any",
        age_from=age_from,
        age_to=age_to,
        radius_km=radius_km,
        provinces_json=_dump_provinces(provinces),
        require_identity=require_identity,
        play_anonymous=play_anonymous,
        use_fake_identity=use_fake_identity,
        fake_identity_id=fake_identity_id,
        identity_mode=identity_mode,
        expires_at=_expires_at(),
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    session.flush()
    return row


def cancel(session: Session, user: User) -> bool:
    row = session.query(MatchQueue).filter_by(user_id=user.id).one_or_none()
    if not row:
        return False
    if row.status == STATUS_MATCHING:
        # Pairing in progress — do not cancel mid-claim
        return False
    was_waiting = row.status == STATUS_WAITING
    session.delete(row)
    session.flush()
    return was_waiting


def expire_stale(session: Session) -> int:
    now = _now()
    rows = (
        session.query(MatchQueue)
        .filter(
            MatchQueue.status == STATUS_WAITING,
            MatchQueue.expires_at.isnot(None),
            MatchQueue.expires_at < now,
        )
        .all()
    )
    for row in rows:
        row.status = STATUS_EXPIRED
        session.delete(row)
    if rows:
        session.flush()
    return len(rows)


def cleanup_stale_matching(session: Session, older_than_seconds: int = 30) -> int:
    """Recover rows stuck in 'matching' if a worker died mid-pair."""
    cutoff = _now() - timedelta(seconds=older_than_seconds)
    rows = (
        session.query(MatchQueue)
        .filter(
            MatchQueue.status == STATUS_MATCHING,
            MatchQueue.updated_at.isnot(None),
            MatchQueue.updated_at < cutoff,
        )
        .all()
    )
    for row in rows:
        logger.warning("Resetting stale matching claim queue_id=%s user_id=%s", row.id, row.user_id)
        row.status = STATUS_WAITING
        row.updated_at = _now()
    if rows:
        session.flush()
    return len(rows)


def _compatible(a: MatchQueue, ua: User, b: MatchQueue, ub: User) -> bool:
    if not profile_complete(ua) or not profile_complete(ub):
        return False

    if not ub.allow_stranger_requests or not ua.allow_stranger_requests:
        return False

    if a.play_anonymous and not ub.allow_anonymous_requests:
        return False
    if b.play_anonymous and not ua.allow_anonymous_requests:
        return False

    # Identified seekers can still match anonymous seekers if they allow it
    # (handled above). Both-anonymous or both-identified also OK.
    # Block only when one requires identity and the other hides / plays anonymous.
    if a.require_identity and (b.play_anonymous or not ub.show_identity):
        return False
    if b.require_identity and (a.play_anonymous or not ua.show_identity):
        return False

    if a.preferred_gender and a.preferred_gender != "any":
        if ub.gender != a.preferred_gender:
            return False
    if b.preferred_gender and b.preferred_gender != "any":
        if ua.gender != b.preferred_gender:
            return False

    if a.same_city_only:
        if not ua.city or not ub.city or ua.city != ub.city:
            return False
    if b.same_city_only:
        if not ua.city or not ub.city or ua.city != ub.city:
            return False

    if a.radius_km is not None or b.radius_km is not None:
        if a.radius_km is None or b.radius_km is None:
            return False
        limit = min(a.radius_km, b.radius_km)
        if not within_radius(ua.latitude, ua.longitude, ub.latitude, ub.longitude, limit):
            return False

    a_provs = _provinces_list(a)
    b_provs = _provinces_list(b)
    if a_provs and (not ub.province or ub.province not in a_provs):
        return False
    if b_provs and (not ua.province or ua.province not in b_provs):
        return False

    if a.age_from is not None and (ub.age is None or ub.age < a.age_from):
        return False
    if a.age_to is not None and (ub.age is None or ub.age > a.age_to):
        return False
    if b.age_from is not None and (ua.age is None or ua.age < b.age_from):
        return False
    if b.age_to is not None and (ua.age is None or ua.age > b.age_to):
        return False

    if a.use_fake_identity != b.use_fake_identity:
        return False

    return True


def _claim_pair_atomic(session: Session, id_a: int, id_b: int) -> bool:
    """
    Atomically move two waiting rows to 'matching'.
    Must be called while holding match_lock().
    Locks rows in ascending id order to prevent deadlocks.
    Returns True only if BOTH were still waiting.
    """
    if id_a == id_b:
        return False
    first, second = sorted((id_a, id_b))
    now = _now()

    q = (
        session.query(MatchQueue)
        .filter(MatchQueue.id.in_([first, second]))
        .order_by(MatchQueue.id)
    )
    if _is_postgres():
        q = q.with_for_update()
    else:
        try:
            q = q.with_for_update()
        except Exception:
            pass

    rows = q.all()
    if len(rows) != 2:
        return False
    if any(r.status != STATUS_WAITING for r in rows):
        return False
    if any(r.expires_at and r.expires_at < now for r in rows):
        return False

    for r in rows:
        r.status = STATUS_MATCHING
        r.updated_at = now
    session.flush()
    return True


def _release_claim(session: Session, id_a: int, id_b: int) -> None:
    now = _now()
    rows = (
        session.query(MatchQueue)
        .filter(
            MatchQueue.id.in_([id_a, id_b]),
            MatchQueue.status == STATUS_MATCHING,
        )
        .all()
    )
    for r in rows:
        r.status = STATUS_WAITING
        r.updated_at = now
    if rows:
        session.flush()


def _pair_claimed(
    session: Session,
    me: MatchQueue,
    user: User,
    other: MatchQueue,
    other_user: User,
) -> MatchResult:
    """Create game for two already-claimed (matching) queue rows, then remove them."""
    if me.use_fake_identity:
        game_type = "fake_identity"
    elif me.play_anonymous or other.play_anonymous:
        game_type = "anonymous"
    elif me.radius_km is not None or me.queue_mode == "nearby":
        game_type = "nearby"
    else:
        game_type = "stranger"

    game = game_engine.create_session(session, game_type, starter=user)
    game_engine.add_player(
        session,
        game,
        user,
        identity_mode=me.identity_mode,
        fake_identity_id=me.fake_identity_id,
    )
    game_engine.add_player(
        session,
        game,
        other_user,
        identity_mode=other.identity_mode,
        fake_identity_id=other.fake_identity_id,
    )
    game_engine.start_two_player(session, game)

    me.status = STATUS_MATCHED
    other.status = STATUS_MATCHED
    me.matched_game_id = game.id
    other.matched_game_id = game.id
    me.updated_at = _now()
    other.updated_at = _now()
    session.delete(me)
    session.delete(other)
    session.flush()

    logger.info(
        "Matched users %s <-> %s into game %s (%s)",
        user.id,
        other_user.id,
        game.id,
        game_type,
    )
    return MatchResult(
        game_id=game.id,
        user_a_id=user.id,
        user_b_id=other_user.id,
        user_a_tg=user.telegram_id,
        user_b_tg=other_user.telegram_id,
    )


def _try_claim_and_pair(
    session: Session,
    me: MatchQueue,
    user: User,
    other: MatchQueue,
    other_user: User,
) -> Optional[MatchResult]:
    """Claim both queue rows atomically; only then create the game."""
    if game_engine.active_session_for_user(session, user):
        return None
    if game_engine.active_session_for_user(session, other_user):
        # Partner already in a game — drop their stale queue row
        if other.status == STATUS_WAITING:
            session.delete(other)
            session.flush()
        return None

    if not _claim_pair_atomic(session, me.id, other.id):
        return None

    # Re-load after claim to ensure we own the matching rows
    session.expire_all()
    me2 = session.get(MatchQueue, me.id)
    other2 = session.get(MatchQueue, other.id)
    if (
        not me2
        or not other2
        or me2.status != STATUS_MATCHING
        or other2.status != STATUS_MATCHING
    ):
        if me2 or other2:
            _release_claim(session, me.id, other.id)
        return None

    # Final safety: still no active games
    if game_engine.active_session_for_user(session, user) or game_engine.active_session_for_user(
        session, other_user
    ):
        _release_claim(session, me.id, other.id)
        return None

    try:
        return _pair_claimed(session, me2, user, other2, other_user)
    except Exception:
        logger.exception("Pair failed after claim; releasing %s/%s", me.id, other.id)
        _release_claim(session, me.id, other.id)
        raise


def try_match(session: Session, user: User) -> Optional[MatchResult]:
    """Try to match a specific waiting user with the oldest compatible partner."""
    with match_lock(session):
        cleanup_stale_matching(session)
        me = (
            session.query(MatchQueue)
            .filter_by(user_id=user.id, status=STATUS_WAITING)
            .one_or_none()
        )
        if not me:
            return None
        if me.expires_at and me.expires_at < _now():
            me.status = STATUS_EXPIRED
            session.delete(me)
            return None
        if game_engine.active_session_for_user(session, user):
            cancel(session, user)
            return None

        candidates = (
            session.query(MatchQueue)
            .filter(
                MatchQueue.status == STATUS_WAITING,
                MatchQueue.user_id != user.id,
                MatchQueue.use_fake_identity == me.use_fake_identity,
                or_(MatchQueue.expires_at.is_(None), MatchQueue.expires_at >= _now()),
            )
            .order_by(MatchQueue.created_at.asc())
            .limit(MATCH_BATCH_SIZE)
            .all()
        )

        for other in candidates:
            other_user = session.get(User, other.user_id)
            if not other_user:
                session.delete(other)
                continue
            if game_engine.active_session_for_user(session, other_user):
                session.delete(other)
                continue
            if not _compatible(me, user, other, other_user):
                continue
            result = _try_claim_and_pair(session, me, user, other, other_user)
            if result:
                return result
            # Claim failed — partner taken; reload our waiting row if still present
            me = (
                session.query(MatchQueue)
                .filter_by(user_id=user.id, status=STATUS_WAITING)
                .one_or_none()
            )
            if not me:
                return None
        return None


def process_queue_batch(session: Session, limit: int | None = None) -> list[MatchResult]:
    """Background sweep under exclusive match lock."""
    with match_lock(session):
        cleanup_stale_matching(session)
        expire_stale(session)
        limit = limit or MATCH_BATCH_SIZE
        results: list[MatchResult] = []
        claimed_users: set[int] = set()

        waiting = (
            session.query(MatchQueue)
            .filter(
                MatchQueue.status == STATUS_WAITING,
                or_(MatchQueue.expires_at.is_(None), MatchQueue.expires_at >= _now()),
            )
            .order_by(MatchQueue.created_at.asc())
            .limit(limit)
            .all()
        )

        for me in waiting:
            if me.user_id in claimed_users or me.status != STATUS_WAITING:
                continue
            user = session.get(User, me.user_id)
            if not user:
                session.delete(me)
                continue
            if game_engine.active_session_for_user(session, user):
                session.delete(me)
                continue

            partners = (
                session.query(MatchQueue)
                .filter(
                    MatchQueue.status == STATUS_WAITING,
                    MatchQueue.user_id != me.user_id,
                    MatchQueue.use_fake_identity == me.use_fake_identity,
                    or_(MatchQueue.expires_at.is_(None), MatchQueue.expires_at >= _now()),
                )
                .order_by(MatchQueue.created_at.asc())
                .limit(limit)
                .all()
            )
            if claimed_users:
                partners = [p for p in partners if p.user_id not in claimed_users]

            for other in partners:
                if other.user_id in claimed_users:
                    continue
                other_user = session.get(User, other.user_id)
                if not other_user:
                    session.delete(other)
                    continue
                if game_engine.active_session_for_user(session, other_user):
                    session.delete(other)
                    continue
                if not _compatible(me, user, other, other_user):
                    continue
                result = _try_claim_and_pair(session, me, user, other, other_user)
                if result:
                    claimed_users.add(result.user_a_id)
                    claimed_users.add(result.user_b_id)
                    results.append(result)
                    break

        return results
