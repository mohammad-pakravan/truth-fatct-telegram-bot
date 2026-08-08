from __future__ import annotations

import logging

from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import MatchQueue, User
from bot.services import game_engine
from bot.services import matchmaker
from bot.services import users as user_svc
from bot.services.glass_msg import show_td_glass, upsert_hub
from bot.texts import fa as T

logger = logging.getLogger(__name__)


def _opponent_blurb(me: User, other: User) -> str:
    return "حریف:\n" + user_svc.format_profile(other, viewer_settings=me)


async def deliver_match(context: ContextTypes.DEFAULT_TYPE, result: matchmaker.MatchResult) -> None:
    """Edit (or send) one hub message per player for match start + truth/dare."""
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
        fake_game = game.game_type == "fake_identity"
        player_a = next((p for p in players if p.user_id == user_a.id), None)
        player_b = next((p for p in players if p.user_id == user_b.id), None)

        remind_a = remind_b = None
        if anonymous:
            chooser_name = target_name = "ناشناس"
            body_a = T.MATCH_FOUND + "\n" + T.ANON_OPPONENT
            body_b = T.MATCH_FOUND + "\n" + T.ANON_OPPONENT
        elif fake_game and player_a and player_b:
            body_a = (
                T.MATCH_FOUND
                + "\nحریف:\n"
                + game_engine.presented_profile(player_b)
                + "\n\n"
                + T.FAKE_STAY_HINT
            )
            body_b = (
                T.MATCH_FOUND
                + "\nحریف:\n"
                + game_engine.presented_profile(player_a)
                + "\n\n"
                + T.FAKE_STAY_HINT
            )
            from bot.services import fake_identity as fake_svc

            if player_a.identity_mode == "fake" and player_a.fake_identity:
                remind_a = T.FAKE_REMINDER.format(
                    card=fake_svc.format_card_body(player_a.fake_identity)
                )
            if player_b.identity_mode == "fake" and player_b.fake_identity:
                remind_b = T.FAKE_REMINDER.format(
                    card=fake_svc.format_card_body(player_b.fake_identity)
                )
        else:
            body_a = T.MATCH_FOUND + "\n" + _opponent_blurb(user_a, user_b)
            body_b = T.MATCH_FOUND + "\n" + _opponent_blurb(user_b, user_a)

        chooser_id = rnd.chooser_user_id if rnd else None
        turn = T.CHOOSE_TRUTH_OR_DARE.format(chooser=chooser_name, target=target_name)
        if rnd:
            turn = f"{T.ROUND_INFO.format(n=game.round_number, max=game.max_rounds)}\n{turn}"

        a_tg, b_tg = user_a.telegram_id, user_b.telegram_id
        a_is_chooser = bool(rnd and rnd.chooser_user_id == user_a.id)
        b_is_chooser = bool(rnd and rnd.chooser_user_id == user_b.id)
        game_id = game.id

    hubs = {
        a_tg: st.get(a_tg).get("game_hub_message_id"),
        b_tg: st.get(b_tg).get("game_hub_message_id"),
    }
    for tg_id in (a_tg, b_tg):
        st.clear(tg_id)

    for tg_id, body, is_chooser, remind in (
        (a_tg, body_a, a_is_chooser, remind_a),
        (b_tg, body_b, b_is_chooser, remind_b),
    ):
        try:
            if remind:
                await context.bot.send_message(tg_id, remind)
            if is_chooser and chooser_id:
                hub_text = T.MATCH_HUB.format(match_body=body)
                mid = await upsert_hub(
                    context.bot,
                    tg_id,
                    hub_text,
                    message_id=hubs.get(tg_id),
                    reply_kb=kb.in_game_menu(is_chooser=True),
                    replace_keyboard=True,
                )
                glass_id = await show_td_glass(
                    context.bot,
                    tg_id,
                    session_id=game_id,
                    chooser_id=chooser_id,
                    turn_text=turn,
                )
                st.set_state(
                    tg_id, game_hub_message_id=mid, game_glass_message_id=glass_id
                )
            else:
                text = T.MATCH_START_WAITER.format(match_body=body, turn=turn)
                mid = await upsert_hub(
                    context.bot,
                    tg_id,
                    text,
                    message_id=hubs.get(tg_id),
                    reply_kb=kb.in_game_menu(is_chooser=False),
                    replace_keyboard=True,
                )
                st.set_state(tg_id, game_hub_message_id=mid)
        except Exception:
            logger.exception("Failed to notify matched user %s", tg_id)


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
    hub_message_id: int | None = None,
) -> bool:
    """
    Enqueue user, try immediate match, otherwise show waiting UI.
    Returns True if matched immediately.
    Keeps a single hub message (edit in place) for searching → match.
    """
    tg_id = telegram_user.id
    if hub_message_id is not None:
        st.set_state(tg_id, game_hub_message_id=hub_message_id)
    elif edit_message is not None:
        st.set_state(tg_id, game_hub_message_id=edit_message.message_id)
    hub_id = st.get(tg_id).get("game_hub_message_id")

    with matchmaker.match_section():
        with get_session() as session:
            user = user_svc.get_or_create_user(
                session, telegram_user.id, telegram_user.username, telegram_user.full_name
            )
            active = game_engine.active_session_for_user(session, user)
            if active:
                if hub_id:
                    try:
                        await upsert_hub(
                            context.bot, tg_id, T.ALREADY_IN_GAME, message_id=hub_id
                        )
                    except Exception:
                        pass
                from bot.handlers import gameplay

                await gameplay.resume_active_game_keyboard(context, telegram_user.id)
                return False

            from bot.config import MIN_USER_AGE

            if user.age is None or user.age < MIN_USER_AGE:
                msg = T.AGE_TOO_YOUNG
                if hub_id:
                    try:
                        await upsert_hub(
                            context.bot,
                            tg_id,
                            msg,
                            message_id=hub_id,
                            reply_kb=main_menu(),
                        )
                    except Exception:
                        pass
                else:
                    await context.bot.send_message(
                        telegram_user.id, msg, reply_markup=main_menu()
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
                if str(exc) == "restricted":
                    from bot.services import moderation as mod_svc

                    msg = mod_svc.restriction_message(session, user) or T.RESTRICTED_PERMANENT.format(
                        reason="—"
                    )
                    if hub_id:
                        try:
                            await upsert_hub(
                                context.bot,
                                tg_id,
                                msg,
                                message_id=hub_id,
                                reply_kb=main_menu(),
                            )
                        except Exception:
                            pass
                    else:
                        await context.bot.send_message(
                            telegram_user.id, msg, reply_markup=main_menu()
                        )
                    return False
                if str(exc) == "match_in_progress":
                    await upsert_hub(
                        context.bot,
                        tg_id,
                        "الان در حال مچ شدنت هستیم… چند لحظه صبر کن.",
                        message_id=hub_id,
                    )
                    return False
                raise

            result = matchmaker.try_match(session, user)
            if result:
                match_ids = result
            else:
                me_row = (
                    session.query(MatchQueue)
                    .filter_by(user_id=user.id, status=matchmaker.STATUS_WAITING)
                    .one_or_none()
                )
                pos = matchmaker.queue_position(session, user)
                total = matchmaker.waiting_count(
                    session,
                    use_fake_identity=bool(me_row.use_fake_identity) if me_row else None,
                    queue_mode=me_row.queue_mode if me_row else None,
                )
                mode_key = (me_row.queue_mode if me_row else queue_mode) or "stranger"
                mode_label = {
                    "stranger": "غریبه",
                    "fake": "هویت رندوم",
                    "nearby": "نزدیک من",
                    "advanced": "جستجوی پیشرفته",
                    "anonymous": "ناشناس",
                }.get(mode_key, mode_key)
                wait_text = T.WAITING_MATCH.format(
                    pos=pos, total=total, mode=mode_label
                )
                mid = await upsert_hub(
                    context.bot,
                    tg_id,
                    wait_text,
                    message_id=hub_id,
                    reply_kb=kb.queue_menu(),
                    replace_keyboard=True,
                )
                st.set_state(tg_id, mode="queued", game_hub_message_id=mid)
                return False

    await deliver_match(context, match_ids)
    return True
