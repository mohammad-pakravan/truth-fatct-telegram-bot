from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot.db import get_session
from bot.models import User
from bot.services import game_engine
from bot.services import users as user_svc
from bot.texts import fa as T


async def on_truth_dare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    # td:session:chooser:truth|dare
    parts = query.data.split(":")
    if len(parts) != 4:
        await query.answer()
        return
    _, sid, chooser_id, choice = parts
    session_id = int(sid)
    chooser_uid = int(chooser_id)

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        if user.id != chooser_uid:
            await query.answer(T.NOT_YOUR_TURN, show_alert=True)
            return
        await query.answer()
        game = game_engine.get_session(session, session_id)
        if not game or game.status != "playing":
            await query.edit_message_text("این بازی فعال نیست.")
            return
        rnd = game_engine.get_active_round(session, game)
        if not rnd or rnd.chooser_user_id != user.id:
            await query.edit_message_text(T.NOT_YOUR_TURN)
            return
        prompt = game_engine.apply_choice(session, rnd, choice)
        target = session.get(User, rnd.target_user_id)
        kind = T.BTN_TRUTH if choice == "truth" else T.BTN_DARE
        await query.edit_message_text(f"انتخاب شد: {kind}")

        if target:
            msg = T.YOUR_PROMPT.format(kind=kind, prompt=prompt)
            msg = f"{T.ROUND_INFO.format(n=game.round_number, max=game.max_rounds)}\n\n{msg}"
            try:
                await context.bot.send_message(
                    target.telegram_id,
                    msg,
                    reply_markup=kb.skip_answer(game.id),
                )
            except Exception:
                pass
            if game.chat_id and game.game_type == "group":
                try:
                    await context.bot.send_message(
                        game.chat_id,
                        f"{user_svc.public_name(target)} — {kind}:\n{prompt}",
                        reply_markup=kb.skip_answer(game.id),
                    )
                except Exception:
                    pass


async def on_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    session_id = int(query.data.split(":")[1])
    await _finish_answer(update, context, session_id, answer=None, via_callback=True)


async def answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture answers when user is the target of an open round."""
    if not update.message or not update.effective_user or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/") or text.startswith(("🎭", "📍", "🕶", "👤", "🤝", "📖", "💬", "🔗", "👥", "✏️", "📜", "🔙", "🙂")):
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        # find playing session where user is target of open round with choice set
        from bot.models import GamePlayer, GameSession, Round

        rows = (
            session.query(Round, GameSession)
            .join(GameSession, Round.session_id == GameSession.id)
            .filter(
                GameSession.status == "playing",
                Round.target_user_id == user.id,
                Round.status == "open",
                Round.choice.isnot(None),
            )
            .order_by(Round.id.desc())
            .all()
        )
        if not rows:
            return
        rnd, game = rows[0]
        # for group games, only accept in the group chat or private
        game_engine.submit_answer(session, rnd, text)
        await update.message.reply_text(T.ANSWER_RECEIVED)
        await _notify_and_advance(context, session, game, user, text)


async def _finish_answer(update, context, session_id, answer, via_callback=False):
    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        game = game_engine.get_session(session, session_id)
        if not game:
            return
        rnd = game_engine.get_active_round(session, game)
        if not rnd or rnd.target_user_id != user.id:
            if via_callback:
                await update.callback_query.edit_message_text(T.NOT_YOUR_TURN)
            return
        if not rnd.choice:
            return
        game_engine.submit_answer(session, rnd, answer)
        if via_callback:
            await update.callback_query.edit_message_text("رد شد.")
        await _notify_and_advance(context, session, game, user, answer or "—")


async def _notify_and_advance(context, session, game, user, answer_text):
    from bot.models import User

    players = game_engine.get_players(session, game)
    # notify others
    for p in players:
        if p.user_id == user.id:
            continue
        try:
            await context.bot.send_message(
                p.user.telegram_id,
                f"جواب {user_svc.public_name(user)}:\n{answer_text}",
            )
        except Exception:
            pass
    if game.chat_id and game.game_type == "group":
        try:
            await context.bot.send_message(
                game.chat_id,
                f"جواب {user_svc.public_name(user)}:\n{answer_text}",
            )
        except Exception:
            pass

    nxt = game_engine.advance_round(session, game)
    if nxt is None and game.status in ("finished", "guessing"):
        summary = game.summary or ""
        for p in players:
            try:
                await context.bot.send_message(
                    p.user.telegram_id, T.GAME_OVER.format(summary=summary)
                )
            except Exception:
                pass
        if game.status == "guessing":
            for p in players:
                try:
                    await context.bot.send_message(
                        p.user.telegram_id,
                        T.FINAL_GUESS_ASK,
                        reply_markup=kb.final_guess(game.id),
                    )
                except Exception:
                    pass
        if game.chat_id:
            try:
                await context.bot.send_message(
                    game.chat_id, T.GAME_OVER.format(summary=summary)
                )
            except Exception:
                pass
        return

    if not nxt:
        return
    chooser = session.get(User, nxt.chooser_user_id)
    target = session.get(User, nxt.target_user_id)
    chooser_name = user_svc.public_name(chooser) if chooser else "?"
    target_name = user_svc.public_name(target) if target else "?"
    # override with fake names
    for p in players:
        if p.user_id == nxt.chooser_user_id:
            chooser_name = game_engine.display_for_player(p)
        if p.user_id == nxt.target_user_id:
            target_name = game_engine.display_for_player(p)

    text = (
        f"{T.ROUND_INFO.format(n=game.round_number, max=game.max_rounds)}\n"
        + T.CHOOSE_TRUTH_OR_DARE.format(chooser=chooser_name, target=target_name)
    )
    markup = kb.truth_dare(game.id, nxt.chooser_user_id)
    if chooser:
        try:
            await context.bot.send_message(chooser.telegram_id, text, reply_markup=markup)
        except Exception:
            pass
    if game.chat_id and game.game_type == "group":
        try:
            await context.bot.send_message(game.chat_id, text, reply_markup=markup)
        except Exception:
            pass
