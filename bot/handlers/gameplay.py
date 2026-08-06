from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.models import User
from bot.services import game_engine
from bot.services import users as user_svc
from bot.services.glass_msg import clear_td_glass, show_td_glass, upsert_action, upsert_hub
from bot.texts import fa as T

logger = logging.getLogger(__name__)


async def send_in_game_menu(context, telegram_id: int, *, is_chooser: bool) -> None:
    """No-op: never send standalone menu-hint / wait messages."""
    return


async def _show_opponent_profile(bot, chat_id: int, session, user, game) -> None:
    players = game_engine.get_players(session, game)
    other_player = next((p for p in players if p.user_id != user.id), None)
    if not other_player:
        await bot.send_message(chat_id, "پروفایل حریف پیدا نشد.")
        return
    if game.game_type == "anonymous" or other_player.identity_mode == "anonymous":
        await bot.send_message(chat_id, T.ANON_OPPONENT)
        return
    if game.game_type == "fake_identity":
        await bot.send_message(
            chat_id, "پروفایل حریف:\n" + game_engine.presented_profile(other_player)
        )
        return
    other = other_player.user
    profile = user_svc.format_profile(other, viewer_settings=user)
    caption = f"پروفایل حریف:\n{profile}"
    if user_svc.may_show_photo(other, for_opponent=True):
        try:
            if other.profile_photo_file_id:
                await bot.send_photo(
                    chat_id, photo=other.profile_photo_file_id, caption=caption[:1024]
                )
                return
        except Exception:
            pass
    await bot.send_message(chat_id, caption)


async def _end_active_game(context, session, user, game) -> None:
    players = game_engine.get_players(session, game)
    game_engine.finish_game(session, game)
    summary = game.summary or ""
    status = game.status
    game_id = game.id
    for p in players:
        try:
            await clear_td_glass(context.bot, p.user.telegram_id)
            await context.bot.send_message(
                p.user.telegram_id,
                f"{T.GAME_ENDED_BY_USER}\n{summary}",
                reply_markup=kb.main_menu() if status != "guessing" else None,
            )
        except Exception:
            pass
    if status == "guessing":
        from bot.handlers import fake as fake_handler

        await fake_handler.prompt_final_guess(context, game_id, players)


async def _ask_chooser_for_prompt(
    context,
    *,
    chooser_tg: int,
    kind: str,
    game_id: int,
    choice: str,
    glass_message=None,
) -> None:
    """Turn the truth/dare action message into the 'write your question' prompt."""
    text = T.ASK_CUSTOM_PROMPT.format(kind=kind)
    action_id = None
    if glass_message is not None:
        try:
            await glass_message.edit_text(text)
            action_id = glass_message.message_id
        except Exception:
            logger.debug("action→ask edit failed", exc_info=True)
            action_id = glass_message.message_id
    if action_id is None:
        action_id = st.get(chooser_tg).get("game_glass_message_id")
        action_id = await upsert_action(
            context.bot,
            chooser_tg,
            text,
            message_id=action_id,
        )
    st.set_state(
        chooser_tg,
        wait="custom_prompt",
        custom_prompt_game_id=game_id,
        custom_prompt_choice=choice,
        game_glass_message_id=action_id,
    )


async def _deliver_prompt_to_target(
    context,
    *,
    target_tg: int,
    kind: str,
    prompt: str,
    round_number: int,
    max_rounds: int,
    game_id: int,
    game_type: str | None = None,
    chat_id: int | None = None,
    target_name: str | None = None,
) -> None:
    msg = T.YOUR_PROMPT.format(kind=kind, prompt=prompt)
    msg = f"{T.ROUND_INFO.format(n=round_number, max=max_rounds)}\n\n{msg}"
    mid = await upsert_hub(
        context.bot,
        target_tg,
        msg,
        message_id=st.get(target_tg).get("game_hub_message_id"),
        reply_kb=kb.in_game_menu(awaiting_answer=True),
        replace_keyboard=True,
    )
    st.set_state(target_tg, game_hub_message_id=mid)
    if chat_id and game_type == "group":
        label = target_name or "بازیکن"
        try:
            await context.bot.send_message(
                chat_id,
                f"{label} — {kind}:\n{prompt}",
                reply_markup=kb.skip_answer(game_id),
            )
        except Exception:
            logger.exception("group prompt notify failed chat_id=%s", chat_id)


async def resume_active_game_keyboard(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    *,
    reply_to=None,
) -> bool:
    """If user has an active game, show in-game keyboard (+ glass truth/dare if needed)."""
    with get_session() as session:
        user = user_svc.get_or_create_user(session, telegram_id)
        game = game_engine.active_session_for_user(session, user)
        if not game:
            return False
        rnd = game_engine.get_active_round(session, game)
        is_chooser = bool(rnd and rnd.chooser_user_id == user.id and not rnd.choice)
        awaiting = bool(
            rnd
            and rnd.target_user_id == user.id
            and rnd.choice
            and rnd.prompt_text
            and rnd.status == "open"
        )
        game_id = game.id
        chooser_uid = rnd.chooser_user_id if rnd else None
        reply = kb.in_game_menu(is_chooser=is_chooser, awaiting_answer=awaiting)

    hub_id = await upsert_hub(
        context.bot,
        telegram_id,
        T.ALREADY_IN_GAME,
        message_id=st.get(telegram_id).get("game_hub_message_id"),
        reply_kb=reply,
        replace_keyboard=True,
    )
    glass_id = None
    if is_chooser and chooser_uid:
        glass_id = await show_td_glass(
            context.bot,
            telegram_id,
            session_id=game_id,
            chooser_id=chooser_uid,
            turn_text=T.CHOOSE_TRUTH_OR_DARE.format(chooser="تو", target="حریف"),
            glass_message_id=st.get(telegram_id).get("game_glass_message_id"),
        )
    st.set_state(
        telegram_id, game_hub_message_id=hub_id, game_glass_message_id=glass_id
    )
    return True


async def custom_prompt_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Chooser submits the truth/dare question for the opponent."""
    if not update.message or not update.effective_user or not update.message.text:
        return False
    tg = update.effective_user
    state = st.get(tg.id)
    if state.get("wait") != "custom_prompt":
        return False

    text = update.message.text.strip()
    if text in {
        T.BTN_GAME_PROFILE,
        T.BTN_GAME_END,
        T.BTN_TRUTH,
        T.BTN_DARE,
        T.BTN_GAME_WAIT,
        T.BTN_SKIP,
    }:
        return False
    if len(text) < 2:
        await update.message.reply_text("سؤال رو کامل‌تر بنویس 🙂")
        return True

    game_id = state.get("custom_prompt_game_id")
    choice = state.get("custom_prompt_choice")
    if not game_id or choice not in ("truth", "dare"):
        st.set_state(tg.id, wait=None, custom_prompt_game_id=None, custom_prompt_choice=None)
        return True

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, int(game_id))
        if not game or game.status != "playing":
            st.set_state(tg.id, wait=None, custom_prompt_game_id=None, custom_prompt_choice=None)
            await update.message.reply_text("این بازی دیگه فعال نیست.", reply_markup=kb.main_menu())
            return True
        rnd = game_engine.get_active_round(session, game)
        if not rnd or rnd.chooser_user_id != user.id or rnd.choice != choice:
            st.set_state(tg.id, wait=None, custom_prompt_game_id=None, custom_prompt_choice=None)
            await update.message.reply_text(T.NOT_YOUR_TURN, reply_markup=kb.in_game_menu())
            return True
        if rnd.prompt_text:
            st.set_state(tg.id, wait=None, custom_prompt_game_id=None, custom_prompt_choice=None)
            return True

        prompt = game_engine.apply_choice(session, rnd, choice, prompt=text)
        target = session.get(User, rnd.target_user_id)
        kind = T.BTN_TRUTH if choice == "truth" else T.BTN_DARE
        target_tg = target.telegram_id if target else None
        target_name = user_svc.public_name(target) if target else None
        chat_id = game.chat_id
        round_number = game.round_number
        max_rounds = game.max_rounds
        snap_game_id = game.id
        game_type = game.game_type

    st.set_state(tg.id, wait=None, custom_prompt_game_id=None, custom_prompt_choice=None)
    action_id = await upsert_action(
        context.bot,
        tg.id,
        T.PROMPT_SENT,
        message_id=st.get(tg.id).get("game_glass_message_id"),
    )
    st.set_state(tg.id, game_glass_message_id=action_id)
    if not target_tg:
        logger.error("custom prompt: no target_tg for game_id=%s", snap_game_id)
        return True
    try:
        await _deliver_prompt_to_target(
            context,
            target_tg=target_tg,
            kind=kind,
            prompt=prompt,
            round_number=round_number,
            max_rounds=max_rounds,
            game_id=snap_game_id,
            game_type=game_type,
            chat_id=chat_id,
            target_name=target_name,
        )
    except Exception:
        logger.exception(
            "Failed to deliver prompt to tg=%s game_id=%s", target_tg, snap_game_id
        )
        await update.message.reply_text(
            "سؤال ثبت شد ولی ارسال به حریف خطا داد. دوباره امتحان کن."
        )
    return True


async def game_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user or not update.message.text:
        return False
    text = update.message.text.strip()
    if text not in {
        T.BTN_GAME_PROFILE,
        T.BTN_GAME_END,
        T.BTN_TRUTH,
        T.BTN_DARE,
        T.BTN_GAME_WAIT,
        T.BTN_SKIP,
    }:
        return False

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        game = game_engine.active_session_for_user(session, user)
        if not game:
            await update.message.reply_text(T.NO_ACTIVE_GAME, reply_markup=kb.main_menu())
            return True

        rnd = game_engine.get_active_round(session, game)

        if text == T.BTN_GAME_PROFILE:
            await _show_opponent_profile(context.bot, update.effective_user.id, session, user, game)
            return True

        if text == T.BTN_GAME_END:
            await _end_active_game(context, session, user, game)
            return True

        if text == T.BTN_GAME_WAIT:
            return True

        if text == T.BTN_SKIP:
            if not rnd or rnd.target_user_id != user.id or not rnd.choice or not rnd.prompt_text:
                await update.message.reply_text(T.NOT_YOUR_TURN)
                return True
            game_engine.submit_answer(session, rnd, None)
            await update.message.reply_text("رد شد.", reply_markup=kb.in_game_menu(is_chooser=False))
            await _notify_and_advance(context, session, game, user, "رد شد")
            return True

        if not rnd or rnd.chooser_user_id != user.id:
            await update.message.reply_text(T.NOT_YOUR_TURN)
            return True

        choice = "truth" if text == T.BTN_TRUTH else "dare"
        game_engine.set_pending_choice(session, rnd, choice)
        kind = T.BTN_TRUTH if choice == "truth" else T.BTN_DARE
        game_id = game.id

    await _ask_chooser_for_prompt(
        context,
        chooser_tg=update.effective_user.id,
        kind=kind,
        game_id=game_id,
        choice=choice,
    )
    return True


async def on_game_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Glass profile / end-game actions: gact:profile|end:<session_id>."""
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, action, sid = parts
    session_id = int(sid)

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        game = game_engine.get_session(session, session_id)
        if not game or game.status not in ("playing", "guessing"):
            await query.answer("این بازی فعال نیست.", show_alert=True)
            return
        players = game_engine.get_players(session, game)
        if user.id not in {p.user_id for p in players}:
            await query.answer(T.NOT_YOUR_TURN, show_alert=True)
            return

        if action == "profile":
            await query.answer()
            await _show_opponent_profile(
                context.bot, update.effective_user.id, session, user, game
            )
            return

        if action == "end":
            await query.answer()
            await _end_active_game(context, session, user, game)
            return

    await query.answer()


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
        game_engine.set_pending_choice(session, rnd, choice)
        kind = T.BTN_TRUTH if choice == "truth" else T.BTN_DARE
        chooser_tg = update.effective_user.id
        game_id = game.id

    await _ask_chooser_for_prompt(
        context,
        chooser_tg=chooser_tg,
        kind=kind,
        game_id=game_id,
        choice=choice,
        glass_message=query.message,
    )


async def on_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    session_id = int(query.data.split(":")[1])
    await _finish_answer(update, context, session_id, answer=None, via_callback=True)


async def answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture answers when user is the target of an open round with a prompt."""
    if not update.message or not update.effective_user or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/") or text.startswith(
        ("🎭", "📍", "🕶", "👤", "🤝", "📖", "💬", "🔗", "👥", "✏️", "📜", "🔙", "🙂", "⛔", "⏳", "❌", "👁", "⏭")
    ):
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        from bot.models import GameSession, Round

        rows = (
            session.query(Round, GameSession)
            .join(GameSession, Round.session_id == GameSession.id)
            .filter(
                GameSession.status == "playing",
                Round.target_user_id == user.id,
                Round.status == "open",
                Round.choice.isnot(None),
                Round.prompt_text.isnot(None),
            )
            .order_by(Round.id.desc())
            .all()
        )
        if not rows:
            return
        rnd, game = rows[0]
        game_engine.submit_answer(session, rnd, text)
        await update.message.reply_text(
            T.ANSWER_RECEIVED,
            reply_markup=kb.in_game_menu(is_chooser=False),
        )
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
        if not rnd.choice or not rnd.prompt_text:
            return
        game_engine.submit_answer(session, rnd, answer)
        if via_callback:
            await update.callback_query.edit_message_text("رد شد.")
        await _notify_and_advance(context, session, game, user, answer or "رد شد")


async def _notify_and_advance(context, session, game, user, answer_text):
    players = game_engine.get_players(session, game)
    anonymous = game.game_type == "anonymous"
    body = (answer_text or "").strip() or "—"

    nxt = game_engine.advance_round(session, game)

    for p in players:
        if p.user_id == user.id:
            continue
        try:
            await context.bot.send_message(
                p.user.telegram_id,
                body,
                reply_markup=kb.in_game_menu(is_chooser=False),
            )
        except Exception:
            pass
    if game.chat_id and game.game_type == "group":
        try:
            await context.bot.send_message(game.chat_id, body)
        except Exception:
            pass

    if nxt is None and game.status in ("finished", "guessing"):
        summary = game.summary or ""
        for p in players:
            try:
                await context.bot.send_message(
                    p.user.telegram_id,
                    T.GAME_OVER.format(summary=summary),
                    reply_markup=kb.main_menu(),
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
    if anonymous:
        chooser_name = target_name = "ناشناس"
    else:
        chooser_name = user_svc.public_name(chooser) if chooser else "?"
        target_name = user_svc.public_name(target) if target else "?"
        for p in players:
            if p.user_id == nxt.chooser_user_id:
                chooser_name = game_engine.display_for_player(p)
            if p.user_id == nxt.target_user_id:
                target_name = game_engine.display_for_player(p)

    if game.game_type == "group":
        choose = T.GROUP_TURN.format(chooser=chooser_name, target=target_name)
    else:
        choose = T.CHOOSE_TRUTH_OR_DARE.format(chooser=chooser_name, target=target_name)
    text = f"{T.ROUND_INFO.format(n=game.round_number, max=game.max_rounds)}\n{choose}"

    if chooser:
        try:
            # Keep hub as-is when possible; refresh the action strip with new turn
            glass_id = await show_td_glass(
                context.bot,
                chooser.telegram_id,
                session_id=game.id,
                chooser_id=nxt.chooser_user_id,
                turn_text=text,
                glass_message_id=st.get(chooser.telegram_id).get("game_glass_message_id"),
            )
            hub_id = st.get(chooser.telegram_id).get("game_hub_message_id")
            if not hub_id:
                hub_id = await upsert_hub(
                    context.bot,
                    chooser.telegram_id,
                    T.MATCH_HUB.format(match_body=T.ROUND_INFO.format(
                        n=game.round_number, max=game.max_rounds
                    )),
                    reply_kb=kb.in_game_menu(is_chooser=True),
                    replace_keyboard=True,
                )
            st.set_state(
                chooser.telegram_id,
                game_hub_message_id=hub_id,
                game_glass_message_id=glass_id,
            )
        except Exception:
            pass
    if target and (not chooser or target.id != chooser.id):
        try:
            mid = await upsert_hub(
                context.bot,
                target.telegram_id,
                text + "\nمنتظر انتخاب طرف مقابل باش…",
                message_id=st.get(target.telegram_id).get("game_hub_message_id"),
                reply_kb=kb.in_game_menu(is_chooser=False),
                replace_keyboard=bool(
                    not st.get(target.telegram_id).get("game_hub_message_id")
                ),
            )
            await clear_td_glass(context.bot, target.telegram_id)
            st.set_state(
                target.telegram_id, game_hub_message_id=mid, game_glass_message_id=None
            )
        except Exception:
            pass
    if game.chat_id and game.game_type == "group":
        try:
            await context.bot.send_message(
                game.chat_id,
                text,
                reply_markup=kb.truth_dare(game.id, nxt.chooser_user_id),
            )
        except Exception:
            pass
