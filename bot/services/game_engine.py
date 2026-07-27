from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from bot.models import GamePlayer, GameSession, Round, User
from bot.services.questions import random_prompt
from bot.services.users import public_name


def create_session(
    session: Session,
    game_type: str,
    starter: Optional[User] = None,
    chat_id: Optional[int] = None,
    max_rounds: int = 5,
) -> GameSession:
    gs = GameSession(
        game_type=game_type,
        status="waiting",
        chat_id=chat_id,
        starter_user_id=starter.id if starter else None,
        max_rounds=max_rounds,
    )
    session.add(gs)
    session.flush()
    return gs


def add_player(
    session: Session,
    game: GameSession,
    user: User,
    identity_mode: str = "real",
    fake_identity_id: Optional[int] = None,
) -> GamePlayer:
    existing = (
        session.query(GamePlayer)
        .filter_by(session_id=game.id, user_id=user.id)
        .one_or_none()
    )
    if existing:
        return existing
    player = GamePlayer(
        session_id=game.id,
        user_id=user.id,
        identity_mode=identity_mode,
        fake_identity_id=fake_identity_id,
    )
    session.add(player)
    session.flush()
    return player


def player_count(session: Session, game: GameSession) -> int:
    return session.query(GamePlayer).filter_by(session_id=game.id).count()


def get_players(session: Session, game: GameSession) -> list[GamePlayer]:
    return (
        session.query(GamePlayer)
        .options(joinedload(GamePlayer.user), joinedload(GamePlayer.fake_identity))
        .filter_by(session_id=game.id)
        .order_by(GamePlayer.id)
        .all()
    )


def display_for_player(player: GamePlayer) -> str:
    if player.identity_mode == "fake" and player.fake_identity:
        fi = player.fake_identity
        return f"{fi.name} ({fi.city})"
    return public_name(player.user)


def start_two_player(session: Session, game: GameSession) -> Round:
    players = get_players(session, game)
    if len(players) < 2:
        raise ValueError("need_two")
    game.status = "playing"
    game.round_number = 1
    chooser = players[0]
    target = players[1]
    game.current_turn_user_id = chooser.user_id
    game.current_target_user_id = target.user_id
    rnd = Round(
        session_id=game.id,
        round_no=1,
        chooser_user_id=chooser.user_id,
        target_user_id=target.user_id,
        status="open",
    )
    session.add(rnd)
    session.flush()
    return rnd


def start_group_rotation(session: Session, game: GameSession) -> Round:
    players = get_players(session, game)
    if len(players) < 2:
        raise ValueError("need_two")
    game.status = "playing"
    game.round_number = 1
    chooser = players[0]
    target = players[1]
    game.current_turn_user_id = chooser.user_id
    game.current_target_user_id = target.user_id
    rnd = Round(
        session_id=game.id,
        round_no=1,
        chooser_user_id=chooser.user_id,
        target_user_id=target.user_id,
        status="open",
    )
    session.add(rnd)
    session.flush()
    return rnd


def apply_choice(session: Session, rnd: Round, choice: str) -> str:
    prompt = random_prompt(choice)  # type: ignore[arg-type]
    rnd.choice = choice
    rnd.prompt_text = prompt
    return prompt


def submit_answer(session: Session, rnd: Round, text: Optional[str]) -> None:
    rnd.answer_text = text
    rnd.status = "answered" if text else "skipped"


def advance_round(session: Session, game: GameSession) -> Optional[Round]:
    players = get_players(session, game)
    if not players:
        return None

    if game.round_number >= game.max_rounds:
        return finish_game(session, game)

    # rotate: previous target becomes chooser; next player is target
    ids = [p.user_id for p in players]
    prev_chooser = game.current_turn_user_id
    prev_target = game.current_target_user_id
    if prev_target is None or prev_chooser is None:
        return None

    new_chooser = prev_target
    idx = ids.index(new_chooser)
    # pick next different player as target
    new_target = ids[(idx + 1) % len(ids)]
    if new_target == new_chooser and len(ids) > 1:
        new_target = ids[(idx + 2) % len(ids)]

    game.round_number += 1
    game.current_turn_user_id = new_chooser
    game.current_target_user_id = new_target
    rnd = Round(
        session_id=game.id,
        round_no=game.round_number,
        chooser_user_id=new_chooser,
        target_user_id=new_target,
        status="open",
    )
    session.add(rnd)
    session.flush()
    return rnd


def finish_game(session: Session, game: GameSession) -> None:
    game.status = "finished"
    game.finished_at = datetime.utcnow()
    rounds = (
        session.query(Round)
        .filter_by(session_id=game.id)
        .order_by(Round.round_no)
        .all()
    )
    answered = sum(1 for r in rounds if r.status == "answered")
    skipped = sum(1 for r in rounds if r.status == "skipped")
    players = get_players(session, game)
    names = "، ".join(display_for_player(p) for p in players)
    game.summary = (
        f"نوع: {game.game_type} | بازیکنان: {names} | "
        f"{len(rounds)} راند ({answered} جواب، {skipped} رد)"
    )
    # for fake identity games, move to guessing instead of finished if needed
    if game.game_type == "fake_identity" and any(p.identity_mode == "fake" for p in players):
        # keep finished but mark guessing phase via status if guesses pending
        pending = [p for p in players if p.final_guess is None]
        if pending:
            game.status = "guessing"
    return None


def get_active_round(session: Session, game: GameSession) -> Optional[Round]:
    return (
        session.query(Round)
        .filter_by(session_id=game.id, status="open")
        .order_by(Round.id.desc())
        .first()
    )


def get_session(session: Session, session_id: int) -> Optional[GameSession]:
    return session.get(GameSession, session_id)


def active_session_for_user(session: Session, user: User) -> Optional[GameSession]:
    row = (
        session.query(GameSession)
        .join(GamePlayer, GamePlayer.session_id == GameSession.id)
        .filter(
            GamePlayer.user_id == user.id,
            GameSession.status.in_(["playing", "guessing"]),
            GameSession.game_type.in_(["friends", "stranger", "anonymous", "nearby", "fake_identity"]),
        )
        .order_by(GameSession.id.desc())
        .first()
    )
    return row


def user_recent_games(session: Session, user: User, limit: int = 20) -> list[GameSession]:
    player_rows = (
        session.query(GamePlayer.session_id)
        .filter_by(user_id=user.id)
        .subquery()
    )
    return (
        session.query(GameSession)
        .filter(GameSession.id.in_(player_rows))
        .filter(GameSession.status.in_(["finished", "guessing"]))
        .order_by(GameSession.id.desc())
        .limit(limit)
        .all()
    )
