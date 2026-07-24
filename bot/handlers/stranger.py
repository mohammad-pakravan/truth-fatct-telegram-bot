from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.config import AGE_FROM_OPTIONS, AGE_TO_OPTIONS
from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import User
from bot.services import game_engine
from bot.services import matchmaker
from bot.services import users as user_svc
from bot.texts import fa as T


async def open_stranger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if not user_svc.profile_complete(user):
            await update.message.reply_text(T.PROFILE_INCOMPLETE, reply_markup=main_menu())
            return
    st.set_state(tg.id, mode="stranger", wait="city", stranger={})
    await update.message.reply_text(T.STRANGER_INTRO, reply_markup=kb.city_pref())


async def open_nearby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Same-city matchmaking shortcut."""
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if not user_svc.profile_complete(user):
            await update.message.reply_text(T.PROFILE_INCOMPLETE, reply_markup=main_menu())
            return
    s = {"same_city": True}
    st.set_state(tg.id, mode="stranger", wait="gender", stranger=s)
    await update.message.reply_text(
        "📍 افراد نزدیک (همشهری)\nجنسیت طرف مقابل رو انتخاب کن:",
        reply_markup=kb.gender_any_inline("pref_gender"),
    )


async def open_anonymous(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stranger match with identity hidden preference pre-selected."""
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if not user_svc.profile_complete(user):
            await update.message.reply_text(T.PROFILE_INCOMPLETE, reply_markup=main_menu())
            return
    s = {"require_identity": False, "play_anonymous": True}
    st.set_state(tg.id, mode="stranger", wait="city", stranger=s)
    await update.message.reply_text(
        "🕶 بازی با ناشناس\nهمشهری می‌خوای یا هرجا اوکیه؟",
        reply_markup=kb.city_pref(),
    )


async def stranger_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    await query.answer()
    tg = update.effective_user
    data = query.data
    s = st.get(tg.id).setdefault("stranger", {})

    if data == "str_cancel":
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username)
            matchmaker.cancel(session, user)
        st.clear(tg.id)
        await query.edit_message_text("از صف خارج شدی.")
        return

    if data.startswith("str_city:"):
        s["same_city"] = data.endswith(":same")
        st.set_state(tg.id, stranger=s, wait="gender")
        await query.edit_message_text("جنسیت طرف مقابل؟", reply_markup=kb.gender_any_inline("pref_gender"))
        return

    if data.startswith("pref_gender:"):
        s["gender"] = data.split(":")[1]
        st.set_state(tg.id, stranger=s, wait="age_from")
        await query.edit_message_text(
            "رنج سنی — از چند سال؟",
            reply_markup=kb.age_options("age_from", AGE_FROM_OPTIONS),
        )
        return

    if data.startswith("age_from:"):
        s["age_from"] = int(data.split(":")[1])
        st.set_state(tg.id, stranger=s, wait="age_to")
        opts = [a for a in AGE_TO_OPTIONS if a >= s["age_from"]]
        await query.edit_message_text(
            "رنج سنی — تا چند سال؟",
            reply_markup=kb.age_options("age_to", opts),
        )
        return

    if data.startswith("age_to:"):
        s["age_to"] = int(data.split(":")[1])
        # If anonymous shortcut already chose identity prefs, skip that step
        if "require_identity" in s:
            await _enqueue_and_match(query, context, tg, s, use_fake=False)
            return
        st.set_state(tg.id, stranger=s, wait="identity")
        await query.edit_message_text("هویت طرف مشخص باشه؟", reply_markup=kb.identity_pref())
        return

    if data.startswith("str_id:"):
        s["require_identity"] = data.endswith(":visible")
        s["play_anonymous"] = not s["require_identity"]
        await _enqueue_and_match(query, context, tg, s, use_fake=False)


async def _enqueue_and_match(query, context, tg, s, use_fake=False, identity_mode="real", fake_id=None):
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        matchmaker.enqueue(
            session,
            user,
            same_city_only=bool(s.get("same_city")),
            preferred_gender=s.get("gender") if s.get("gender") != "any" else "any",
            age_from=s.get("age_from"),
            age_to=s.get("age_to"),
            require_identity=bool(s.get("require_identity", True)),
            play_anonymous=bool(s.get("play_anonymous", False)),
            use_fake_identity=use_fake,
            fake_identity_id=fake_id,
            identity_mode=identity_mode,
        )
        result = matchmaker.try_match(session, user)
        if not result:
            st.clear(tg.id)
            await query.edit_message_text(T.WAITING_MATCH, reply_markup=kb.cancel_match())
            return

        game, other = result
        rnd = game_engine.get_active_round(session, game)
        players = game_engine.get_players(session, game)
        chooser_name = target_name = "?"
        for p in players:
            if rnd and p.user_id == rnd.chooser_user_id:
                chooser_name = game_engine.display_for_player(p)
            if rnd and p.user_id == rnd.target_user_id:
                target_name = game_engine.display_for_player(p)
        text = T.CHOOSE_TRUTH_OR_DARE.format(chooser=chooser_name, target=target_name)
        markup = kb.truth_dare(game.id, rnd.chooser_user_id) if rnd else None

        # notify both
        me_msg = T.MATCH_FOUND + "\n" + _opponent_blurb(session, user, other)
        other_msg = T.MATCH_FOUND + "\n" + _opponent_blurb(session, other, user)
        st.clear(tg.id)
        await query.edit_message_text(me_msg)
        try:
            await context.bot.send_message(other.telegram_id, other_msg)
        except Exception:
            pass
        if rnd and markup:
            chooser = session.get(User, rnd.chooser_user_id)
            if chooser:
                try:
                    await context.bot.send_message(
                        chooser.telegram_id, text, reply_markup=markup
                    )
                except Exception:
                    pass


def _opponent_blurb(session, me: User, other: User) -> str:
    return "حریف:\n" + user_svc.format_profile(other, viewer_settings=me)


async def cancel_match_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    with get_session() as session:
        user = user_svc.get_or_create_user(session, update.effective_user.id)
        ok = matchmaker.cancel(session, user)
    await update.message.reply_text(
        "از صف خارج شدی." if ok else "تو صف نبودی.",
        reply_markup=main_menu(),
    )
