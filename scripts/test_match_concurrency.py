import concurrent.futures

from bot.db import get_session, init_db
from bot.models import GamePlayer, GameSession, MatchQueue, User
from bot.services import game_engine, matchmaker
from bot.services import users as user_svc


def main() -> None:
    init_db()

    with get_session() as s:
        for tid in range(920001, 920005):
            u = s.query(User).filter_by(telegram_id=tid).one_or_none()
            if not u:
                continue
            s.query(MatchQueue).filter_by(user_id=u.id).delete()
            for gp in s.query(GamePlayer).filter_by(user_id=u.id).all():
                g = s.get(GameSession, gp.session_id)
                if g and g.status in ("playing", "guessing", "waiting", "registering"):
                    g.status = "finished"
        s.flush()

        base = user_svc.get_or_create_user(s, 920001, "w", "Waiter")
        # Ensure waiter is not stuck in an active game from prior runs
        for gp in s.query(GamePlayer).filter_by(user_id=base.id).all():
            g = s.get(GameSession, gp.session_id)
            if g and g.status in ("playing", "guessing", "waiting", "registering"):
                g.status = "finished"
        s.flush()
        assert game_engine.active_session_for_user(s, base) is None
        base.display_name = "Waiter"
        base.province = "Tehran"
        base.city = "Tehran"
        base.gender = "female"
        base.age = 22
        base.allow_stranger_requests = True
        base.show_identity = True
        base.allow_anonymous_requests = True
        matchmaker.enqueue(
            s,
            base,
            same_city_only=False,
            preferred_gender="any",
            age_from=None,
            age_to=None,
            require_identity=False,
            play_anonymous=True,
            queue_mode="anonymous",
        )
        racers = []
        for i, tid in enumerate((920002, 920003, 920004)):
            u = user_svc.get_or_create_user(s, tid, f"r{i}", f"Racer{i}")
            u.display_name = f"Racer{i}"
            u.province = "Tehran"
            u.city = "Tehran"
            u.gender = "male"
            u.age = 23
            u.allow_stranger_requests = True
            u.show_identity = True
            u.allow_anonymous_requests = True
            racers.append(tid)

    def race(tid: int):
        with matchmaker.match_section():
            with get_session() as s:
                u = s.query(User).filter_by(telegram_id=tid).one()
                matchmaker.enqueue(
                    s,
                    u,
                    same_city_only=False,
                    preferred_gender="any",
                    age_from=None,
                    age_to=None,
                    require_identity=False,
                    play_anonymous=True,
                    queue_mode="anonymous",
                )
                r = matchmaker.try_match(s, u)
                return (tid, bool(r), r.game_id if r else None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        outs = list(ex.map(race, racers))

    print("results:", outs)
    matched = [o for o in outs if o[1]]
    print("matched_count", len(matched))

    with get_session() as s:
        # No user may be in more than one active game
        from sqlalchemy import func

        dupes = (
            s.query(GamePlayer.user_id, func.count(GamePlayer.id))
            .join(GameSession, GameSession.id == GamePlayer.session_id)
            .filter(GameSession.status == "playing")
            .group_by(GamePlayer.user_id)
            .having(func.count(GamePlayer.id) > 1)
            .all()
        )
        print("users in multiple playing games:", dupes)
        assert not dupes, dupes

        waiter = s.query(User).filter_by(telegram_id=920001).one()
        games = (
            s.query(GameSession)
            .join(GamePlayer, GamePlayer.session_id == GameSession.id)
            .filter(GamePlayer.user_id == waiter.id, GameSession.status == "playing")
            .all()
        )
        print("waiter active games", len(games), [g.id for g in games])
        waiting = s.query(MatchQueue).filter_by(status="waiting").count()
        matching = s.query(MatchQueue).filter_by(status="matching").count()
        print("queue waiting", waiting, "matching", matching)
        assert len(games) == 1, games
        assert matching == 0
        # Exactly one racer matched the waiter; remaining two may match each other
        assert len(matched) in (1, 2), matched
    print("OK concurrency safe")


if __name__ == "__main__":
    main()
