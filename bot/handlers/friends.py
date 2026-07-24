from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import invite as invite_svc
from bot.services import users as user_svc
from bot.texts import fa as T


async def open_friends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    st.set_state(update.effective_user.id, mode="friends")
    await update.message.reply_text(T.FRIENDS_INTRO, reply_markup=kb.invite_display_mode())


async def friends_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    await query.answer()
    if not query.data.startswith("inv_disp:"):
        return
    mode = query.data.split(":", 1)[1]
    tg = update.effective_user

    if mode == "nickname":
        st.set_state(tg.id, mode="friends", waiting="inv_nick", inv_mode="nickname")
        await query.edit_message_text("لقب یا اسمی که توی دعوت نشون داده بشه رو بفرست:")
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        inv = invite_svc.create_invite(session, user, display_mode=mode)
        link = invite_svc.invite_link_url(inv.token)
    await query.edit_message_text(T.INVITE_CREATED.format(link=link))


async def friends_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    if st.get(tg.id).get("waiting") != "inv_nick":
        return
    label = (update.message.text or "").strip()[:64]
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        inv = invite_svc.create_invite(
            session, user, display_mode="nickname", custom_label=label
        )
        link = invite_svc.invite_link_url(inv.token)
    st.clear(tg.id)
    await update.message.reply_text(T.INVITE_CREATED.format(link=link), reply_markup=main_menu())
