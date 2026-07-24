from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from bot.models import MatchQueue, User
from bot.services import game_engine
from bot.services.users import profile_complete


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
) -> MatchQueue:
    existing = session.query(MatchQueue).filter_by(user_id=user.id).one_or_none()
    if existing:
        session.delete(existing)
        session.flush()

    row = MatchQueue(
        user_id=user.id,
        same_city_only=same_city_only,
        preferred_gender=preferred_gender,
        age_from=age_from,
        age_to=age_to,
        require_identity=require_identity,
        play_anonymous=play_anonymous,
        use_fake_identity=use_fake_identity,
        fake_identity_id=fake_identity_id,
        identity_mode=identity_mode,
    )
    session.add(row)
    session.flush()
    return row


def cancel(session: Session, user: User) -> bool:
    row = session.query(MatchQueue).filter_by(user_id=user.id).one_or_none()
    if not row:
        return False
    session.delete(row)
    return True


def _compatible(a: MatchQueue, ua: User, b: MatchQueue, ub: User) -> bool:
    if not profile_complete(ua) or not profile_complete(ub):
        return False

    # stranger request permission
    if not ub.allow_stranger_requests or not ua.allow_stranger_requests:
        return False

    # anonymous play respect
    if a.play_anonymous and not ub.allow_anonymous_requests:
        return False
    if b.play_anonymous and not ua.allow_anonymous_requests:
        return False

    # gender preference
    if a.preferred_gender and a.preferred_gender != "any":
        if ub.gender != a.preferred_gender:
            return False
    if b.preferred_gender and b.preferred_gender != "any":
        if ua.gender != b.preferred_gender:
            return False

    # city
    if a.same_city_only and ua.city and ub.city and ua.city != ub.city:
        return False
    if b.same_city_only and ua.city and ub.city and ua.city != ub.city:
        return False

    # age ranges (other person's age must fall in my range)
    if a.age_from is not None and (ub.age is None or ub.age < a.age_from):
        return False
    if a.age_to is not None and (ub.age is None or ub.age > a.age_to):
        return False
    if b.age_from is not None and (ua.age is None or ua.age < b.age_from):
        return False
    if b.age_to is not None and (ua.age is None or ua.age > b.age_to):
        return False

    # identity visibility preference: if I require identity, other must show_identity
    if a.require_identity and not ub.show_identity:
        return False
    if b.require_identity and not ua.show_identity:
        return False

    # fake mode pairing: both should be same queue mode family
    if a.use_fake_identity != b.use_fake_identity:
        return False

    return True


def try_match(session: Session, user: User) -> Optional[tuple]:
    """Try to match user with someone in queue. Returns (game, other_user) or None."""
    me = session.query(MatchQueue).filter_by(user_id=user.id).one_or_none()
    if not me:
        return None

    candidates = (
        session.query(MatchQueue)
        .filter(MatchQueue.user_id != user.id)
        .order_by(MatchQueue.created_at)
        .all()
    )
    for other in candidates:
        other_user = session.get(User, other.user_id)
        if not other_user:
            continue
        if _compatible(me, user, other, other_user):
            game_type = "fake_identity" if me.use_fake_identity else "stranger"
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
            session.delete(me)
            session.delete(other)
            session.flush()
            return game, other_user
    return None
