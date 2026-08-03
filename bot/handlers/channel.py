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
from bot.models import GameSession, Round, Vote
from bot.services import game_engine
from bot.services import users as user_svc
from bot.texts import fa as T


def _kind_label(choice: str | None) -> str:
    return T.BTN_TRUTH if choice == "truth" else T.BTN_DARE


def _active_channel_game(session, starter_id: int | None = None) -> GameSession | None:
    q = session.query(GameSession).filter(
        GameSession.game_type == "channel",
        GameSession.status.in_(["playing", "waiting"]),
    )
    if starter_id is not None:
        q = q.filter(GameSession.starter_user_id == starter_id)
    return q.order_by(GameSession.id.desc()).first()


async def channel_game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    chat = update.effective_chat
    tg = update.effective_user

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if _active_channel_game(session, user.id):
            await update.message.reply_text(T.CHANNEL_ALREADY_OPEN, reply_markup=main_menu())
            return

    if chat and chat.type == ChatType.CHANNEL:
        st.set_state(tg.id, mode="channel", channel_id=chat.id, wait="ch_mode")
        await update.message.reply_text(T.CHANNEL_MODE_ASK, reply_markup=kb.channel_answer_mode())
        return

    args = context.args or []
    if args and args[0].lstrip("-").isdigit():
        st.set_state(tg.id, mode="channel", channel_id=int(args[0]), wait="ch_mode")
        await update.message.reply_text(T.CHANNEL_MODE_ASK, reply_markup=kb.channel_answer_mode())
        return

    st.set_state(tg.id, mode="channel", wait="channel_id")
    await update.message.reply_text(T.CHANNEL_ID_ASK + T.CHANNEL_INTRO, reply_markup=main_menu())


async def channel_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    wait = st.get(tg.id).get("wait")
    text = (update.message.text or "").strip()
    if not wait:
        return

    if wait == "channel_id":
        try:
            channel_id = int(text)
        except ValueError:
            await update.message.reply_text("آیدی عددی معتبر بفرست.")
            return
        st.set_state(tg.id, channel_id=channel_id, wait="ch_mode")
        await update.message.reply_text(T.CHANNEL_MODE_ASK, reply_markup=kb.channel_answer_mode())
        return

    if wait == "ch_prompt":
        if len(text) < 3:
            await update.message.reply_text("سؤال رو کامل‌تر بنویس.")
            return
        data = st.get(tg.id)
        mode = data.get("channel_answer_mode")
        st.set_state(tg.id, channel_prompt=text[:1000])
        if mode == "buttons":
            st.set_state(tg.id, wait="ch_options")
            await update.message.reply_text(T.CHANNEL_OPTIONS_ASK)
            return
        # comments mode — start round now
        await _publish_channel_round(update, context)
        return

    if wait == "ch_options":
        options = [line.strip()[:60] for line in text.splitlines() if line.strip()]
        if len(options) < 2:
            await update.message.reply_text("حداقل ۲ گزینه لازم است.")
            return
        if len(options) > 8:
            await update.message.reply_text("حداکثر ۸ گزینه.")
            return
        st.set_state(tg.id, channel_options=options)
        await _publish_channel_round(update, context)
        return


async def channel_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    data = query.data
    tg = update.effective_user

    if data.startswith("ch_mode:"):
        await query.answer()
        mode = data.split(":")[1]
        channel_id = st.get(tg.id).get("channel_id")
        if not channel_id:
            await query.edit_message_text("اول /channel_game رو بزن و آیدی کانال رو بده.")
            return

        if mode == "comments":
            try:
                chat = await context.bot.get_chat(channel_id)
                linked = getattr(chat, "linked_chat_id", None)
            except Exception:
                linked = None
            if not linked:
                await query.edit_message_text(T.CHANNEL_NEED_DISCUSSION)
                return
            st.set_state(
                tg.id,
                channel_answer_mode="comments",
                discussion_chat_id=linked,
                wait="ch_ask",
            )
        else:
            st.set_state(tg.id, channel_answer_mode="buttons", wait="ch_ask")

        await query.edit_message_text(T.CHANNEL_ASK_TD, reply_markup=kb.channel_owner_truth_dare())
        return

    if data.startswith("ch_ask:"):
        await query.answer()
        choice = data.split(":")[1]
        if choice not in ("truth", "dare"):
            return
        st.set_state(tg.id, channel_choice=choice, wait="ch_prompt")
        await query.edit_message_text(T.CHANNEL_ASK_PROMPT)
        return

    if data.startswith("ch_opt:"):
        _, sid, rid, idx = data.split(":")
        await _cast_option_vote(query, int(sid), int(rid), idx)
        return

    if data.startswith("ch_close:"):
        _, sid, rid = data.split(":")
        await _close_round(query, context, int(sid), int(rid))
        return

    if data.startswith("ch_next:"):
        await query.answer()
        sid = int(data.split(":")[1])
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            game = game_engine.get_session(session, sid)
            if not game or game.starter_user_id != user.id:
                await query.edit_message_text(T.CHANNEL_NOT_OWNER)
                return
            if game.status == "finished":
                game.status = "playing"
            channel_id = game.channel_id
            answer_mode = game.channel_answer_mode
            discussion_id = game.discussion_chat_id

        st.set_state(
            tg.id,
            mode="channel",
            channel_id=channel_id,
            channel_answer_mode=answer_mode,
            discussion_chat_id=discussion_id,
            channel_session_id=sid,
            wait="ch_ask",
        )
        await query.edit_message_text(T.CHANNEL_ASK_TD, reply_markup=kb.channel_owner_truth_dare())
        return

    if data.startswith("ch_end:"):
        await query.answer()
        sid = int(data.split(":")[1])
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            game = game_engine.get_session(session, sid)
            if not game or game.starter_user_id != user.id:
                await query.edit_message_text(T.CHANNEL_NOT_OWNER)
                return
            game_engine.finish_game(session, game)
        st.clear(tg.id)
        await query.edit_message_text("بازی کانال تموم شد.")
        return


async def discussion_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Collect Instagram-style comments from the linked discussion group."""
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    text = (update.message.text or "").strip()
    if not text:
        return

    chat_id = update.effective_chat.id
    reply = update.message.reply_to_message
    voter_id = update.effective_user.id

    with get_session() as session:
        game = (
            session.query(GameSession)
            .filter(
                GameSession.game_type == "channel",
                GameSession.status == "playing",
                GameSession.channel_answer_mode == "comments",
                GameSession.discussion_chat_id == chat_id,
            )
            .order_by(GameSession.id.desc())
            .first()
        )
        if not game:
            return

        # Prefer replies to the bot prompt; also accept any text if no prompt id yet
        if game.channel_prompt_message_id:
            if not reply or reply.message_id != game.channel_prompt_message_id:
                return

        rnd = (
            session.query(Round)
            .filter_by(session_id=game.id, status="open")
            .order_by(Round.id.desc())
            .first()
        )
        if not rnd:
            return

        existing = (
            session.query(Vote)
            .filter_by(round_id=rnd.id, voter_telegram_id=voter_id)
            .one_or_none()
        )
        clipped = text[:500]
        if existing:
            existing.value = clipped
        else:
            session.add(Vote(round_id=rnd.id, voter_telegram_id=voter_id, value=clipped))

    try:
        await update.message.reply_text(T.CHANNEL_COMMENT_RECORDED)
    except Exception:
        pass


async def _publish_channel_round(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    data = st.get(tg.id)
    channel_id = data.get("channel_id")
    answer_mode = data.get("channel_answer_mode")
    choice = data.get("channel_choice")
    prompt = data.get("channel_prompt")
    options = data.get("channel_options") or []
    discussion_id = data.get("discussion_chat_id")
    reuse_sid = data.get("channel_session_id")

    if not channel_id or not answer_mode or not choice or not prompt:
        await update.message.reply_text(T.ERROR_GENERIC)
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = None
        if reuse_sid:
            game = game_engine.get_session(session, int(reuse_sid))
            if game and game.starter_user_id != user.id:
                game = None

        if not game:
            game = game_engine.create_session(
                session, "channel", starter=user, chat_id=channel_id, max_rounds=50
            )
            game_engine.add_player(session, game, user)

        game.status = "playing"
        game.channel_id = channel_id
        game.channel_answer_mode = answer_mode
        game.discussion_chat_id = discussion_id
        game.channel_options_json = (
            json.dumps(options, ensure_ascii=False) if options else None
        )
        game.channel_prompt_message_id = None
        game.round_number = (game.round_number or 0) + 1

        rnd = Round(
            session_id=game.id,
            round_no=game.round_number,
            chooser_user_id=user.id,
            target_user_id=user.id,
            choice=choice,
            prompt_text=prompt,
            status="open",
        )
        session.add(rnd)
        session.flush()
        sid, rid = game.id, rnd.id
        kind = _kind_label(choice)

    st.clear(tg.id)

    try:
        if answer_mode == "buttons":
            post = T.CHANNEL_POST_BUTTONS.format(kind=kind, prompt=prompt)
            msg = await context.bot.send_message(
                channel_id,
                post,
                reply_markup=kb.channel_option_votes(sid, rid, options),
            )
        else:
            post = T.CHANNEL_POST_COMMENTS.format(kind=kind, prompt=prompt)
            await context.bot.send_message(channel_id, post)
            disc = await context.bot.send_message(
                discussion_id,
                T.CHANNEL_DISCUSSION_PROMPT.format(kind=kind, prompt=prompt),
                reply_markup=kb.channel_close_only(sid, rid),
            )
            with get_session() as session:
                game = game_engine.get_session(session, sid)
                if game:
                    game.channel_prompt_message_id = disc.message_id
            # Also give owner a close button in DM
            await update.message.reply_text(
                T.CHANNEL_POSTED.format(sid=sid),
                reply_markup=kb.channel_close_only(sid, rid),
            )
            return

        await update.message.reply_text(
            T.CHANNEL_POSTED.format(sid=sid),
            reply_markup=kb.channel_close_only(sid, rid),
        )
        _ = msg
    except Exception:
        await update.message.reply_text(T.CHANNEL_POST_FAIL, reply_markup=main_menu())


async def _cast_option_vote(query, session_id: int, round_id: int, idx: str) -> None:
    voter_id = query.from_user.id
    with get_session() as session:
        rnd = session.get(Round, round_id)
        game = game_engine.get_session(session, session_id)
        if not rnd or not game or rnd.status != "open" or game.status != "playing":
            await query.answer("رأی‌گیری بسته شده.", show_alert=True)
            return
        if game.channel_answer_mode != "buttons":
            await query.answer("این دور رأی دکمه‌ای نیست.", show_alert=True)
            return
        options = json.loads(game.channel_options_json or "[]")
        try:
            i = int(idx)
        except ValueError:
            await query.answer("گزینه نامعتبر.", show_alert=True)
            return
        if i < 0 or i >= len(options):
            await query.answer("گزینه نامعتبر.", show_alert=True)
            return

        existing = (
            session.query(Vote)
            .filter_by(round_id=round_id, voter_telegram_id=voter_id)
            .one_or_none()
        )
        if existing:
            existing.value = str(i)
        else:
            session.add(Vote(round_id=round_id, voter_telegram_id=voter_id, value=str(i)))

    await query.answer(T.CHANNEL_VOTE_RECORDED)


async def _close_round(query, context, session_id: int, round_id: int) -> None:
    tg = query.from_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, session_id)
        rnd = session.get(Round, round_id)
        if not game or not rnd:
            await query.answer("پیدا نشد.", show_alert=True)
            return
        if game.starter_user_id != user.id:
            await query.answer(T.CHANNEL_NOT_OWNER, show_alert=True)
            return
        if rnd.status != "open":
            await query.answer("این دور قبلاً بسته شده.", show_alert=True)
            return

        votes = session.query(Vote).filter_by(round_id=round_id).all()
        if not votes:
            await query.answer(T.CHANNEL_NO_VOTES, show_alert=True)
            return

        kind = _kind_label(rnd.choice)
        prompt = rnd.prompt_text or ""
        channel_id = game.channel_id
        mode = game.channel_answer_mode

        if mode == "buttons":
            options = json.loads(game.channel_options_json or "[]")
            counts = Counter(v.value for v in votes if v.value.isdigit())
            if not counts:
                await query.answer(T.CHANNEL_NO_VOTES, show_alert=True)
                return
            win_idx = int(counts.most_common(1)[0][0])
            winner = options[win_idx] if 0 <= win_idx < len(options) else "?"
            tally_parts = []
            for i, opt in enumerate(options):
                tally_parts.append(f"{opt}: {counts.get(str(i), 0)}")
            tally = " | ".join(tally_parts)
            rnd.answer_text = winner
            rnd.status = "answered"
            result = T.CHANNEL_RESULT_OPTION.format(
                kind=kind, prompt=prompt, winner=winner, tally=tally
            )
        else:
            lines = []
            for i, v in enumerate(votes, start=1):
                lines.append(f"{i}. {v.value}")
            comments = "\n".join(lines)
            rnd.answer_text = comments[:2000]
            rnd.status = "answered"
            result = T.CHANNEL_RESULT_COMMENTS.format(
                kind=kind, prompt=prompt, count=len(votes), comments=comments
            )

        sid = game.id

    await query.answer("نتیجه اعلام شد")
    try:
        if channel_id:
            await context.bot.send_message(channel_id, result)
    except Exception:
        pass

    try:
        await query.edit_message_text(
            result + "\n\nدور بعد یا پایان؟",
            reply_markup=kb.channel_after_round(sid),
        )
    except Exception:
        await context.bot.send_message(
            tg.id,
            result + "\n\nدور بعد یا پایان؟",
            reply_markup=kb.channel_after_round(sid),
        )
