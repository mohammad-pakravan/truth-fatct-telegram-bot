from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import game_engine
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
        await query.edit_message_text(T.INVITE_NICK_PROMPT)
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        inv = invite_svc.create_invite(session, user, display_mode=mode)
        link = invite_svc.invite_link_url(inv.token)
        label = invite_svc.inviter_label(inv)
    await query.edit_message_text(T.INVITE_CREATED.format(link=link, label=label))


async def friends_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    if st.get(tg.id).get("waiting") != "inv_nick":
        return
    label = (update.message.text or "").strip()[:64]
    if not label:
        await update.message.reply_text(T.INVITE_NICK_PROMPT)
        return
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        inv = invite_svc.create_invite(
            session, user, display_mode="nickname", custom_label=label
        )
        link = invite_svc.invite_link_url(inv.token)
        shown = invite_svc.inviter_label(inv)
    st.clear(tg.id)
    await update.message.reply_text(
        T.INVITE_CREATED.format(link=link, label=shown),
        reply_markup=main_menu(),
    )


async def accept_invite_and_notify(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    token: str,
    *,
    intro: str | None = None,
) -> bool:
    """Accept a friend invite token and notify both players. Returns True if handled."""
    if not update.effective_user or not update.message:
        return False
    tg = update.effective_user

    if intro:
        await update.message.reply_text(intro)

    try:
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            accepted = invite_svc.accept_invite(session, user, token)
            rnd = accepted.round
            label = accepted.label

            chooser_name = "?"
            target_name = "?"
            chooser_tg: int | None = None
            for p in game_engine.get_players(session, accepted.game):
                name = game_engine.display_for_player(p)
                if p.user_id == rnd.chooser_user_id:
                    chooser_name = name
                    chooser_tg = p.user.telegram_id if p.user else None
                if p.user_id == rnd.target_user_id:
                    target_name = name

            joiner_is_chooser = rnd.chooser_user_id == user.id
            game_id = accepted.game.id
            chooser_user_id = rnd.chooser_user_id
    except RuntimeError as exc:
        code = str(exc)
        msg = {
            "invalid": T.INVITE_INVALID,
            "self": T.INVITE_SELF,
            "busy": T.INVITE_BUSY,
        }.get(code, T.INVITE_INVALID)
        await update.message.reply_text(msg, reply_markup=main_menu())
        return True

    await update.message.reply_text(
        T.INVITE_ACCEPTED.format(label=label),
        reply_markup=kb.in_game_menu(is_chooser=joiner_is_chooser),
    )

    choose_text = T.CHOOSE_TRUTH_OR_DARE.format(chooser=chooser_name, target=target_name)
    markup = kb.truth_dare(game_id, chooser_user_id)

    if chooser_tg == tg.id:
        await update.message.reply_text(choose_text, reply_markup=markup)
        return True

    if chooser_tg:
        try:
            await context.bot.send_message(chooser_tg, choose_text, reply_markup=markup)
            from bot.handlers import gameplay

            await gameplay.send_in_game_menu(context, chooser_tg, is_chooser=True)
        except Exception:
            pass

    await update.message.reply_text(T.INVITE_WAIT_CHOICE)
    return True
