from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from bot.models import GamePlayer, GameSession, Round, User
from bot.services.questions import random_prompt
from bot.services.users import public_name

DEFAULT_TWO_PLAYER_ROUNDS = 10


def format_round_info(round_number: int, max_rounds: int | None = None) -> str:
    """Human-readable round line; endless when max_rounds is None/<=0."""
    from bot.texts import fa as T

    if max_rounds and max_rounds > 0:
        return T.ROUND_INFO.format(n=round_number, max=max_rounds)
    return T.ROUND_INFO_OPEN.format(n=round_number)


def create_session(
    session: Session,
    game_type: str,
    starter: Optional[User] = None,
    chat_id: Optional[int] = None,
    max_rounds: int = 0,
    inline_message_id: Optional[str] = None,
) -> GameSession:
    """max_rounds <= 0 means unlimited rounds (end only via button)."""
    gs = GameSession(
        game_type=game_type,
        status="waiting",
        chat_id=chat_id,
        starter_user_id=starter.id if starter else None,
        max_rounds=max_rounds,
        inline_message_id=inline_message_id,
    )
    session.add(gs)
    session.flush()
    return gs


def two_player_round_cap(game_type: str) -> int:
    return 0 if game_type in {"group", "channel"} else DEFAULT_TWO_PLAYER_ROUNDS


def find_registering_group(
    session: Session,
    *,
    chat_id: Optional[int] = None,
    inline_message_id: Optional[str] = None,
) -> Optional[GameSession]:
    """Open group registration for a chat or inline message, if any."""
    q = session.query(GameSession).filter(
        GameSession.game_type == "group",
        GameSession.status == "registering",
    )
    if inline_message_id:
        row = q.filter(GameSession.inline_message_id == inline_message_id).order_by(
            GameSession.id.desc()
        ).first()
        if row:
            return row
    if chat_id is not None:
        return (
            q.filter(GameSession.chat_id == chat_id)
            .order_by(GameSession.id.desc())
            .first()
        )
    return None


def add_player(
    session: Session,
    game: GameSession,
    user: User,
    identity_mode: str = "real",
    fake_identity_id: Optional[int] = None,
    display_label: Optional[str] = None,
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
        display_label=display_label,
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
    if player.identity_mode in ("anonymous", "nickname"):
        return public_name(player.user, player.identity_mode, player.display_label)
    # Casual joiners (no bot /start / incomplete profile): show account label
    if player.display_label:
        return player.display_label
    return public_name(player.user)


def presented_profile(player: GamePlayer) -> str:
    """What the opponent should see for this player (persona or real profile)."""
    from bot.services import fake_identity as fake_svc
    from bot.services import users as user_svc

    if player.identity_mode == "fake" and player.fake_identity:
        return fake_svc.format_card_public(player.fake_identity)
    if player.identity_mode == "anonymous":
        return "کاربر ناشناس"
    return user_svc.format_profile(player.user, viewer_settings=player.user)


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
    """Start group play: current player answers their own question (self-turn)."""
    players = get_players(session, game)
    if len(players) < 2:
        raise ValueError("need_two")
    game.status = "playing"
    game.round_number = 1
    game.max_rounds = 0  # endless — ends via اتمام بازی
    turn = players[0]
    game.current_turn_user_id = turn.user_id
    game.current_target_user_id = turn.user_id
    rnd = Round(
        session_id=game.id,
        round_no=1,
        chooser_user_id=turn.user_id,
        target_user_id=turn.user_id,
        status="open",
    )
    session.add(rnd)
    session.flush()
    return rnd


def advance_group_self_turn(session: Session, game: GameSession) -> Optional[Round]:
    """Close current open round (if any) and move to next player in list."""
    players = get_players(session, game)
    if not players:
        return None
    open_rnd = get_active_round(session, game)
    if open_rnd and open_rnd.status == "open":
        if not open_rnd.prompt_text and not open_rnd.choice:
            open_rnd.status = "skipped"
        elif open_rnd.status == "open":
            open_rnd.status = "answered" if open_rnd.prompt_text else "skipped"

    ids = [p.user_id for p in players]
    cur = game.current_turn_user_id
    if cur in ids:
        idx = ids.index(cur)
        next_uid = ids[(idx + 1) % len(ids)]
    else:
        next_uid = ids[0]

    game.round_number += 1
    game.current_turn_user_id = next_uid
    game.current_target_user_id = next_uid
    rnd = Round(
        session_id=game.id,
        round_no=game.round_number,
        chooser_user_id=next_uid,
        target_user_id=next_uid,
        status="open",
    )
    session.add(rnd)
    session.flush()
    return rnd


def apply_choice(
    session: Session,
    rnd: Round,
    choice: str,
    prompt: Optional[str] = None,
    *,
    media_type: Optional[str] = None,
    file_id: Optional[str] = None,
) -> str:
    """Set truth/dare. If prompt/media omitted, pick a random bank prompt."""
    rnd.choice = choice
    text = (prompt or "").strip()
    source = "custom" if (text or file_id) else "bank"
    if not text and not file_id:
        target = session.get(User, rnd.target_user_id) if rnd.target_user_id else None
        seen = used_prompts(session, rnd.session_id)
        text = random_prompt(
            choice,  # type: ignore[arg-type]
            gender=getattr(target, "gender", None),
            age=getattr(target, "age", None),
            session=session,
            exclude=seen,
        )
    rnd.prompt_text = text or None
    rnd.prompt_media_type = media_type if file_id else None
    rnd.prompt_file_id = file_id
    rnd.prompt_source = source
    if text:
        return text
    labels = {
        "photo": "📷 عکس",
        "voice": "🎤 ویس",
        "video": "🎥 ویدیو",
        "video_note": "🎬 ویدیوی دایره‌ای",
    }
    return labels.get(media_type or "", "مدیا")


def apply_category_prompt(
    session: Session,
    rnd: Round,
    cat_key: str,
) -> tuple[str, str]:
    """Apply a group category; returns (category_label, prompt)."""
    from bot.services.questions import prompt_for_category

    kind, label, text = prompt_for_category(
        session, cat_key, exclude=used_prompts(session, rnd.session_id)
    )
    rnd.choice = kind
    rnd.category_key = cat_key
    rnd.prompt_text = text
    rnd.prompt_media_type = None
    rnd.prompt_file_id = None
    rnd.prompt_source = "bank"
    return label, text


def set_pending_choice(session: Session, rnd: Round, choice: str) -> None:
    """Chooser picked truth/dare; waiting for their custom question text."""
    rnd.choice = choice
    rnd.prompt_text = None
    rnd.prompt_media_type = None
    rnd.prompt_file_id = None
    rnd.prompt_source = None


def used_prompts(session: Session, session_id: int) -> set[str]:
    rows = (
        session.query(Round.prompt_text)
        .filter(Round.session_id == session_id, Round.prompt_text.isnot(None))
        .all()
    )
    return {r[0].strip() for r in rows if r[0] and r[0].strip()}


def submit_answer(
    session: Session,
    rnd: Round,
    text: Optional[str],
    *,
    media_type: Optional[str] = None,
    file_id: Optional[str] = None,
) -> None:
    rnd.answer_text = text
    rnd.answer_media_type = media_type if file_id else None
    rnd.answer_file_id = file_id
    rnd.status = "answered" if (text or file_id) else "skipped"


def round_has_prompt(rnd: Round) -> bool:
    return bool((rnd.prompt_text and rnd.prompt_text.strip()) or rnd.prompt_file_id)


def advance_round(session: Session, game: GameSession) -> Optional[Round]:
    players = get_players(session, game)
    if not players:
        return None

    # max_rounds <= 0 → endless; otherwise stop when cap reached
    if game.max_rounds and game.max_rounds > 0 and game.round_number >= game.max_rounds:
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
    kind = _game_type_label(game.game_type)
    game.summary = (
        f"{kind} با {names} — "
        f"{len(rounds)} راند ({answered} جواب، {skipped} رد)"
    )
    # Fake-identity games always end with the core guess question
    if game.game_type == "fake_identity":
        game.status = "guessing"
    return None


def continue_game(session: Session, game: GameSession, *, extra_rounds: int = DEFAULT_TWO_PLAYER_ROUNDS) -> Optional[Round]:
    """Resume a finished two-player game for extra rounds."""
    if game.status not in ("finished",):
        return None
    if game.game_type in {"group", "channel"}:
        return None
    game.status = "playing"
    game.finished_at = None
    game.summary = None
    current = int(game.max_rounds or 0)
    game.max_rounds = max(current, game.round_number) + max(1, extra_rounds)
    return advance_round(session, game)


def remake_two_player(session: Session, game: GameSession) -> Optional[Round]:
    """Create a fresh 10-round game with the same two real players/personas."""
    players = get_players(session, game)
    if len(players) != 2:
        return None
    starter_user = next((p.user for p in players if p.user_id == game.starter_user_id), None)
    new_game = create_session(
        session,
        game.game_type,
        starter=starter_user or players[0].user,
        max_rounds=two_player_round_cap(game.game_type),
    )
    for p in players:
        add_player(
            session,
            new_game,
            p.user,
            identity_mode=p.identity_mode,
            fake_identity_id=p.fake_identity_id,
            display_label=p.display_label,
        )
    return start_two_player(session, new_game)


def _game_type_label(game_type: str) -> str:
    return {
        "friends": "دوستان",
        "group": "گروه",
        "channel": "کانال",
        "stranger": "غریبه",
        "anonymous": "ناشناس",
        "nearby": "نزدیک",
        "fake_identity": "هویت رندوم",
    }.get(game_type, game_type)


def format_history_entry(session: Session, game: GameSession, me_user_id: int) -> str:
    """Short history line: whom + kind + progress."""
    players = get_players(session, game)
    others = [display_for_player(p) for p in players if p.user_id != me_user_id]
    if not others and game.game_type == "channel":
        whom = "مخاطبان کانال"
    elif not others and game.game_type == "group":
        whom = "، ".join(display_for_player(p) for p in players) or "گروه"
    else:
        whom = "، ".join(others) if others else "—"

    kind = _game_type_label(game.game_type)
    rounds = (
        session.query(Round)
        .filter_by(session_id=game.id)
        .order_by(Round.round_no)
        .all()
    )
    if rounds:
        answered = sum(1 for r in rounds if r.status == "answered")
        skipped = sum(1 for r in rounds if r.status == "skipped")
        progress = f"{len(rounds)} راند · {answered} جواب · {skipped} رد"
    elif game.summary:
        # fallback extract after em-dash if present
        progress = game.summary
        if "— " in game.summary:
            progress = game.summary.split("— ", 1)[-1]
    else:
        progress = f"وضعیت: {game.status}"

    return f"با {whom}\n   {kind} — {progress}"


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
