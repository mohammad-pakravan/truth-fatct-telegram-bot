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


def _is_skip_photo(text: str) -> bool:
    """Match skip-photo button with/without emoji variation selector."""
    norm = (text or "").replace("\ufe0f", "").strip()
    return norm in {
        T.BTN_SKIP_PHOTO.replace("\ufe0f", ""),
        T.BTN_SKIP.replace("\ufe0f", ""),
        "⏭ فعلاً بدون عکس",
    }


async def _restore_profile_hub(message, tg_id: int, text: str = "باشه ✅") -> None:
    st.set_state(tg_id, mode="hub_profile", waiting=None)
    await message.reply_text(text, reply_markup=kb.hub_profile_menu())


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

    if mode != "profile" and waiting not in {"name", "city", "age", "photo", "settings", "nickname"}:
        return

    if text == T.BTN_BACK:
        await _restore_profile_hub(update.message, tg.id, T.HUB_PROFILE_TEXT)
        return

    if text == T.BTN_SHOW_PROFILE:
        await _send_edit_card(update.message, context, tg)
        return

    if text == T.BTN_RUN_WIZARD:
        await wizard.start_wizard(update, context, force=True)
        return

    if _is_skip_photo(text) and waiting == "photo":
        await _restore_profile_hub(update.message, tg.id, "عکس تغییر نکرد.")
        return

    waiting = st.get(tg.id).get("waiting")
    if waiting == "name":
        if not text:
            await update.message.reply_text("فقط یه اسم یا لقب بفرست 😊")
            return
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.display_name = text[:128]
            new_val = user.display_name
        await _restore_profile_hub(update.message, tg.id, f"اسم عوض شد به «{new_val}»")
        return
    if waiting == "nickname":
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            if text in {"-", "—", "پاک", "حذف"}:
                user.nickname = None
                await _restore_profile_hub(update.message, tg.id, T.NICKNAME_CLEARED)
                return
            user.nickname = text[:64]
            nick = user.nickname
        await _restore_profile_hub(update.message, tg.id, T.NICKNAME_SAVED.format(nick=nick))
        return
    if waiting == "city":
        if len(text) < 2:
            await update.message.reply_text("اسم شهر رو کامل‌تر بنویس 🙂")
            return
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.city = text[:64]
            new_val = user.city
        await _restore_profile_hub(update.message, tg.id, f"شهر عوض شد به «{new_val}»")
        return
    if waiting == "age":
        from bot.config import MAX_USER_AGE, MIN_USER_AGE

        if not text.isdigit() or not (MIN_USER_AGE <= int(text) <= MAX_USER_AGE):
            await update.message.reply_text(T.AGE_INVALID)
            return
        age = int(text)
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.age = age
        await _restore_profile_hub(update.message, tg.id, f"سن عوض شد به «{age}»")
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
        if action == "nickname":
            st.set_state(tg.id, waiting="nickname")
            await msg.reply_text(T.ASK_NICKNAME, reply_markup=kb.back_menu())
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
            pass
        await _restore_profile_hub(msg, tg.id, f"جنسیت عوض شد به «{label}»")
        return

    if data.startswith("pprov:"):
        from bot.provinces import PROVINCES

        idx = int(data.split(":")[1])
        province = PROVINCES[idx]
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.province = province

        from bot.handlers import membership as mem_handler

        gated = await mem_handler.maybe_prompt_sponsor(
            context=context,
            query=query,
            provinces=province,
            continue_to="profile_done",
        )
        if gated:
            return

        try:
            await query.edit_message_text(f"استان عوض شد به «{province}»")
        except Exception:
            pass
        await _restore_profile_hub(msg, tg.id, f"استان عوض شد به «{province}»")
        return

    if data.startswith("set:"):
        field = data.split(":", 1)[1]
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            try:
                user_svc.toggle_setting(user, field)
            except ValueError:
                await query.answer("تنظیم نامعتبر.", show_alert=True)
                return
            markup = kb.settings_keyboard(user)
        await query.edit_message_text(T.SETTINGS_MENU, reply_markup=markup)
        return


async def set_private_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if user_svc.is_account_private(user):
            await update.message.reply_text(T.ACCOUNT_ALREADY_PRIVATE)
            return
        user_svc.set_account_private(user, True)
    await update.message.reply_text(T.ACCOUNT_SET_PRIVATE_OK)


async def privacy_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    tg = update.effective_user
    if query.data != "priv:on":
        await query.answer()
        return
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if user_svc.is_account_private(user):
            await query.answer(T.ACCOUNT_ALREADY_PRIVATE, show_alert=True)
            return
        user_svc.set_account_private(user, True)
    await query.answer(T.ACCOUNT_SET_PRIVATE_OK, show_alert=True)
