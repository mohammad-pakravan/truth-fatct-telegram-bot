from __future__ import annotations

import logging

from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.models import User
from bot.services import game_engine
from bot.services import matchmaker
from bot.services import users as user_svc
from bot.texts import fa as T

logger = logging.getLogger(__name__)


def _opponent_blurb(me: User, other: User) -> str:
    return "حریف:\n" + user_svc.format_profile(other, viewer_settings=me)


async def deliver_match(context: ContextTypes.DEFAULT_TYPE, result: matchmaker.MatchResult) -> None:
    """Notify both players and switch them into the in-game keyboard (idempotent)."""
    with get_session() as session:
        game = game_engine.get_session(session, result.game_id)
        if not game or game.status not in ("playing", "guessing"):
            logger.warning("Skip deliver for inactive/missing game_id=%s", result.game_id)
            return
        user_a = session.get(User, result.user_a_id)
        user_b = session.get(User, result.user_b_id)
        if not user_a or not user_b:
            return
        players = game_engine.get_players(session, game)
        player_ids = {p.user_id for p in players}
        if result.user_a_id not in player_ids or result.user_b_id not in player_ids:
            logger.warning("Skip deliver: players mismatch game_id=%s", result.game_id)
            return
        rnd = game_engine.get_active_round(session, game)

        chooser_name = target_name = "?"
        for p in players:
            if rnd and p.user_id == rnd.chooser_user_id:
                chooser_name = game_engine.display_for_player(p)
            if rnd and p.user_id == rnd.target_user_id:
                target_name = game_engine.display_for_player(p)

        anonymous = game.game_type == "anonymous"
        if anonymous:
            chooser_name = target_name = "ناشناس"
            msg_a = T.MATCH_FOUND + "\n" + T.ANON_OPPONENT
            msg_b = T.MATCH_FOUND + "\n" + T.ANON_OPPONENT
        else:
            msg_a = T.MATCH_FOUND + "\n" + _opponent_blurb(user_a, user_b)
            msg_b = T.MATCH_FOUND + "\n" + _opponent_blurb(user_b, user_a)

        chooser_id = rnd.chooser_user_id if rnd else None
        td_text = T.CHOOSE_TRUTH_OR_DARE.format(chooser=chooser_name, target=target_name)
        td_markup = kb.truth_dare(game.id, chooser_id) if rnd and chooser_id else None

        a_tg, b_tg = user_a.telegram_id, user_b.telegram_id
        a_is_chooser = bool(rnd and rnd.chooser_user_id == user_a.id)
        b_is_chooser = bool(rnd and rnd.chooser_user_id == user_b.id)

    for tg_id in (a_tg, b_tg):
        st.clear(tg_id)

    for tg_id, text, is_chooser in (
        (a_tg, msg_a, a_is_chooser),
        (b_tg, msg_b, b_is_chooser),
    ):
        try:
            await context.bot.send_message(
                tg_id,
                text,
                reply_markup=kb.in_game_menu(is_chooser=is_chooser),
            )
        except Exception:
            logger.exception("Failed to notify matched user %s", tg_id)

    if td_markup and chooser_id:
        chooser_tg = a_tg if a_is_chooser else b_tg if b_is_chooser else None
        if chooser_tg:
            try:
                await context.bot.send_message(chooser_tg, td_text, reply_markup=td_markup)
            except Exception:
                logger.exception("Failed to send truth/dare prompt to %s", chooser_tg)


async def enqueue_and_maybe_match(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    telegram_user,
    prefs: dict,
    use_fake: bool = False,
    identity_mode: str = "real",
    fake_id=None,
    queue_mode: str = "stranger",
    edit_message=None,
) -> bool:
    """
    Enqueue user, try immediate match, otherwise show waiting UI.
    Returns True if matched immediately.
    """
    with matchmaker.match_section():
        with get_session() as session:
            user = user_svc.get_or_create_user(
                session, telegram_user.id, telegram_user.username, telegram_user.full_name
            )
            active = game_engine.active_session_for_user(session, user)
            if active:
                rnd = game_engine.get_active_round(session, active)
                is_chooser = bool(rnd and rnd.chooser_user_id == user.id)
                markup = kb.in_game_menu(is_chooser=is_chooser)
                if edit_message:
                    try:
                        await edit_message.edit_text(T.ALREADY_IN_GAME)
                    except Exception:
                        pass
                await context.bot.send_message(
                    telegram_user.id,
                    T.ALREADY_IN_GAME,
                    reply_markup=markup,
                )
                return False

            try:
                matchmaker.enqueue(
                    session,
                    user,
                    same_city_only=bool(prefs.get("same_city")),
                    preferred_gender=prefs.get("gender") if prefs.get("gender") != "any" else "any",
                    age_from=prefs.get("age_from"),
                    age_to=prefs.get("age_to"),
                    require_identity=bool(prefs.get("require_identity", True)),
                    play_anonymous=bool(prefs.get("play_anonymous", False)),
                    use_fake_identity=use_fake,
                    fake_identity_id=fake_id,
                    identity_mode=identity_mode,
                    queue_mode=queue_mode,
                    provinces=prefs.get("provinces"),
                    radius_km=prefs.get("radius_km"),
                )
            except RuntimeError as exc:
                if str(exc) == "already_in_game":
                    from bot.handlers import gameplay

                    await gameplay.resume_active_game_keyboard(context, telegram_user.id)
                    return False
                if str(exc) == "match_in_progress":
                    await context.bot.send_message(
                        telegram_user.id,
                        "الان در حال مچ شدنت هستیم… چند لحظه صبر کن.",
                    )
                    return False
                raise

            result = matchmaker.try_match(session, user)
            if result:
                match_ids = result
            else:
                pos = matchmaker.queue_position(session, user)
                total = matchmaker.waiting_count(session)
                wait_text = T.WAITING_MATCH.format(pos=pos, total=total)
                st.set_state(telegram_user.id, mode="queued")
                if edit_message:
                    try:
                        await edit_message.edit_text(wait_text, reply_markup=kb.cancel_match())
                    except Exception:
                        pass
                    await context.bot.send_message(
                        telegram_user.id,
                        T.WAITING_MATCH_HINT,
                        reply_markup=kb.queue_menu(),
                    )
                else:
                    await context.bot.send_message(
                        telegram_user.id,
                        wait_text,
                        reply_markup=kb.queue_menu(),
                    )
                return False

    if edit_message:
        try:
            await edit_message.edit_text(T.MATCH_FOUND)
        except Exception:
            pass
    await deliver_match(context, match_ids)
    return True
