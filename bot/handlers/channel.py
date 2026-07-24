from __future__ import annotations

import json
from collections import Counter

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import Round, Vote
from bot.services import game_engine
from bot.services import questions
from bot.services import users as user_svc
from bot.texts import fa as T


async def channel_game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    chat = update.effective_chat
    tg = update.effective_user

    # If used inside a channel (rare for commands) or private with args
    if chat and chat.type == ChatType.CHANNEL:
        channel_id = chat.id
        st.set_state(tg.id, mode="channel", channel_id=channel_id, wait="ch_mode")
        await update.message.reply_text(T.CHANNEL_MODE_ASK, reply_markup=kb.channel_answer_mode())
        return

    args = context.args or []
    if args and args[0].lstrip("-").isdigit():
        channel_id = int(args[0])
        st.set_state(tg.id, mode="channel", channel_id=channel_id, wait="ch_mode")
        await update.message.reply_text(T.CHANNEL_MODE_ASK, reply_markup=kb.channel_answer_mode())
        return

    st.set_state(tg.id, mode="channel", wait="channel_id")
    await update.message.reply_text(
        "آیدی عددی کانال رو بفرست (ربات باید ادمین باشه).\n"
        "مثال: -1001234567890\n\n"
        + T.CHANNEL_INTRO,
        reply_markup=main_menu(),
    )


async def channel_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    wait = st.get(tg.id).get("wait")
    text = (update.message.text or "").strip()

    if wait == "channel_id":
        try:
            channel_id = int(text)
        except ValueError:
            await update.message.reply_text("آیدی عددی معتبر بفرست.")
            return
        st.set_state(tg.id, channel_id=channel_id, wait="ch_mode")
        await update.message.reply_text(T.CHANNEL_MODE_ASK, reply_markup=kb.channel_answer_mode())
        return

    if wait == "ch_options":
        options = [line.strip() for line in text.splitlines() if line.strip()]
        if len(options) < 2:
            await update.message.reply_text("حداقل ۲ گزینه لازم است.")
            return
        channel_id = st.get(tg.id).get("channel_id")
        await _start_channel_round(update, context, channel_id, "buttons", options)
        st.clear(tg.id)
        return


async def channel_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    await query.answer()
    data = query.data
    tg = update.effective_user

    if data.startswith("ch_mode:"):
        mode = data.split(":")[1]
        channel_id = st.get(tg.id).get("channel_id")
        if not channel_id:
            await query.edit_message_text("اول /channel_game رو بزن و آیدی کانال رو بده.")
            return
        if mode == "comments":
            # Try to detect discussion group via getChat
            try:
                chat = await context.bot.get_chat(channel_id)
                linked = getattr(chat, "linked_chat_id", None)
            except Exception:
                linked = None
            if not linked:
                await query.edit_message_text(T.CHANNEL_NEED_DISCUSSION)
                return
            st.set_state(tg.id, discussion_chat_id=linked)
            await _start_channel_round(query, context, channel_id, "comments", None, linked)
            st.clear(tg.id)
            return

        st.set_state(tg.id, wait="ch_options", channel_answer_mode="buttons")
        await query.edit_message_text(T.CHANNEL_OPTIONS_ASK)
        return

    if data.startswith("ch_vote:"):
        # ch_vote:session:round:truth|dare
        _, sid, rid, value = data.split(":")
        await _cast_vote(query, context, int(sid), int(rid), value, kind="td")
        return

    if data.startswith("ch_opt:"):
        _, sid, rid, idx = data.split(":")
        await _cast_vote(query, context, int(sid), int(rid), idx, kind="opt")
        return


async def _start_channel_round(source, context, channel_id, answer_mode, options, discussion_id=None):
    is_query = hasattr(source, "edit_message_text")
    tg_user = source.from_user if is_query else source.effective_user
    message_reply = source.edit_message_text if is_query else source.message.reply_text

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg_user.id, tg_user.username, tg_user.full_name)
        game = game_engine.create_session(session, "channel", starter=user, chat_id=channel_id)
        game.status = "playing"
        game.channel_id = channel_id
        game.channel_answer_mode = answer_mode
        game.discussion_chat_id = discussion_id
        if options:
            game.channel_options_json = json.dumps(options, ensure_ascii=False)
        game_engine.add_player(session, game, user)
        game.round_number = 1
        rnd = Round(
            session_id=game.id,
            round_no=1,
            chooser_user_id=user.id,
            target_user_id=user.id,
            status="open",
        )
        session.add(rnd)
        session.flush()
        sid, rid = game.id, rnd.id

    vote_markup = kb.channel_truth_dare_vote(sid, rid)
    try:
        await context.bot.send_message(
            channel_id,
            T.CHANNEL_VOTE_TRUTH_DARE,
            reply_markup=vote_markup,
        )
        await message_reply(f"رأی‌گیری جرئت/حقیقت توی کانال پست شد. (سشن #{sid})")
    except Exception:
        await message_reply(
            "نتونستم توی کانال پیام بفرستم. مطمئن شو ربات ادمین کانال هست و آیدی درسته."
        )


async def _cast_vote(query, context, session_id, round_id, value, kind):
    voter_id = query.from_user.id
    with get_session() as session:
        existing = (
            session.query(Vote)
            .filter_by(round_id=round_id, voter_telegram_id=voter_id)
            .one_or_none()
        )
        if existing:
            existing.value = value
        else:
            session.add(
                Vote(round_id=round_id, voter_telegram_id=voter_id, value=value)
            )
        session.flush()
        votes = session.query(Vote).filter_by(round_id=round_id).all()
        counts = Counter(v.value for v in votes)
        game = game_engine.get_session(session, session_id)
        rnd = session.get(Round, round_id)

        # Close TD vote after enough votes or admin presses — auto close at 3+ votes
        if kind == "td" and sum(counts.values()) >= 3 and rnd and not rnd.choice:
            winner = counts.most_common(1)[0][0]
            prompt = questions.random_prompt(winner)  # type: ignore
            rnd.choice = winner
            rnd.prompt_text = prompt
            options = []
            if game and game.channel_options_json:
                options = json.loads(game.channel_options_json)
            channel_id = game.channel_id if game else None
            if channel_id:
                kind_label = T.BTN_TRUTH if winner == "truth" else T.BTN_DARE
                await context.bot.send_message(
                    channel_id,
                    T.CHANNEL_VOTE_CLOSED.format(result=kind_label) + f"\n\n{prompt}",
                )
                if game.channel_answer_mode == "buttons" and options:
                    await context.bot.send_message(
                        channel_id,
                        "به گزینه‌ها رأی بدید:",
                        reply_markup=kb.channel_option_votes(session_id, round_id, options),
                    )
                elif game.channel_answer_mode == "comments" and game.discussion_chat_id:
                    await context.bot.send_message(
                        game.discussion_chat_id,
                        f"کامنت‌هاتون رو زیر این پیام بنویسید:\n{prompt}",
                    )
        elif kind == "opt" and sum(counts.values()) >= 3:
            # only count option votes (numeric)
            opt_counts = Counter(v.value for v in votes if v.value.isdigit())
            if opt_counts and game and game.channel_options_json:
                options = json.loads(game.channel_options_json)
                win_idx = int(opt_counts.most_common(1)[0][0])
                if 0 <= win_idx < len(options):
                    rnd.answer_text = options[win_idx]
                    rnd.status = "answered"
                    game_engine.finish_game(session, game)
                    await context.bot.send_message(
                        game.channel_id,
                        f"نتیجه رأی گزینه‌ها: {options[win_idx]}\n\n{game.summary}",
                    )

    await query.answer("رأی ثبت شد")
