from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import User
from bot.services import game_engine
from bot.services import users as user_svc
from bot.texts import fa as T


async def open_group_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "🙂 بازی در کانال / گروه\n\n"
        "گروه = جمع دوستان با نوبت چرخشی\n"
        "کانال = صاحب کانال می‌پرسه، مخاطب‌ها رأی/کامنت می‌دن",
        reply_markup=kb.group_channel_help(),
    )


async def gc_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if query.data == "gc:group":
        await query.edit_message_text(T.GROUP_INTRO)
    elif query.data == "gc:channel":
        await query.edit_message_text(T.CHANNEL_INTRO)


async def group_game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text(
            "این دستور رو داخل گروه بزن.\n\n" + T.GROUP_INTRO,
            reply_markup=main_menu(),
        )
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session,
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.full_name,
        )
        game = game_engine.create_session(
            session, "group", starter=user, chat_id=chat.id, max_rounds=8
        )
        game.status = "registering"
        game_engine.add_player(session, game, user)
        sid = game.id
        names = "، ".join(
            game_engine.display_for_player(p) for p in game_engine.get_players(session, game)
        )

    await update.message.reply_text(
        T.GROUP_REGISTER_OPEN.format(sid=sid)
        + "\n\n"
        + T.GROUP_PLAYERS_LIST.format(count=1, names=names),
        reply_markup=kb.join_group_game(sid),
    )


async def group_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    data = query.data

    if data.startswith("gjoin:"):
        sid = int(data.split(":")[1])
        with get_session() as session:
            user = user_svc.get_or_create_user(
                session,
                update.effective_user.id,
                update.effective_user.username,
                update.effective_user.full_name,
            )
            game = game_engine.get_session(session, sid)
            if not game or game.status != "registering":
                await query.answer("ثبت‌نام بسته شده.", show_alert=True)
                return
            before = game_engine.player_count(session, game)
            game_engine.add_player(session, game, user)
            after = game_engine.player_count(session, game)
            names = "، ".join(
                game_engine.display_for_player(p) for p in game_engine.get_players(session, game)
            )
        if before == after:
            await query.answer(T.ALREADY_JOINED, show_alert=True)
        else:
            await query.answer("ثبت شد!")
        try:
            await query.edit_message_text(
                T.GROUP_REGISTER_OPEN.format(sid=sid)
                + "\n\n"
                + T.GROUP_PLAYERS_LIST.format(count=after, names=names),
                reply_markup=kb.join_group_game(sid),
            )
        except Exception:
            pass
        return

    if data.startswith("gstart:"):
        sid = int(data.split(":")[1])
        with get_session() as session:
            user = user_svc.get_or_create_user(
                session, update.effective_user.id, update.effective_user.username
            )
            game = game_engine.get_session(session, sid)
            if not game or game.status != "registering":
                await query.answer("بازی قبلاً شروع شده یا نیست.", show_alert=True)
                return
            if game.starter_user_id and game.starter_user_id != user.id:
                await query.answer("فقط کسی که بازی رو ساخته می‌تونه شروع کنه.", show_alert=True)
                return
            if game_engine.player_count(session, game) < 2:
                await query.answer(T.NEED_TWO_PLAYERS, show_alert=True)
                return
            await query.answer()
            rnd = game_engine.start_group_rotation(session, game)
            chooser = session.get(User, rnd.chooser_user_id)
            players = game_engine.get_players(session, game)
            chooser_name = target_name = "?"
            for p in players:
                if p.user_id == rnd.chooser_user_id:
                    chooser_name = game_engine.display_for_player(p)
                if p.user_id == rnd.target_user_id:
                    target_name = game_engine.display_for_player(p)
            text = T.GROUP_TURN.format(chooser=chooser_name, target=target_name)
            markup = kb.truth_dare(game.id, rnd.chooser_user_id)
            chat_id = game.chat_id
            chooser_tg = chooser.telegram_id if chooser else None

        await query.edit_message_text(T.GROUP_STARTED)
        if chat_id:
            await context.bot.send_message(chat_id, text, reply_markup=markup)
        if chooser_tg:
            try:
                await context.bot.send_message(chooser_tg, text, reply_markup=markup)
            except Exception:
                pass
