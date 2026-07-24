from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.services import users as user_svc
from bot.services.profile_card import send_profile_card
from bot.texts import fa as T
from bot.handlers import wizard


async def _send_edit_card(message, context, tg_user) -> None:
    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, tg_user.id, tg_user.username, tg_user.full_name
        )
        session.expunge(user)
    await send_profile_card(
        message,
        context,
        user,
        intro="از دکمه‌های زیر هر چیزی رو که می‌خوای عوض کن ✨",
        with_main_menu=False,
        edit_mode=True,
    )


async def open_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    st.set_state(update.effective_user.id, mode="profile")
    await _send_edit_card(update.message, context, update.effective_user)


async def profile_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    text = (update.message.text or "").strip()
    mode = st.get(tg.id).get("mode")
    waiting = st.get(tg.id).get("waiting")

    if mode != "profile" and waiting not in {"name", "city", "age", "photo", "settings"}:
        return

    if text == T.BTN_BACK:
        st.set_state(tg.id, mode="hub_profile", waiting=None)
        await update.message.reply_text(T.HUB_PROFILE_TEXT, reply_markup=kb.hub_profile_menu())
        return

    if text == T.BTN_SHOW_PROFILE:
        await _send_edit_card(update.message, context, tg)
        return

    if text == T.BTN_RUN_WIZARD:
        await wizard.start_wizard(update, context, force=True)
        return

    if text == T.BTN_SKIP_PHOTO and waiting == "photo":
        st.set_state(tg.id, waiting=None)
        await update.message.reply_text("عکس تغییر نکرد.")
        return

    waiting = st.get(tg.id).get("waiting")
    if waiting == "name":
        if len(text) < 2:
            await update.message.reply_text("اسم حداقل ۲ حرف باشه 🙂")
            return
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.display_name = text[:128]
            new_val = user.display_name
        st.set_state(tg.id, waiting=None)
        await update.message.reply_text(f"اسم عوض شد به «{new_val}»")
        return
    if waiting == "city":
        if len(text) < 2:
            await update.message.reply_text("اسم شهر رو کامل‌تر بنویس 🙂")
            return
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.city = text[:64]
            new_val = user.city
        st.set_state(tg.id, waiting=None)
        await update.message.reply_text(f"شهر عوض شد به «{new_val}»")
        return
    if waiting == "age":
        if not text.isdigit() or not (10 <= int(text) <= 99):
            await update.message.reply_text("سن معتبر بفرست (۱۰ تا ۹۹).")
            return
        age = int(text)
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.age = age
        st.set_state(tg.id, waiting=None)
        await update.message.reply_text(f"سن عوض شد به «{age}»")
        return


async def profile_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    await query.answer()
    data = query.data
    tg = update.effective_user
    msg = query.message

    if data == "profile_card:edit":
        st.set_state(tg.id, mode="profile")
        await _send_edit_card(msg, context, tg)
        return

    if data.startswith("pedit:"):
        action = data.split(":", 1)[1]
        st.set_state(tg.id, mode="profile")

        if action == "name":
            st.set_state(tg.id, waiting="name")
            await msg.reply_text(T.ASK_NAME, reply_markup=kb.back_menu())
            return
        if action == "city":
            st.set_state(tg.id, waiting="city")
            await msg.reply_text(T.ASK_CITY, reply_markup=kb.back_menu())
            return
        if action == "province":
            await msg.reply_text(
                T.ASK_PROVINCE,
                reply_markup=kb.provinces_pick_one("pprov"),
            )
            return
        if action == "age":
            st.set_state(tg.id, waiting="age")
            await msg.reply_text(T.ASK_AGE, reply_markup=kb.back_menu())
            return
        if action == "gender":
            await msg.reply_text(T.ASK_GENDER, reply_markup=kb.gender_inline("pgender"))
            return
        if action == "photo":
            st.set_state(tg.id, waiting="photo")
            await msg.reply_text(T.ASK_PHOTO, reply_markup=kb.skip_photo_menu())
            return
        if action == "settings":
            with get_session() as session:
                user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
                markup = kb.settings_keyboard(user)
            await msg.reply_text(T.SETTINGS_MENU, reply_markup=markup)
            return
        return

    if data.startswith("pgender:"):
        gender = data.split(":", 1)[1]
        label = "پسر" if gender == "male" else "دختر"
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.gender = gender
        try:
            await query.edit_message_text(f"جنسیت عوض شد به «{label}»")
        except Exception:
            await msg.reply_text(f"جنسیت عوض شد به «{label}»")
        return

    if data.startswith("pprov:"):
        from bot.provinces import PROVINCES

        idx = int(data.split(":")[1])
        province = PROVINCES[idx]
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.province = province
        try:
            await query.edit_message_text(f"استان عوض شد به «{province}»")
        except Exception:
            await msg.reply_text(f"استان عوض شد به «{province}»")
        return

    if data.startswith("set:"):
        field = data.split(":", 1)[1]
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user_svc.toggle_setting(user, field)
            markup = kb.settings_keyboard(user)
        await query.edit_message_text(T.SETTINGS_MENU, reply_markup=markup)
        return
