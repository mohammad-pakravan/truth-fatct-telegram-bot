from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot.config import BOT_USERNAME
from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import User
from bot.services import game_engine
from bot.services import membership as mem_svc
from bot.services import users as user_svc
from bot.services.questions import CATEGORIES
from bot.texts import fa as T


def _bot_mention() -> str:
    return f"@{BOT_USERNAME}" if BOT_USERNAME else "@YourBot"


def _bind_inline_context(query, game) -> None:
    """Attach chat_id / inline_message_id from callback when available."""
    if query.message and query.message.chat:
        game.chat_id = query.message.chat.id
    if query.inline_message_id:
        game.inline_message_id = query.inline_message_id


async def _edit_callback_message(query, context, text: str, reply_markup=None) -> None:
    try:
        if query.inline_message_id:
            await context.bot.edit_message_text(
                text=text,
                inline_message_id=query.inline_message_id,
                reply_markup=reply_markup,
            )
        else:
            await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        pass


def _player_names(session, game) -> str:
    players = game_engine.get_players(session, game)
    if not players:
        return "—"
    return "\n".join(f"• {game_engine.display_for_player(p)}" for p in players)


def _lobby_text(session, game) -> str:
    return T.GROUP_REGISTER_OPEN.format(names=_player_names(session, game))


def _sponsor_buttons(session) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[int] = set()
    for ch in mem_svc.list_all_channels(session):
        if not ch.active or not ch.invite_link:
            continue
        if ch.chat_id in seen:
            continue
        seen.add(ch.chat_id)
        label = mem_svc.channel_label(ch)
        out.append((label, ch.invite_link))
        if len(out) >= 5:
            break
    return out


def _lobby_markup(session, sid: int):
    return kb.join_group_game(sid, sponsor_buttons=_sponsor_buttons(session))


def _turn_name(session, game) -> str:
    uid = game.current_turn_user_id
    for p in game_engine.get_players(session, game):
        if p.user_id == uid:
            return game_engine.display_for_player(p)
    return "?"


def _pick_text(session, game) -> str:
    return T.GROUP_TURN_PICK.format(
        started=T.GROUP_STARTED,
        name=_turn_name(session, game),
    )


async def open_group_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        T.HUB_FRIENDS_TEXT,
        reply_markup=kb.hub_friends_inline(),
    )


async def gc_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if query.data == "gc:noop":
        return
    mention = _bot_mention()
    if query.data == "gc:group":
        await query.edit_message_text(
            T.GROUP_INTRO.format(bot=mention),
            reply_markup=kb.group_channel_help(),
        )
    elif query.data == "gc:channel":
        await query.edit_message_text(
            T.CHANNEL_INTRO.format(bot=mention),
            reply_markup=kb.group_channel_help(),
        )


async def group_game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    chat = update.effective_chat
    mention = _bot_mention()
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text(
            "این دستور رو داخل گروه بزن.\n\n" + T.GROUP_INTRO.format(bot=mention),
            reply_markup=main_menu(update.effective_user.id),
        )
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session,
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.full_name,
        )
        existing = game_engine.find_registering_group(session, chat_id=chat.id)
        if existing:
            game = existing
            game_engine.add_player(session, game, user)
        else:
            game = game_engine.create_session(
                session, "group", starter=user, chat_id=chat.id, max_rounds=0
            )
            game.status = "registering"
            game_engine.add_player(session, game, user)
        sid = game.id
        text = _lobby_text(session, game)
        markup = _lobby_markup(session, sid)

    await update.message.reply_text(text, reply_markup=markup)


async def group_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    data = query.data
    tg = update.effective_user

    if data.startswith("gjoin:"):
        await _on_join(query, context, tg, data, mid=False)
        return
    if data.startswith("grejoin:"):
        await _on_join(query, context, tg, data, mid=True)
        return
    if data.startswith("gstart:"):
        await _on_start(query, context, tg, data)
        return
    if data.startswith("gcat:"):
        await _on_category(query, context, tg, data)
        return
    if data.startswith("greshuf:"):
        await _on_reshuffle(query, context, tg, data)
        return
    if data.startswith("gdone:"):
        await _on_answered(query, context, tg, data)
        return
    if data.startswith("gnext:"):
        await _on_next(query, context, tg, data)
        return
    if data.startswith("gend:"):
        await _on_end(query, context, tg, data)
        return


def _telegram_account_name(tg) -> str:
    """Best-effort Telegram display name for users who never started the bot."""
    name = (getattr(tg, "full_name", None) or "").strip()
    if name:
        return name[:64]
    first = (getattr(tg, "first_name", None) or "").strip()
    last = (getattr(tg, "last_name", None) or "").strip()
    combined = f"{first} {last}".strip()
    if combined:
        return combined[:64]
    uname = getattr(tg, "username", None)
    if uname:
        return f"@{uname}"
    return "بازیکن"


def _require_group(game) -> bool:
    return bool(game and game.game_type == "group")


async def _on_join(query, context, tg, data: str, *, mid: bool) -> None:
    sid = int(data.split(":")[1])
    account_name = _telegram_account_name(tg)
    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, tg.id, tg.username, account_name
        )
        # No full profile yet → keep showing Telegram account name in this game
        label = None
        if not user_svc.profile_complete(user):
            user.display_name = account_name
            label = account_name
        game = game_engine.get_session(session, sid)
        if not _require_group(game):
            await query.answer("بازی پیدا نشد.", show_alert=True)
            return
        if mid:
            if game.status != "playing":
                await query.answer("بازی در جریان نیست.", show_alert=True)
                return
        elif game.status != "registering":
            await query.answer("ثبت‌نام بسته شده.", show_alert=True)
            return
        _bind_inline_context(query, game)
        before = game_engine.player_count(session, game)
        player = game_engine.add_player(session, game, user, display_label=label)
        if label and player.display_label != label:
            player.display_label = label
        after = game_engine.player_count(session, game)
        if mid:
            text = _pick_text(session, game)
            markup = kb.group_category_keyboard(sid)
        else:
            text = _lobby_text(session, game)
            markup = _lobby_markup(session, sid)

    if before == after:
        await query.answer(T.ALREADY_JOINED, show_alert=True)
    else:
        await query.answer("ثبت شد!")
    await _edit_callback_message(query, context, text, reply_markup=markup)


async def _on_start(query, context, tg, data: str) -> None:
    sid = int(data.split(":")[1])
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, sid)
        if not _require_group(game) or game.status != "registering":
            await query.answer("بازی قبلاً شروع شده یا نیست.", show_alert=True)
            return
        _bind_inline_context(query, game)
        if game.starter_user_id and game.starter_user_id != user.id:
            await query.answer(T.GROUP_ONLY_STARTER, show_alert=True)
            return
        if game_engine.player_count(session, game) < 2:
            await query.answer(T.NEED_TWO_PLAYERS, show_alert=True)
            return
        game_engine.start_group_rotation(session, game)
        text = _pick_text(session, game)
        markup = kb.group_category_keyboard(sid)
    await query.answer()
    await _edit_callback_message(query, context, text, reply_markup=markup)


def _require_turn(session, game, user) -> bool:
    return game.current_turn_user_id == user.id


async def _on_category(query, context, tg, data: str) -> None:
    # gcat:{sid}:{cat}
    parts = data.split(":")
    if len(parts) < 3:
        return
    sid = int(parts[1])
    cat = parts[2]
    if cat not in CATEGORIES:
        await query.answer("دسته نامعتبر.", show_alert=True)
        return
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, sid)
        if not _require_group(game) or game.status != "playing":
            await query.answer("بازی فعال نیست.", show_alert=True)
            return
        _bind_inline_context(query, game)
        if not _require_turn(session, game, user):
            await query.answer(T.GROUP_NOT_YOUR_TURN, show_alert=True)
            return
        rnd = game_engine.get_active_round(session, game)
        if not rnd:
            await query.answer(T.ERROR_GENERIC, show_alert=True)
            return
        label, prompt = game_engine.apply_category_prompt(session, rnd, cat)
        name = _turn_name(session, game)
        text = T.GROUP_QUESTION.format(name=name, category=label, prompt=prompt)
        markup = kb.group_question_keyboard(sid, cat)
    await query.answer()
    await _edit_callback_message(query, context, text, reply_markup=markup)


async def _on_reshuffle(query, context, tg, data: str) -> None:
    parts = data.split(":")
    if len(parts) < 3:
        return
    sid = int(parts[1])
    cat = parts[2]
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, sid)
        if not _require_group(game) or game.status != "playing":
            await query.answer("بازی فعال نیست.", show_alert=True)
            return
        _bind_inline_context(query, game)
        if not _require_turn(session, game, user):
            await query.answer(T.GROUP_NOT_YOUR_TURN, show_alert=True)
            return
        rnd = game_engine.get_active_round(session, game)
        if not rnd:
            await query.answer(T.ERROR_GENERIC, show_alert=True)
            return
        label, prompt = game_engine.apply_category_prompt(session, rnd, cat)
        name = _turn_name(session, game)
        text = T.GROUP_QUESTION.format(name=name, category=label, prompt=prompt)
        markup = kb.group_question_keyboard(sid, cat)
    await query.answer("سوال عوض شد")
    await _edit_callback_message(query, context, text, reply_markup=markup)


async def _on_answered(query, context, tg, data: str) -> None:
    sid = int(data.split(":")[1])
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, sid)
        if not _require_group(game) or game.status != "playing":
            await query.answer("بازی فعال نیست.", show_alert=True)
            return
        _bind_inline_context(query, game)
        if not _require_turn(session, game, user):
            await query.answer(T.GROUP_NOT_YOUR_TURN, show_alert=True)
            return
        rnd = game_engine.get_active_round(session, game)
        if rnd and rnd.status == "open":
            game_engine.submit_answer(session, rnd, "(پاسخ دادم)")
        game_engine.advance_group_self_turn(session, game)
        text = _pick_text(session, game)
        markup = kb.group_category_keyboard(sid)
    await query.answer()
    await _edit_callback_message(query, context, text, reply_markup=markup)


async def _on_next(query, context, tg, data: str) -> None:
    sid = int(data.split(":")[1])
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, sid)
        if not _require_group(game) or game.status != "playing":
            await query.answer("بازی فعال نیست.", show_alert=True)
            return
        _bind_inline_context(query, game)
        if game.starter_user_id != user.id:
            await query.answer(T.GROUP_ONLY_STARTER, show_alert=True)
            return
        game_engine.advance_group_self_turn(session, game)
        text = _pick_text(session, game)
        markup = kb.group_category_keyboard(sid)
    await query.answer()
    await _edit_callback_message(query, context, text, reply_markup=markup)


async def _on_end(query, context, tg, data: str) -> None:
    sid = int(data.split(":")[1])
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        game = game_engine.get_session(session, sid)
        if not _require_group(game) or game.status not in ("playing", "registering"):
            await query.answer("بازی تموم شده.", show_alert=True)
            return
        _bind_inline_context(query, game)
        if game.starter_user_id != user.id:
            await query.answer(T.GROUP_ONLY_STARTER, show_alert=True)
            return
        game_engine.finish_game(session, game)
        summary = game.summary or T.GROUP_ENDED
        text = f"{T.GROUP_ENDED}\n\n{summary}"
    await query.answer()
    await _edit_callback_message(query, context, text, reply_markup=None)


def build_game_card(session, game) -> tuple[str, object]:
    """Current playing/lobby card text + markup for resume / bump."""
    if game.game_type != "group":
        return T.GROUP_ENDED, None
    sid = game.id
    if game.status == "registering":
        return _lobby_text(session, game), _lobby_markup(session, sid)
    if game.status != "playing":
        return T.GROUP_ENDED, None
    rnd = game_engine.get_active_round(session, game)
    name = _turn_name(session, game)
    if rnd and rnd.prompt_text:
        cat = getattr(rnd, "category_key", None) or "lucky"
        meta = CATEGORIES.get(cat)
        cat_label = meta[2] if meta else "سوال"
        text = T.GROUP_QUESTION.format(
            name=name, category=cat_label, prompt=rnd.prompt_text
        )
        return text, kb.group_question_keyboard(sid, cat)
    return _pick_text(session, game), kb.group_category_keyboard(sid)
