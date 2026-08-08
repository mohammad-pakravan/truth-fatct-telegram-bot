from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.config import AGE_FROM_OPTIONS, AGE_TO_OPTIONS
from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import game_engine
from bot.services import match_flow
from bot.services import matchmaker
from bot.services import users as user_svc
from bot.texts import fa as T


async def _guard_active_game(update: Update, context: ContextTypes.DEFAULT_TYPE, session, user) -> bool:
    """If already in a game, restore in-game keyboard and return True."""
    if not game_engine.active_session_for_user(session, user):
        return False
    from bot.handlers import gameplay

    await gameplay.resume_active_game_keyboard(
        context, update.effective_user.id, reply_to=update.message
    )
    return True


async def open_stranger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if not user_svc.profile_complete(user):
            await update.message.reply_text(T.PROFILE_INCOMPLETE, reply_markup=main_menu())
            return
        if await _guard_active_game(update, context, session, user):
            return
        city = user.city or "—"

    st.set_state(tg.id, mode="stranger", wait="city", stranger={})
    await update.message.reply_text(T.STRANGER_INTRO)
    await update.message.reply_text(
        T.STRANGER_ASK_CITY.format(city=city),
        reply_markup=kb.city_pref(),
    )


async def open_nearby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nearby matchmaking via Telegram live location + radius."""
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if not user_svc.profile_complete(user):
            await update.message.reply_text(T.PROFILE_INCOMPLETE, reply_markup=main_menu())
            return
        if await _guard_active_game(update, context, session, user):
            return
    st.set_state(tg.id, mode="nearby", wait="location", stranger={})
    await update.message.reply_text(
        T.NEARBY_ASK_LOCATION,
        reply_markup=kb.request_location_menu(),
    )


async def nearby_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle shared Telegram location for nearby flow. Returns True if handled."""
    if not update.message or not update.effective_user or not update.message.location:
        return False
    tg = update.effective_user
    state = st.get(tg.id)
    if state.get("mode") != "nearby" or state.get("wait") != "location":
        return False

    loc = update.message.location
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        from datetime import datetime

        user.latitude = loc.latitude
        user.longitude = loc.longitude
        user.location_updated_at = datetime.utcnow()

    st.set_state(tg.id, mode="nearby", wait="radius")
    await update.message.reply_text(
        T.NEARBY_ASK_RADIUS,
        reply_markup=kb.radius_keyboard(),
    )
    await update.message.reply_text(
        "شعاع رو از دکمه‌های بالا انتخاب کن 👆",
        reply_markup=main_menu(),
    )
    return True


async def nearby_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    if not query.data.startswith("near_r:"):
        return
    await query.answer()
    tg = update.effective_user
    state = st.get(tg.id)
    if state.get("mode") != "nearby":
        await query.edit_message_text("اول از منو «افراد نزدیک» رو بزن و لوکیشن بفرست.")
        return

    km = int(query.data.split(":")[1])
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if user.latitude is None or user.longitude is None:
            await query.edit_message_text(T.NEARBY_ASK_LOCATION)
            await context.bot.send_message(
                tg.id, T.NEARBY_ASK_LOCATION, reply_markup=kb.request_location_menu()
            )
            st.set_state(tg.id, mode="nearby", wait="location")
            return

    await query.edit_message_text(T.NEARBY_SEARCHING.format(km=km))
    await match_flow.enqueue_and_maybe_match(
        context,
        telegram_user=tg,
        prefs={
            "same_city": False,
            "gender": "any",
            "age_from": None,
            "age_to": None,
            "require_identity": True,
            "play_anonymous": False,
            "radius_km": km,
        },
        queue_mode="nearby",
        edit_message=query.message,
    )


async def open_anonymous(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Instant anonymous match — no gender/age/city filters."""
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if not user_svc.profile_complete(user):
            await update.message.reply_text(T.PROFILE_INCOMPLETE, reply_markup=main_menu())
            return
        if await _guard_active_game(update, context, session, user):
            return

    sent = await update.message.reply_text(T.ANON_SEARCHING, reply_markup=kb.queue_menu())
    st.set_state(tg.id, game_hub_message_id=sent.message_id, mode="queued")
    await match_flow.enqueue_and_maybe_match(
        context,
        telegram_user=tg,
        prefs={
            "same_city": False,
            "gender": "any",
            "age_from": None,
            "age_to": None,
            "require_identity": False,
            "play_anonymous": True,
        },
        queue_mode="anonymous",
        hub_message_id=sent.message_id,
    )


async def leave_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle leave-queue reply button. Returns True if handled."""
    if not update.message or not update.effective_user:
        return False
    text = (update.message.text or "").strip()
    tg = update.effective_user

    if text == T.BTN_CANCEL and st.get(tg.id).get("mode") == "nearby":
        st.clear(tg.id)
        await update.message.reply_text(T.LEFT_QUEUE, reply_markup=main_menu())
        return True

    # Accept emoji / non-emoji variants (Telegram clients sometimes strip)
    if text not in (T.BTN_LEAVE_QUEUE, T.LEAVE_QUEUE) and "خروج از صف" not in text:
        return False

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username)
        ok = matchmaker.cancel(session, user)
    st.clear(tg.id)
    # Always give visible feedback + restore main menu
    await update.message.reply_text(
        T.LEFT_QUEUE if ok else T.NOT_IN_QUEUE,
        reply_markup=main_menu(),
    )
    return True


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
            ok = matchmaker.cancel(session, user)
        st.clear(tg.id)
        await query.edit_message_text(T.LEFT_QUEUE if ok else T.NOT_IN_QUEUE)
        try:
            await context.bot.send_message(tg.id, T.MAIN_MENU_TITLE, reply_markup=main_menu())
        except Exception:
            pass
        return

    if data.startswith("str_city:"):
        s["same_city"] = data.endswith(":same")
        st.set_state(tg.id, stranger=s, wait="gender")
        await query.edit_message_text(
            T.STRANGER_ASK_GENDER,
            reply_markup=kb.gender_any_inline("pref_gender"),
        )
        return

    if data.startswith("pref_gender:"):
        s["gender"] = data.split(":")[1]
        st.set_state(tg.id, stranger=s, wait="age_from")
        await query.edit_message_text(
            T.STRANGER_ASK_AGE_FROM,
            reply_markup=kb.age_options("age_from", AGE_FROM_OPTIONS),
        )
        return

    if data.startswith("age_from:"):
        s["age_from"] = int(data.split(":")[1])
        st.set_state(tg.id, stranger=s, wait="age_to")
        opts = [a for a in AGE_TO_OPTIONS if a >= s["age_from"]]
        await query.edit_message_text(
            T.STRANGER_ASK_AGE_TO.format(from_age=s["age_from"]),
            reply_markup=kb.age_options("age_to", opts),
        )
        return

    if data.startswith("age_to:"):
        s["age_to"] = int(data.split(":")[1])
        # Fake-identity path may pre-set require_identity and skip remaining prompts
        if "require_identity" in s and st.get(tg.id).get("mode") == "fake_match":
            await _enqueue_and_match(
                query, context, tg, s, use_fake=True, queue_mode="fake"
            )
            return
        st.set_state(tg.id, stranger=s, wait="identity")
        await query.edit_message_text(
            T.STRANGER_ASK_IDENTITY,
            reply_markup=kb.identity_pref(),
        )
        return

    if data.startswith("str_id:"):
        visible = data.endswith(":visible")
        s["require_identity"] = visible
        s["play_anonymous"] = not visible
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.show_identity = visible
        st.set_state(tg.id, stranger=s, wait="allow_anon")
        await query.edit_message_text(
            T.STRANGER_ASK_ALLOW_ANON,
            reply_markup=kb.allow_anon_pref(),
        )
        return

    if data.startswith("str_allow:"):
        allow = data.endswith(":yes")
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.allow_anonymous_requests = allow
        await _enqueue_and_match(query, context, tg, s, use_fake=False, queue_mode="stranger")


async def _enqueue_and_match(
    query,
    context,
    tg,
    s,
    use_fake=False,
    identity_mode="real",
    fake_id=None,
    queue_mode="stranger",
):
    await match_flow.enqueue_and_maybe_match(
        context,
        telegram_user=tg,
        prefs=s,
        use_fake=use_fake,
        identity_mode=identity_mode,
        fake_id=fake_id,
        queue_mode=queue_mode,
        edit_message=query.message,
    )


async def cancel_match_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    with get_session() as session:
        user = user_svc.get_or_create_user(session, update.effective_user.id)
        ok = matchmaker.cancel(session, user)
    st.clear(update.effective_user.id)
    await update.message.reply_text(
        T.LEFT_QUEUE if ok else T.NOT_IN_QUEUE,
        reply_markup=main_menu(),
    )
