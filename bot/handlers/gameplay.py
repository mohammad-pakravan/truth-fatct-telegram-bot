from __future__ import annotations

import logging
from datetime import datetime

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

_MEDIA_TYPES = frozenset({"photo", "voice", "video", "video_note"})
STALE_ASKER_SECONDS = 30 * 60


def _waiting_for_asker_text(chooser: User | None) -> str:
    """Label shown to answerer while waiting for opponent to send a question."""
    from bot.services.presence import is_online

    if not chooser or not chooser.last_active_at:
        return T.WAITING_FOR_QUESTION_STALE
    secs = int((datetime.utcnow() - chooser.last_active_at).total_seconds())
    if secs > STALE_ASKER_SECONDS:
        return T.WAITING_FOR_QUESTION_STALE
    if not is_online(chooser.last_active_at):
        return T.WAITING_FOR_QUESTION_OFFLINE
    return T.WAITING_FOR_QUESTION


async def _delete_game_messages(bot, chat_id: int, *message_ids: int | None) -> None:
    for mid in message_ids:
        if not mid:
            continue
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            logger.debug("delete msg failed chat=%s mid=%s", chat_id, mid, exc_info=True)


async def _ack_answerer(bot, answerer_tg: int, *, skipped: bool = False) -> None:
    """Remove question UI and send a fresh ack below the user's answer."""
    state = st.get(answerer_tg)
    await _delete_game_messages(
        bot,
        answerer_tg,
        state.get("game_hub_message_id"),
        state.get("game_glass_message_id"),
    )
    text = T.ANSWER_SKIPPED if skipped else T.ANSWER_RECEIVED
    sent = await bot.send_message(
        answerer_tg,
        text,
        reply_markup=kb.in_game_menu(is_chooser=False, awaiting_answer=False),
    )
    st.set_state(answerer_tg, game_glass_message_id=None)
    # Keep ack as its own bubble — next round sends a fresh message below.
    _ = sent


def _extract_media(message) -> tuple[str | None, str | None, str | None]:
    """Return (media_type, file_id, caption_or_none) from a Telegram message."""
    if not message:
        return None, None, None
    caption = (message.caption or "").strip() or None
    if message.photo:
        return "photo", message.photo[-1].file_id, caption
    if message.voice:
        return "voice", message.voice.file_id, caption
    if message.video:
        return "video", message.video.file_id, caption
    if message.video_note:
        return "video_note", message.video_note.file_id, caption
    return None, None, None


def _media_label(media_type: str | None) -> str:
    return (T.MEDIA_ANSWER_LABEL or {}).get(media_type or "", "مدیا")


async def _send_media(
    bot,
    chat_id: int,
    *,
    media_type: str | None,
    file_id: str | None,
    caption: str | None = None,
    reply_markup=None,
    protect_content: bool = True,
) -> None:
    """Send photo / voice / video / video_note with optional content protection."""
    kwargs = {"protect_content": protect_content}
    if media_type == "photo" and file_id:
        await bot.send_photo(
            chat_id,
            photo=file_id,
            caption=caption or None,
            reply_markup=reply_markup,
            **kwargs,
        )
        return
    if media_type == "voice" and file_id:
        await bot.send_voice(
            chat_id,
            voice=file_id,
            caption=caption or None,
            reply_markup=reply_markup,
            **kwargs,
        )
        return
    if media_type == "video" and file_id:
        await bot.send_video(
            chat_id,
            video=file_id,
            caption=caption or None,
            reply_markup=reply_markup,
            **kwargs,
        )
        return
    if media_type == "video_note" and file_id:
        await bot.send_video_note(chat_id, video_note=file_id, protect_content=protect_content)
        if caption or reply_markup:
            await bot.send_message(
                chat_id,
                caption or "🎬",
                reply_markup=reply_markup,
                protect_content=protect_content,
            )
        return
    await bot.send_message(
        chat_id,
        (caption or "—").strip() or "—",
        reply_markup=reply_markup,
        protect_content=protect_content,
    )


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
            chat_id,
            T.OPPONENT_HEADER + "\n" + T.RULE + "\n" + game_engine.presented_profile(other_player),
        )
        return
    other = other_player.user
    profile = user_svc.format_profile(other, viewer_settings=user)
    caption = T.OPPONENT_HEADER + "\n" + T.RULE + "\n" + profile
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
    # Snapshot opponent ids before session work finishes
    for p in players:
        try:
            peer_tg = p.user.telegram_id
            st.set_state(peer_tg, private_chat=False, private_chat_peer=None)
            await clear_td_glass(context.bot, peer_tg)
            other = next((x for x in players if x.user_id != p.user_id), None)
            other_uid = other.user_id if other else None
            await context.bot.send_message(
                peer_tg,
                f"{T.GAME_ENDED_BY_USER}\n{summary}",
                reply_markup=kb.main_menu(peer_tg) if status != "guessing" else None,
            )
            if other_uid and status != "guessing":
                await _send_post_game_actions(context.bot, peer_tg, game_id, other_uid)
        except Exception:
            pass
    if status == "guessing":
        from bot.handlers import fake as fake_handler

        await fake_handler.prompt_final_guess(context, game_id, players)
        # Still offer social actions on the real accounts
        for p in players:
            other = next((x for x in players if x.user_id != p.user_id), None)
            if not other or not p.user:
                continue
            try:
                await _send_post_game_actions(
                    context.bot, p.user.telegram_id, game_id, other.user_id
                )
            except Exception:
                pass


async def _send_post_game_actions(bot, chat_id: int, game_id: int, target_user_id: int) -> None:
    await bot.send_message(
        chat_id,
        T.POST_GAME_ACTIONS,
        reply_markup=kb.post_game_actions_keyboard(game_id, target_user_id),
    )


def _other_player_tg(session, game, user) -> int | None:
    players = game_engine.get_players(session, game)
    other = next((p for p in players if p.user_id != user.id), None)
    if not other or not other.user:
        return None
    return other.user.telegram_id


async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user:
        return False
    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        game = game_engine.active_session_for_user(session, user)
        if not game:
            await update.message.reply_text(T.REPORT_NEED_GAME)
            return True
        other = next(
            (p for p in game_engine.get_players(session, game) if p.user_id != user.id),
            None,
        )
        if not other:
            await update.message.reply_text(T.REPORT_NO_OPPONENT)
            return True
        game_id = game.id
    await update.message.reply_text(
        T.REPORT_PICK_REASON,
        reply_markup=kb.report_reason_keyboard(game_id),
    )
    return True


async def on_user_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ureport:<reason>:<game_id>"""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, reason, sid = parts
    game_id = int(sid)
    tg = update.effective_user

    if reason == "other":
        st.set_state(tg.id, waiting="report_other", report_game_id=game_id)
        await query.answer()
        await query.edit_message_text(T.REPORT_ASK_OTHER)
        return

    await query.answer()
    ok_msg = await _submit_report(context, tg, game_id, reason_code=reason, reason_text=None)
    try:
        await query.edit_message_text(ok_msg)
    except Exception:
        await context.bot.send_message(tg.id, ok_msg)


async def on_post_game_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """pgact:like|contact|report:game_id:target_user_id — always targets real User."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    parts = query.data.split(":")
    if len(parts) != 4:
        await query.answer()
        return
    _, action, sid, tid = parts
    game_id = int(sid)
    target_uid = int(tid)
    tg = update.effective_user

    from bot.services import social as social_svc

    with get_session() as session:
        me = user_svc.get_or_create_user(session, tg.id, tg.username)
        if not social_svc.players_were_in_game(session, game_id, me.id, target_uid):
            await query.answer(T.PGACT_FORBIDDEN, show_alert=True)
            return
        target = session.get(User, target_uid)
        if not target:
            await query.answer(T.PGACT_FORBIDDEN, show_alert=True)
            return

        if action == "like":
            status, n = social_svc.like_user(session, me, target, session_id=game_id)
            msg = {
                "liked": T.LIKE_OK.format(n=n),
                "unliked": T.LIKE_REMOVED.format(n=n),
                "self": T.LIKE_SELF,
            }.get(status, T.ERROR_GENERIC)
            await query.answer(msg, show_alert=True)
            return

        if action == "contact":
            status = social_svc.add_contact(session, me, target, session_id=game_id)
            msg = {
                "added": T.CONTACT_ADDED,
                "exists": T.CONTACT_EXISTS,
                "self": T.CONTACT_SELF,
            }.get(status, T.ERROR_GENERIC)
            await query.answer(msg, show_alert=True)
            if status == "added":
                from bot.handlers.user_profile import maybe_notify_follow

                await maybe_notify_follow(context, me, target)
            return

        if action == "report":
            await query.answer()
            try:
                await query.edit_message_text(
                    T.REPORT_PICK_REASON,
                    reply_markup=kb.report_reason_keyboard(game_id),
                )
            except Exception:
                await context.bot.send_message(
                    tg.id,
                    T.REPORT_PICK_REASON,
                    reply_markup=kb.report_reason_keyboard(game_id),
                )
            return

    await query.answer()


async def report_other_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user or not update.message.text:
        return False
    tg = update.effective_user
    state = st.get(tg.id)
    if state.get("waiting") != "report_other":
        return False
    text = update.message.text.strip()
    if text in (T.BTN_CANCEL, T.BTN_BACK):
        st.set_state(tg.id, waiting=None, report_game_id=None)
        await update.message.reply_text(T.ADMIN_CANCELLED)
        return True
    game_id = state.get("report_game_id")
    st.set_state(tg.id, waiting=None, report_game_id=None)
    if not game_id:
        await update.message.reply_text(T.REPORT_NEED_GAME)
        return True
    msg = await _submit_report(
        context, tg, int(game_id), reason_code="other", reason_text=text
    )
    await update.message.reply_text(msg)
    return True


async def _submit_report(context, tg, game_id: int, *, reason_code: str, reason_text: str | None) -> str:
    from bot.config import ADMIN_IDS
    from bot.services import moderation as mod_svc

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username)
        game = game_engine.get_session(session, game_id)
        if not game:
            return T.REPORT_NEED_GAME
        players = game_engine.get_players(session, game)
        if user.id not in {p.user_id for p in players}:
            return T.REPORT_NEED_GAME
        other = next((p for p in players if p.user_id != user.id), None)
        if not other or not other.user:
            return T.REPORT_NO_OPPONENT
        row, status = mod_svc.create_report(
            session,
            reporter=user,
            reported=other.user,
            reason_code=reason_code,
            reason_text=reason_text,
            session_id=game_id,
        )
        if status == "duplicate":
            return T.REPORT_DUP
        if status == "self":
            return T.REPORT_SELF
        reported_tg = other.user.telegram_id
        report_id = row.id if row else 0
        reason_label = mod_svc.reason_label(reason_code)

    # Notify env admins (best-effort)
    note = T.ADMIN_MOD_NOTIFY_NEW.format(
        id=report_id, reported_tg=reported_tg, reason=reason_label
    )
    for admin_tid in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_tid, note)
        except Exception:
            pass
    return T.REPORT_OK


async def open_private_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user:
        return False
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username)
        game = game_engine.active_session_for_user(session, user)
        if not game:
            await update.message.reply_text(T.PRIVATE_CHAT_NEED_GAME, reply_markup=kb.main_menu(tg.id))
            return True
        peer_tg = _other_player_tg(session, game, user)
        if not peer_tg:
            await update.message.reply_text("حریف پیدا نشد.")
            return True
        game_id = game.id

    st.set_state(tg.id, private_chat=True, private_chat_peer=peer_tg, private_chat_game_id=game_id)
    await update.message.reply_text(T.PRIVATE_CHAT_ON, reply_markup=kb.private_chat_menu())

    peer_state = st.get(peer_tg)
    if not peer_state.get("private_chat"):
        try:
            await context.bot.send_message(
                peer_tg,
                T.PRIVATE_CHAT_PEER_ON,
                reply_markup=kb.in_game_menu(),
            )
        except Exception:
            pass
    return True


async def close_private_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user:
        return False
    tg = update.effective_user
    st.set_state(tg.id, private_chat=False)
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username)
        game = game_engine.active_session_for_user(session, user)
        awaiting = False
        is_chooser = False
        if game:
            rnd = game_engine.get_active_round(session, game)
            is_chooser = bool(rnd and rnd.chooser_user_id == user.id and not rnd.choice)
            awaiting = bool(
                rnd
                and rnd.target_user_id == user.id
                and rnd.choice
                and game_engine.round_has_prompt(rnd)
                and rnd.status == "open"
            )
    markup = kb.in_game_menu(is_chooser=is_chooser, awaiting_answer=awaiting)
    await update.message.reply_text(T.PRIVATE_CHAT_OFF, reply_markup=markup)
    return True


async def relay_private_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Relay any message to the matched peer with protect_content."""
    if not update.message or not update.effective_user:
        return False
    tg = update.effective_user
    state = st.get(tg.id)
    if not state.get("private_chat"):
        return False
    peer_tg = state.get("private_chat_peer")
    if not peer_tg:
        return False
    text = (update.message.text or "").strip()
    if text in {
        T.BTN_PRIVATE_CHAT,
        T.BTN_PRIVATE_CHAT_EXIT,
        T.BTN_GAME_PROFILE,
        T.BTN_GAME_END,
        T.BTN_SKIP,
        T.BTN_TRUTH,
        T.BTN_DARE,
        T.BTN_GAME_WAIT,
        T.BTN_REPORT_USER,
    }:
        return False
    try:
        await context.bot.copy_message(
            chat_id=peer_tg,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
            protect_content=True,
        )
    except Exception:
        logger.exception("private chat relay failed %s -> %s", tg.id, peer_tg)
        await update.message.reply_text("ارسال به حریف ناموفق بود.")
        return True
    return True


async def _ask_chooser_for_prompt(
    context,
    *,
    chooser_tg: int,
    kind: str,
    game_id: int,
    choice: str,
    glass_message=None,
) -> None:
    """Asker UI: pick bank category or type a custom text question."""
    text = T.OPPONENT_PICKED_ASK.format(kind=kind)
    action_id = None
    markup = kb.asker_bank_keyboard(game_id, choice)
    if glass_message is not None:
        try:
            await glass_message.edit_text(text, reply_markup=markup)
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
            inline_kb=markup,
        )
    st.set_state(
        chooser_tg,
        wait="asker_pick",
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
    media_type: str | None = None,
    file_id: str | None = None,
) -> None:
    if file_id and media_type:
        intro = T.YOUR_PROMPT_MEDIA.format(kind=kind)
        intro = f"{game_engine.format_round_info(round_number, max_rounds)}\n\n{intro}"
        mid = await upsert_hub(
            context.bot,
            target_tg,
            intro,
            message_id=st.get(target_tg).get("game_hub_message_id"),
            reply_kb=kb.in_game_menu(awaiting_answer=True),
            replace_keyboard=True,
        )
        st.set_state(target_tg, game_hub_message_id=mid)
        await _send_media(
            context.bot,
            target_tg,
            media_type=media_type,
            file_id=file_id,
            caption=prompt if prompt and prompt != _media_label(media_type) else None,
        )
    else:
        msg = T.YOUR_PROMPT.format(kind=kind, prompt=prompt)
        msg = f"{game_engine.format_round_info(round_number, max_rounds)}\n\n{msg}"
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
            if file_id and media_type:
                await context.bot.send_message(chat_id, f"{label} — {kind}:")
                await _send_media(
                    context.bot,
                    chat_id,
                    media_type=media_type,
                    file_id=file_id,
                    caption=prompt if prompt and prompt != _media_label(media_type) else None,
                    reply_markup=kb.skip_answer(game_id),
                )
            else:
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
        chooser = (
            session.get(User, rnd.chooser_user_id)
            if rnd and rnd.chooser_user_id
            else None
        )
        is_picker = bool(rnd and rnd.target_user_id == user.id and not rnd.choice)
        waiting_for_prompt = bool(
            rnd
            and rnd.target_user_id == user.id
            and rnd.choice
            and not game_engine.round_has_prompt(rnd)
            and rnd.status == "open"
        )
        awaiting = bool(
            rnd
            and rnd.target_user_id == user.id
            and rnd.choice
            and game_engine.round_has_prompt(rnd)
            and rnd.status == "open"
        )
        game_id = game.id
        picker_uid = rnd.target_user_id if rnd else None
        reply = kb.in_game_menu(is_chooser=False, awaiting_answer=awaiting)

    hub_id = await upsert_hub(
        context.bot,
        telegram_id,
        T.ALREADY_IN_GAME,
        message_id=st.get(telegram_id).get("game_hub_message_id"),
        reply_kb=reply,
        replace_keyboard=True,
    )
    glass_id = None
    if is_picker and picker_uid:
        round_line = game_engine.format_round_info(
            game.round_number, game.max_rounds
        )
        turn = f"{round_line}\n{T.CHOOSE_TRUTH_OR_DARE}"
        glass_id = await show_td_glass(
            context.bot,
            telegram_id,
            session_id=game_id,
            chooser_id=picker_uid,
            turn_text=turn,
            glass_message_id=st.get(telegram_id).get("game_glass_message_id"),
        )
    elif waiting_for_prompt:
        wait_text = _waiting_for_asker_text(chooser)
        try:
            glass_id = st.get(telegram_id).get("game_glass_message_id")
            if glass_id:
                await context.bot.edit_message_text(
                    chat_id=telegram_id,
                    message_id=glass_id,
                    text=wait_text,
                    reply_markup=None,
                )
            else:
                sent = await context.bot.send_message(telegram_id, wait_text)
                glass_id = sent.message_id
        except Exception:
            sent = await context.bot.send_message(telegram_id, wait_text)
            glass_id = sent.message_id
    st.set_state(
        telegram_id, game_hub_message_id=hub_id, game_glass_message_id=glass_id
    )
    return True


async def custom_prompt_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Let asker send a custom text question while choosing a bank category."""
    if not update.message or not update.effective_user or not update.message.text:
        return False
    tg = update.effective_user
    state = st.get(tg.id)
    if state.get("wait") != "asker_pick":
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

    return await _submit_custom_prompt(
        update,
        context,
        prompt_text=text,
        media_type=None,
        file_id=None,
    )


async def _submit_custom_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    prompt_text: str | None,
    media_type: str | None,
    file_id: str | None,
) -> bool:
    """Submit custom text/media prompt from asker to target."""
    tg = update.effective_user
    state = st.get(tg.id)
    if state.get("wait") != "asker_pick":
        return False
    game_id = state.get("custom_prompt_game_id")
    if not game_id:
        return False

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username)
        game = game_engine.get_session(session, int(game_id))
        if not game or game.status != "playing":
            if update.message:
                await update.message.reply_text("بازی فعال نیست.")
            st.set_state(tg.id, wait=None, custom_prompt_game_id=None, custom_prompt_choice=None)
            return True
        rnd = game_engine.get_active_round(session, game)
        if (
            not rnd
            or rnd.chooser_user_id != user.id
            or not rnd.choice
            or game_engine.round_has_prompt(rnd)
        ):
            if update.message:
                await update.message.reply_text(T.NOT_YOUR_TURN)
            st.set_state(tg.id, wait=None, custom_prompt_game_id=None, custom_prompt_choice=None)
            return True
        prompt = game_engine.apply_choice(
            session,
            rnd,
            rnd.choice,
            prompt_text,
            media_type=media_type,
            file_id=file_id,
        )
        target = session.get(User, rnd.target_user_id)
        from bot.services.questions import log_user_submitted_question, resolve_bucket

        log_user_submitted_question(
            session,
            session_id=game.id,
            round_id=rnd.id,
            submitter_user_id=user.id,
            target_user_id=target.id if target else None,
            kind=rnd.choice,
            suggested_bucket=resolve_bucket(
                getattr(target, "gender", None), getattr(target, "age", None)
            )
            if target
            else None,
            text=prompt,
        )
        target_tg = target.telegram_id if target else None
        round_number = game.round_number
        max_rounds = game.max_rounds
        kind = T.BTN_TRUTH if rnd.choice == "truth" else T.BTN_DARE

    st.set_state(
        tg.id,
        wait=None,
        custom_prompt_game_id=None,
        custom_prompt_choice=None,
        game_glass_message_id=None,
        pending_bank_prompt=prompt,
    )
    if update.message:
        await update.message.reply_text(T.CUSTOM_PROMPT_SENT.format(prompt=prompt))
    if target_tg:
        await _deliver_prompt_to_target(
            context,
            target_tg=target_tg,
            kind=kind,
            prompt=prompt,
            round_number=round_number,
            max_rounds=max_rounds,
            game_id=game_id,
            media_type=media_type,
            file_id=file_id,
        )
    return True


async def game_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user or not update.message.text:
        return False
    tg = update.effective_user
    text = update.message.text.strip()
    if text not in {
        T.BTN_GAME_PROFILE,
        T.BTN_GAME_END,
        T.BTN_PRIVATE_CHAT,
        T.BTN_PRIVATE_CHAT_EXIT,
        T.BTN_TRUTH,
        T.BTN_DARE,
        T.BTN_GAME_WAIT,
        T.BTN_SKIP,
    }:
        return False

    if text == T.BTN_PRIVATE_CHAT:
        return await open_private_chat(update, context)
    if text == T.BTN_PRIVATE_CHAT_EXIT:
        return await close_private_chat(update, context)

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        game = game_engine.active_session_for_user(session, user)
        if not game:
            await update.message.reply_text(T.NO_ACTIVE_GAME, reply_markup=kb.main_menu(tg.id))
            return True

        rnd = game_engine.get_active_round(session, game)

        if text == T.BTN_GAME_PROFILE:
            await _show_opponent_profile(context.bot, update.effective_user.id, session, user, game)
            return True

        if text == T.BTN_GAME_END:
            await update.message.reply_text(
                T.END_CONFIRM,
                reply_markup=kb.end_game_confirm_keyboard(game.id),
            )
            return True

        if text == T.BTN_GAME_WAIT:
            if (
                rnd
                and rnd.target_user_id == user.id
                and rnd.choice
                and not game_engine.round_has_prompt(rnd)
            ):
                asker = session.get(User, rnd.chooser_user_id)
                wait_text = _waiting_for_asker_text(asker)
                glass_id = st.get(tg.id).get("game_glass_message_id")
                try:
                    if glass_id:
                        await context.bot.edit_message_text(
                            chat_id=tg.id,
                            message_id=glass_id,
                            text=wait_text,
                            reply_markup=None,
                        )
                    else:
                        sent = await context.bot.send_message(tg.id, wait_text)
                        st.set_state(tg.id, game_glass_message_id=sent.message_id)
                except Exception:
                    pass
            return True

        if text == T.BTN_SKIP:
            if not rnd or rnd.target_user_id != user.id or not rnd.choice or not game_engine.round_has_prompt(rnd):
                await update.message.reply_text(T.NOT_YOUR_TURN)
                return True
            snap_prompt = (rnd.prompt_text or "").strip() or None
            game_engine.submit_answer(session, rnd, None)
            await _ack_answerer(context.bot, tg.id, skipped=True)
            await _notify_and_advance(
                context, session, game, user, "رد شد", prompt_text=snap_prompt
            )
            return True

        # Reply-keyboard T/D: answerer (target) picks for self
        if not rnd or rnd.target_user_id != user.id or rnd.choice:
            await update.message.reply_text(T.NOT_YOUR_TURN)
            return True

        choice = "truth" if text == T.BTN_TRUTH else "dare"
        game_engine.set_pending_choice(session, rnd, choice)
        kind = T.BTN_TRUTH if choice == "truth" else T.BTN_DARE
        game_id = game.id
        asker = session.get(User, rnd.chooser_user_id)
        asker_tg = asker.telegram_id if asker else None
        wait_text = _waiting_for_asker_text(asker)

    await update.message.reply_text(wait_text)
    if asker_tg:
        await _ask_chooser_for_prompt(
            context,
            chooser_tg=asker_tg,
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
            try:
                await query.message.reply_text(
                    T.END_CONFIRM,
                    reply_markup=kb.end_game_confirm_keyboard(game.id),
                )
            except Exception:
                await context.bot.send_message(
                    update.effective_user.id,
                    T.END_CONFIRM,
                    reply_markup=kb.end_game_confirm_keyboard(game.id),
                )
            return

    await query.answer()


async def on_end_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm / cancel ending the active game: endok:sid | endno:sid."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    parts = query.data.split(":")
    if len(parts) != 2:
        await query.answer()
        return
    action, sid = parts
    session_id = int(sid)
    tg = update.effective_user

    if action == "endno":
        await query.answer("ادامه می‌دیم 👍")
        try:
            await query.edit_message_text("اوکی، بازی ادامه داره.")
        except Exception:
            pass
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, session_id)
        if not game or game.status not in ("playing", "guessing"):
            await query.answer("این بازی فعال نیست.", show_alert=True)
            try:
                await query.edit_message_text("بازی دیگه فعال نیست.")
            except Exception:
                pass
            return
        players = game_engine.get_players(session, game)
        if user.id not in {p.user_id for p in players}:
            await query.answer(T.NOT_YOUR_TURN, show_alert=True)
            return
        await query.answer()
        try:
            await query.edit_message_text("بازی قطع شد.")
        except Exception:
            pass
        await _end_active_game(context, session, user, game)


async def on_game_after(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Continue finished game for 10 rounds or start a fresh new game."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, action, sid = parts
    game_id = int(sid)

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        game = game_engine.get_session(session, game_id)
        if not game or game.status != "finished":
            await query.answer("این بازی قابل ادامه نیست.", show_alert=True)
            return
        players = game_engine.get_players(session, game)
        if user.id not in {p.user_id for p in players}:
            await query.answer(T.NOT_YOUR_TURN, show_alert=True)
            return
        if action == "continue":
            nxt = game_engine.continue_game(session, game)
            if not nxt:
                await query.answer("ادامه این بازی ممکن نیست.", show_alert=True)
                return
            new_game = game
            text = T.GAME_CONTINUED
        elif action == "restart":
            nxt = game_engine.remake_two_player(session, game)
            if not nxt:
                await query.answer("شروع دوباره این بازی ممکن نیست.", show_alert=True)
                return
            new_game = session.get(type(game), nxt.session_id)
            text = T.GAME_RESTARTED
        else:
            await query.answer()
            return
        new_players = game_engine.get_players(session, new_game)
        await query.answer(text, show_alert=True)
        try:
            await query.edit_message_text(text)
        except Exception:
            pass
        await _broadcast_next_round(
            context,
            session,
            new_game,
            new_players,
            nxt,
            anonymous=(new_game.game_type == "anonymous"),
        )


async def on_truth_dare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    # td:session:picker(target):truth|dare
    parts = query.data.split(":")
    if len(parts) != 4:
        await query.answer()
        return
    _, sid, picker_id, choice = parts
    session_id = int(sid)
    picker_uid = int(picker_id)

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        if user.id != picker_uid:
            await query.answer(T.NOT_YOUR_TURN, show_alert=True)
            return
        await query.answer()
        game = game_engine.get_session(session, session_id)
        if not game or game.status != "playing":
            await query.edit_message_text("این بازی فعال نیست.")
            return
        rnd = game_engine.get_active_round(session, game)
        if not rnd or rnd.target_user_id != user.id or rnd.choice:
            await query.edit_message_text(T.NOT_YOUR_TURN)
            return
        game_engine.set_pending_choice(session, rnd, choice)
        kind = T.BTN_TRUTH if choice == "truth" else T.BTN_DARE
        asker = session.get(User, rnd.chooser_user_id)
        asker_tg = asker.telegram_id if asker else None
        game_id = game.id
        wait_text = _waiting_for_asker_text(asker)

    try:
        await query.edit_message_text(wait_text)
    except Exception:
        pass
    if asker_tg:
        await _ask_chooser_for_prompt(
            context,
            chooser_tg=asker_tg,
            kind=kind,
            game_id=game_id,
            choice=choice,
        )


async def on_asker_bank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Asker picks a bank category after opponent chose truth/dare: 1vq:sid:cat"""
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, sid, cat = parts
    session_id = int(sid)

    from bot.services.questions import CATEGORIES, random_prompt

    if cat == "custom":
        await query.answer()
        st.set_state(
            update.effective_user.id,
            wait="asker_pick",
            custom_prompt_game_id=session_id,
            custom_prompt_choice=None,
        )
        try:
            await query.edit_message_text("سوال خودت را تایپ کن ✍️")
        except Exception:
            pass
        return

    if cat not in CATEGORIES:
        await query.answer("دسته نامعتبر.", show_alert=True)
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        game = game_engine.get_session(session, session_id)
        if not game or game.status != "playing":
            await query.answer("بازی فعال نیست.", show_alert=True)
            return
        rnd = game_engine.get_active_round(session, game)
        if (
            not rnd
            or rnd.chooser_user_id != user.id
            or not rnd.choice
            or game_engine.round_has_prompt(rnd)
        ):
            await query.answer(T.NOT_YOUR_TURN, show_alert=True)
            return

        kind = rnd.choice
        _k, mode, _label = CATEGORIES[cat]
        seen = game_engine.used_prompts(session, game.id)
        if mode == "lucky":
            from bot.services.questions import BUCKETS
            import random as _rnd

            bucket = _rnd.choice(list(BUCKETS))
            prompt = random_prompt(
                kind, session=session, bucket=bucket, exclude=seen
            )  # type: ignore[arg-type]
        elif mode == "normal":
            prompt = random_prompt(kind, session=session, exclude=seen)  # type: ignore[arg-type]
        else:
            prompt = random_prompt(
                kind, session=session, bucket=mode, exclude=seen
            )  # type: ignore[arg-type]

        rnd.prompt_text = prompt
        rnd.category_key = cat
        rnd.prompt_media_type = None
        rnd.prompt_file_id = None
        rnd.prompt_source = "bank"
        target = session.get(User, rnd.target_user_id)
        target_tg = target.telegram_id if target else None
        round_number = game.round_number
        max_rounds = game.max_rounds

    await query.answer()
    asker_tg = update.effective_user.id
    try:
        await query.edit_message_text(T.BANK_PROMPT_SENT.format(prompt=prompt))
    except Exception:
        pass
    st.set_state(
        asker_tg,
        wait=None,
        custom_prompt_game_id=None,
        custom_prompt_choice=None,
        game_glass_message_id=query.message.message_id if query.message else None,
        pending_bank_prompt=prompt,
    )
    if not target_tg:
        return
    short_q = T.BANK_PROMPT_TO_TARGET.format(prompt=prompt)
    skip_kb = kb.skip_answer(session_id)
    await upsert_hub(
        context.bot,
        target_tg,
        short_q,
        message_id=st.get(target_tg).get("game_hub_message_id"),
        reply_kb=kb.in_game_menu(awaiting_answer=True),
        replace_keyboard=True,
    )
    glass_id = st.get(target_tg).get("game_glass_message_id")
    await _delete_game_messages(context.bot, target_tg, glass_id)
    try:
        sent = await context.bot.send_message(
            target_tg, short_q, reply_markup=skip_kb
        )
        glass_id = sent.message_id
    except Exception:
        logger.debug("bank prompt to target failed tg=%s", target_tg, exc_info=True)
        return
    st.set_state(target_tg, game_glass_message_id=glass_id)


async def on_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    session_id = int(query.data.split(":")[1])
    await _finish_answer(update, context, session_id, answer=None, via_callback=True)


async def answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Capture text answers when user is the target of an open round with a prompt."""
    if not update.message or not update.effective_user or not update.message.text:
        return False
    text = update.message.text.strip()
    if text.startswith("/") or text.startswith(
        ("🎭", "📍", "🕶", "👤", "🤝", "📖", "💬", "🔗", "👥", "✏️", "📜", "🔙", "🙂", "⛔", "⏳", "❌", "👁", "⏭", "🔒", "🎮", "🚩")
    ):
        return False
    return await _submit_answer(
        update, context, answer_text=text, media_type=None, file_id=None
    )


async def on_game_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle photo / voice / video / video_note as answer or private chat (not as asker prompt)."""
    if not update.message or not update.effective_user:
        return False
    media_type, file_id, caption = _extract_media(update.message)
    if not media_type or not file_id:
        return False

    state = st.get(update.effective_user.id)
    if state.get("wait") == "asker_pick":
        try:
            await update.message.reply_text(T.ASK_USE_BUTTONS)
        except Exception:
            pass
        return True

    handled = await _submit_answer(
        update,
        context,
        answer_text=caption,
        media_type=media_type,
        file_id=file_id,
    )
    if handled:
        return True

    if await relay_private_chat(update, context):
        return True
    return False


async def _submit_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    answer_text: str | None,
    media_type: str | None,
    file_id: str | None,
) -> bool:
    if not update.message or not update.effective_user:
        return False
    if not (answer_text and answer_text.strip()) and not file_id:
        return False

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        from bot.models import GameSession, Round
        from sqlalchemy import or_

        rows = (
            session.query(Round, GameSession)
            .join(GameSession, Round.session_id == GameSession.id)
            .filter(
                GameSession.status == "playing",
                # Group/channel have their own UIs — never scoop their rounds via DM text
                GameSession.game_type.in_(
                    ["friends", "stranger", "anonymous", "nearby", "fake_identity"]
                ),
                Round.target_user_id == user.id,
                Round.status == "open",
                Round.choice.isnot(None),
                or_(
                    Round.prompt_text.isnot(None),
                    Round.prompt_file_id.isnot(None),
                ),
            )
            .order_by(Round.id.desc())
            .all()
        )
        if not rows:
            return False
        rnd, game = rows[0]
        snap_prompt = (rnd.prompt_text or "").strip() or None
        game_engine.submit_answer(
            session,
            rnd,
            (answer_text or "").strip() or None,
            media_type=media_type,
            file_id=file_id,
        )
        snap_media = media_type
        snap_file = file_id
        snap_text = (answer_text or "").strip() or None
        answerer_tg = update.effective_user.id

        await _ack_answerer(context.bot, answerer_tg, skipped=False)
        await _notify_and_advance(
            context,
            session,
            game,
            user,
            snap_text,
            media_type=snap_media,
            file_id=snap_file,
            prompt_text=snap_prompt,
        )
    return True


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
        if not rnd.choice or not game_engine.round_has_prompt(rnd):
            return
        snap_prompt = (rnd.prompt_text or "").strip() or None
        game_engine.submit_answer(session, rnd, answer)
        answerer_tg = update.effective_user.id
        if via_callback:
            try:
                await update.callback_query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        await _ack_answerer(
            context.bot, answerer_tg, skipped=answer is None
        )
        await _notify_and_advance(
            context,
            session,
            game,
            user,
            answer or "رد شد",
            prompt_text=snap_prompt,
        )


async def _notify_and_advance(
    context,
    session,
    game,
    user,
    answer_text,
    *,
    media_type: str | None = None,
    file_id: str | None = None,
    prompt_text: str | None = None,
):
    players = game_engine.get_players(session, game)
    anonymous = game.game_type == "anonymous"
    if file_id and media_type:
        body = (answer_text or "").strip() or None
    else:
        body = (answer_text or "").strip() or "—"

    nxt = game_engine.advance_round(session, game)

    # Notify asker: delete old «منتظر جواب» bubble, send fresh Q+A below.
    for p in players:
        if p.user_id == user.id:
            continue
        peer_tg = p.user.telegram_id
        prompt = prompt_text or st.get(peer_tg).get("pending_bank_prompt")
        glass_id = st.get(peer_tg).get("game_glass_message_id")
        await _delete_game_messages(context.bot, peer_tg, glass_id)
        try:
            if file_id and media_type:
                cap = None
                if prompt:
                    cap = T.BANK_QA.format(
                        prompt=prompt, answer=(body or "📷")
                    )[:1024]
                else:
                    cap = body or None
                await _send_media(
                    context.bot,
                    peer_tg,
                    media_type=media_type,
                    file_id=file_id,
                    caption=cap,
                )
            else:
                text = (
                    T.BANK_QA.format(prompt=prompt, answer=body)
                    if prompt
                    else T.PEER_ANSWER_HUB.format(answer=body)
                )
                sent = await context.bot.send_message(peer_tg, text)
                st.set_state(peer_tg, game_glass_message_id=sent.message_id)
            st.set_state(peer_tg, pending_bank_prompt=None)
        except Exception:
            logger.debug("peer answer notify failed tg=%s", peer_tg, exc_info=True)

    if game.chat_id and game.game_type == "group":
        try:
            await _send_media(
                context.bot,
                game.chat_id,
                media_type=media_type,
                file_id=file_id,
                caption=body,
            )
        except Exception:
            pass

    if nxt is None and game.status in ("finished", "guessing"):
        summary = game.summary or ""
        game_id = game.id
        pairs = []
        for p in players:
            other = next((x for x in players if x.user_id != p.user_id), None)
            if p.user and other:
                pairs.append((p.user.telegram_id, other.user_id))
        for p in players:
            try:
                await context.bot.send_message(
                    p.user.telegram_id,
                    T.GAME_OVER_NEXT.format(summary=summary)
                    if game.status == "finished"
                    else T.GAME_OVER.format(summary=summary),
                    reply_markup=kb.post_game_continue_keyboard(game_id)
                    if game.status == "finished"
                    else kb.main_menu(p.user.telegram_id),
                )
            except Exception:
                pass
        for tg_id, other_uid in pairs:
            try:
                await _send_post_game_actions(context.bot, tg_id, game_id, other_uid)
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
                    game.chat_id,
                    T.GAME_OVER_NEXT.format(summary=summary)
                    if game.status == "finished"
                    else T.GAME_OVER.format(summary=summary),
                )
            except Exception:
                pass
        return

    if not nxt:
        return
    await _broadcast_next_round(
        context, session, game, players, nxt, anonymous=anonymous, answerer_id=user.id
    )


async def _broadcast_next_round(
    context, session, game, players, nxt, *, anonymous: bool, answerer_id: int | None = None
) -> None:
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

    round_line = game_engine.format_round_info(game.round_number, game.max_rounds)
    if game.game_type == "group":
        choose = T.GROUP_TURN.format(chooser=chooser_name, target=target_name)
    else:
        choose = T.CHOOSE_TRUTH_OR_DARE
    pick_text = f"{round_line}\n{choose}"

    # 1v1: answerer (target) picks T/D — new message at bottom; keep prior Q&A.
    if target and game.game_type != "group":
        try:
            glass_id = await show_td_glass(
                context.bot,
                target.telegram_id,
                session_id=game.id,
                chooser_id=nxt.target_user_id,
                turn_text=pick_text,
                glass_message_id=st.get(target.telegram_id).get("game_glass_message_id"),
                peer_answer=None,
                clear_hub=False,
            )
            # Fresh hub line each round — do not overwrite the answer ack bubble.
            hub_id = await upsert_hub(
                context.bot,
                target.telegram_id,
                round_line,
                message_id=None,
                reply_kb=kb.in_game_menu(is_chooser=False),
                replace_keyboard=True,
            )
            st.set_state(
                target.telegram_id,
                game_hub_message_id=hub_id,
                game_glass_message_id=glass_id,
            )
        except Exception:
            pass
        if chooser and (not target or chooser.id != target.id):
            try:
                if answerer_id and chooser.id == answerer_id:
                    wait_body = T.ROUND_WAIT_PICK_ACK.format(round=round_line)
                else:
                    wait_body = T.ROUND_WAIT_PICK.format(round=round_line)
                mid = await upsert_hub(
                    context.bot,
                    chooser.telegram_id,
                    wait_body,
                    message_id=None,  # always append — never overwrite Q&A hub
                    reply_kb=kb.in_game_menu(is_chooser=False),
                    replace_keyboard=True,
                )
                await clear_td_glass(context.bot, chooser.telegram_id)
                st.set_state(
                    chooser.telegram_id,
                    game_hub_message_id=mid,
                    game_glass_message_id=None,
                )
            except Exception:
                pass
        return

    if chooser:
        try:
            # Group path keeps legacy chooser glass
            glass_id = await show_td_glass(
                context.bot,
                chooser.telegram_id,
                session_id=game.id,
                chooser_id=nxt.chooser_user_id,
                turn_text=pick_text,
                glass_message_id=st.get(chooser.telegram_id).get("game_glass_message_id"),
            )
            hub_id = st.get(chooser.telegram_id).get("game_hub_message_id")
            if not hub_id:
                hub_id = await upsert_hub(
                    context.bot,
                    chooser.telegram_id,
                    T.MATCH_HUB.format(match_body=round_line),
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
                T.ROUND_WAIT_PICK.format(round=round_line),
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
                pick_text,
                reply_markup=kb.truth_dare(game.id, nxt.chooser_user_id),
            )
        except Exception:
            pass
