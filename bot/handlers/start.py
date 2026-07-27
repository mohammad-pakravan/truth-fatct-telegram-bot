from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import invite as invite_svc
from bot.services import users as user_svc
from bot.services import game_engine
from bot.texts import fa as T
from bot import keyboards as kb
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
        complete = user_svc.profile_complete(user)

        # deep link invite — only start game if profile is ready
        if args and args[0].startswith("inv_"):
            if not complete:
                await update.message.reply_text(
                    T.WELCOME.format(name=first),
                    reply_markup=main_menu(),
                )
                await wizard.start_wizard(
                    update, context, feature="دعوت دوست"
                )
                st.set_state(tg.id, pending_invite=args[0][4:])
                return

            token = args[0][4:]
            inv = invite_svc.get_invite(session, token)
            if not inv:
                await update.message.reply_text(T.INVITE_INVALID, reply_markup=main_menu())
                return
            if inv.owner_id == user.id:
                await update.message.reply_text(T.INVITE_SELF, reply_markup=main_menu())
                return
            label = invite_svc.inviter_label(inv)
            game = game_engine.create_session(session, "friends", starter=inv.owner)
            game_engine.add_player(session, game, inv.owner)
            game_engine.add_player(session, game, user)
            rnd = game_engine.start_two_player(session, game)
            from bot.models import User

            chooser_u = session.get(User, rnd.chooser_user_id)
            target_u = session.get(User, rnd.target_user_id)
            chooser_name = user_svc.public_name(chooser_u) if chooser_u else "?"
            target_name = user_svc.public_name(target_u) if target_u else "?"

            await update.message.reply_text(
                f"{T.INVITE_ACCEPTED}\nدعوت از: {label}",
                reply_markup=kb.in_game_menu(is_chooser=rnd.chooser_user_id == user.id),
            )
            text = T.CHOOSE_TRUTH_OR_DARE.format(chooser=chooser_name, target=target_name)
            markup = kb.truth_dare(game.id, rnd.chooser_user_id)
            if chooser_u and chooser_u.telegram_id:
                try:
                    await context.bot.send_message(
                        chooser_u.telegram_id, text, reply_markup=markup
                    )
                    from bot.handlers import gameplay

                    await gameplay.send_in_game_menu(
                        context, chooser_u.telegram_id, is_chooser=True
                    )
                except Exception:
                    pass
            if target_u and target_u.telegram_id != tg.id:
                try:
                    await context.bot.send_message(
                        target_u.telegram_id,
                        f"بازی با {label} شروع شد. منتظر انتخاب جرئت/حقیقت باش.",
                        reply_markup=kb.in_game_menu(is_chooser=False),
                    )
                except Exception:
                    pass
            else:
                await update.message.reply_text("منتظر انتخاب طرف مقابل باش.")
            return

    st.clear(tg.id)
    await update.message.reply_text(T.WELCOME.format(name=first), reply_markup=main_menu())


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text == T.BTN_BACK:
        st.clear(update.effective_user.id)
        await update.message.reply_text(T.MAIN_MENU_TITLE, reply_markup=main_menu())
