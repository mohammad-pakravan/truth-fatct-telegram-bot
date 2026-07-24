from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.config import contact_display
from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import users as user_svc
from bot.texts import fa as T


async def open_hub_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    st.set_state(update.effective_user.id, mode="hub_profile")
    await update.message.reply_text(T.HUB_PROFILE_TEXT, reply_markup=kb.hub_profile_menu())


async def open_hub_friends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    st.set_state(update.effective_user.id, mode="hub_friends")
    await update.message.reply_text(T.HUB_FRIENDS_TEXT, reply_markup=kb.hub_friends_menu())


async def open_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(T.HELP_TEXT, reply_markup=main_menu())


async def open_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        T.CONTACT_TEXT.format(contact=contact_display()),
        reply_markup=main_menu(),
    )


async def hub_profile_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle buttons inside profile hub. Returns True if handled."""
    if not update.message or not update.effective_user:
        return False
    if st.get(update.effective_user.id).get("mode") != "hub_profile":
        return False

    text = (update.message.text or "").strip()
    tg = update.effective_user

    if text == T.BTN_BACK:
        st.clear(tg.id)
        await update.message.reply_text(T.MAIN_MENU_TITLE, reply_markup=main_menu())
        return True

    if text == T.BTN_SHOW_PROFILE:
        from bot.services.profile_card import send_profile_card

        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            session.expunge(user)
        await send_profile_card(
            update.message,
            context,
            user,
            with_main_menu=False,
        )
        await update.message.reply_text(T.HUB_PROFILE_TEXT, reply_markup=kb.hub_profile_menu())
        return True

    if text == T.BTN_PROFILE:
        from bot.handlers import profile

        await profile.open_profile(update, context)
        return True

    if text == T.BTN_RUN_WIZARD:
        from bot.handlers import wizard

        await wizard.start_wizard(update, context, force=True)
        return True

    if text == T.BTN_HISTORY:
        from bot.handlers import history

        await history.open_history(update, context)
        return True

    if text == T.BTN_FAKE:
        from bot.handlers import fake

        await fake.open_fake(update, context)
        return True

    if text == T.BTN_GAME_SETTINGS:
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            markup = kb.settings_keyboard(user)
        await update.message.reply_text(T.SETTINGS_MENU, reply_markup=markup)
        return True

    return False


async def hub_friends_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user:
        return False
    if st.get(update.effective_user.id).get("mode") != "hub_friends":
        return False

    text = (update.message.text or "").strip()
    tg = update.effective_user

    if text == T.BTN_BACK:
        st.clear(tg.id)
        await update.message.reply_text(T.MAIN_MENU_TITLE, reply_markup=main_menu())
        return True

    if text == T.BTN_FRIENDS:
        from bot.handlers import friends

        await friends.open_friends(update, context)
        return True

    if text == T.BTN_GROUP_CHANNEL:
        from bot.handlers import group

        await group.open_group_channel(update, context)
        return True

    return False
