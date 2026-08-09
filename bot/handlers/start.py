from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import users as user_svc
from bot.texts import fa as T
from bot import state as st
from bot.handlers import wizard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    tg = update.effective_user
    args = context.args or []
    first = (tg.first_name or tg.full_name or "رفیق").split()[0]

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session,
            tg.id,
            username=tg.username,
            full_name=tg.full_name,
        )
        from bot.handlers import user_profile

        await user_profile.flush_online_notifies(context, session, user)
        complete = user_svc.profile_complete(user)

        # deep link invite — only start game if profile is ready
        if args and args[0].startswith("inv_"):
            token = args[0][4:]
            if not complete:
                await update.message.reply_text(
                    T.WELCOME.format(name=first),
                    reply_markup=main_menu(tg.id),
                )
                await wizard.start_wizard(
                    update, context, feature="دعوت دوست"
                )
                st.set_state(tg.id, pending_invite=token)
                return

            from bot.handlers import friends

            await friends.accept_invite_and_notify(update, context, token)
            return

    st.clear(tg.id)
    await update.message.reply_text(T.WELCOME.format(name=first), reply_markup=main_menu(tg.id))


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text == T.BTN_BACK:
        st.clear(update.effective_user.id)
        await update.message.reply_text(
            T.MAIN_MENU_TITLE, reply_markup=main_menu(update.effective_user.id)
        )
