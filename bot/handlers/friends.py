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
from bot.services.glass_msg import show_td_glass, upsert_hub
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
        st.set_state(tg.id, waiting="inv_nick", mode="friends")
        await query.edit_message_text(T.INVITE_NICK_PROMPT)
        return
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        from bot.services import moderation as mod_svc

        blocked = mod_svc.restriction_message(session, user)
        if blocked:
            await query.edit_message_text(blocked)
            return
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
            from bot.services import moderation as mod_svc

            blocked = mod_svc.restriction_message(session, user)
            if blocked:
                await update.message.reply_text(blocked, reply_markup=main_menu())
                return True
            accepted = invite_svc.accept_invite(session, user, token)
            rnd = accepted.round
            label = accepted.label

            chooser_name = "?"
            target_name = "?"
            chooser_tg: int | None = None
            waiter_tg: int | None = None
            for p in game_engine.get_players(session, accepted.game):
                name = game_engine.display_for_player(p)
                if p.user_id == rnd.chooser_user_id:
                    chooser_name = name
                    chooser_tg = p.user.telegram_id if p.user else None
                if p.user_id == rnd.target_user_id:
                    target_name = name
                    waiter_tg = p.user.telegram_id if p.user else None

            game_id = accepted.game.id
            chooser_user_id = rnd.chooser_user_id
    except RuntimeError as exc:
        code = str(exc)
        msg = {
            "invalid": T.INVITE_INVALID,
            "self": T.INVITE_SELF,
            "busy": T.INVITE_BUSY,
            "restricted": T.RESTRICTED_PERMANENT.format(reason="یکی از طرفین محدود است"),
        }.get(code, T.INVITE_INVALID)
        await update.message.reply_text(msg, reply_markup=main_menu())
        return True

    match_body = T.INVITE_ACCEPTED.format(label=label)
    turn = T.CHOOSE_TRUTH_OR_DARE.format(chooser=chooser_name, target=target_name)

    if chooser_tg:
        try:
            mid = await upsert_hub(
                context.bot,
                chooser_tg,
                T.MATCH_HUB.format(match_body=match_body),
                reply_kb=kb.in_game_menu(is_chooser=True),
                replace_keyboard=True,
            )
            glass_id = await show_td_glass(
                context.bot,
                chooser_tg,
                session_id=game_id,
                chooser_id=chooser_user_id,
                turn_text=turn,
            )
            st.set_state(
                chooser_tg, game_hub_message_id=mid, game_glass_message_id=glass_id
            )
        except Exception:
            pass
    if waiter_tg and waiter_tg != chooser_tg:
        try:
            mid = await upsert_hub(
                context.bot,
                waiter_tg,
                T.MATCH_START_WAITER.format(match_body=match_body, turn=turn),
                reply_kb=kb.in_game_menu(is_chooser=False),
                replace_keyboard=True,
            )
            st.set_state(waiter_tg, game_hub_message_id=mid)
        except Exception:
            pass
    return True
