from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.config import BOT_USERNAME
from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import game_engine
from bot.services import users as user_svc
from bot.texts import fa as T

RESULT_START_GROUP = "gc_start_group"
RESULT_HELP_GROUP = "gc_help_group"
RESULT_START_CHANNEL = "gc_start_channel"
RESULT_HELP_CHANNEL = "gc_help_channel"

# Required so Telegram returns inline_message_id on chosen_inline_result
_PLACEHOLDER_MARKUP = InlineKeyboardMarkup(
    [[InlineKeyboardButton("⏳ …", callback_data="gc:noop")]]
)

_START_WORDS = ("شروع", "start", "بازی", "game")


def _bot_mention() -> str:
    return f"@{BOT_USERNAME}" if BOT_USERNAME else "@JoratHaqiqatBot"


def _norm(query: str) -> str:
    return (query or "").strip().lower()


def _is_start_query(query: str) -> bool:
    """Empty query or شروع / start / … → show start actions."""
    q = _norm(query)
    if not q:
        return True
    return any(w in q for w in _START_WORDS)


def _wants(query: str, *keywords: str) -> bool:
    q = _norm(query)
    if not q:
        return True
    return any(k in q for k in keywords)


def _article_start_group() -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=RESULT_START_GROUP,
        title=T.INLINE_TITLE_START_GROUP,
        description=T.INLINE_DESC_START_GROUP,
        input_message_content=InputTextMessageContent(T.INLINE_PLACEHOLDER_GROUP),
        reply_markup=_PLACEHOLDER_MARKUP,
    )


def _article_help_group(mention: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=RESULT_HELP_GROUP,
        title=T.INLINE_TITLE_HELP_GROUP,
        description=T.INLINE_DESC_HELP_GROUP,
        input_message_content=InputTextMessageContent(
            T.GROUP_INTRO.format(bot=mention)
        ),
    )


def _article_start_channel() -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=RESULT_START_CHANNEL,
        title=T.INLINE_TITLE_START_CHANNEL,
        description=T.INLINE_DESC_START_CHANNEL,
        input_message_content=InputTextMessageContent(T.INLINE_PLACEHOLDER_CHANNEL),
        reply_markup=_PLACEHOLDER_MARKUP,
    )


def _article_help_channel(mention: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=RESULT_HELP_CHANNEL,
        title=T.INLINE_TITLE_HELP_CHANNEL,
        description=T.INLINE_DESC_HELP_CHANNEL,
        input_message_content=InputTextMessageContent(
            T.CHANNEL_INTRO.format(bot=mention)
        ),
    )


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if not query:
        return

    qtext = query.query or ""
    chat_type = (query.chat_type or "").lower()
    mention = _bot_mention()
    results: list[InlineQueryResultArticle] = []
    start_q = _is_start_query(qtext)

    is_group = chat_type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
        "group",
        "supergroup",
    )
    is_channel = chat_type in (ChatType.CHANNEL, "channel")
    is_private = chat_type in (ChatType.PRIVATE, "private", "sender", "")

    # @Bot شروع  /  @Bot start  — same UX in group and channel
    if is_group:
        if start_q or _wants(qtext, "گروه", "group"):
            results.append(_article_start_group())
        if _wants(qtext, "گروه", "group", "راهنما", "help") or start_q:
            results.append(_article_help_group(mention))

    elif is_channel:
        if start_q or _wants(qtext, "کانال", "channel"):
            results.append(_article_start_channel())
        if _wants(qtext, "کانال", "channel", "راهنما", "help") or start_q:
            results.append(_article_help_channel(mention))

    else:
        # Private / unknown: show both starts on شروع|start
        if start_q or _wants(qtext, "گروه", "group"):
            results.append(_article_start_group())
        if start_q or _wants(qtext, "کانال", "channel"):
            results.append(_article_start_channel())
        if _wants(qtext, "گروه", "group", "راهنما", "help") or (
            start_q and not results
        ):
            results.append(_article_help_group(mention))
        if _wants(qtext, "کانال", "channel", "راهنما", "help") or (
            start_q and len(results) < 2
        ):
            results.append(_article_help_channel(mention))

    # Deduplicate by result id while keeping order
    seen: set[str] = set()
    unique: list[InlineQueryResultArticle] = []
    for item in results:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    results = unique

    if not results:
        if is_channel:
            results = [_article_start_channel(), _article_help_channel(mention)]
        elif is_group:
            results = [_article_start_group(), _article_help_group(mention)]
        else:
            results = [
                _article_start_group(),
                _article_start_channel(),
                _article_help_group(mention),
                _article_help_channel(mention),
            ]

    await query.answer(results[:50], cache_time=0, is_personal=True)


async def chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chosen = update.chosen_inline_result
    if not chosen or not chosen.from_user:
        return

    result_id = chosen.result_id
    inline_message_id = chosen.inline_message_id
    tg = chosen.from_user
    mention = _bot_mention()

    if result_id == RESULT_START_GROUP:
        if not inline_message_id:
            return
        with get_session() as session:
            user = user_svc.get_or_create_user(
                session, tg.id, tg.username, tg.full_name
            )
            existing = game_engine.find_registering_group(
                session, inline_message_id=inline_message_id
            )
            if existing:
                game = existing
            else:
                game = game_engine.create_session(
                    session,
                    "group",
                    starter=user,
                    max_rounds=8,
                    inline_message_id=inline_message_id,
                )
                game.status = "registering"
                game_engine.add_player(session, game, user)
            sid = game.id
            names = "، ".join(
                game_engine.display_for_player(p)
                for p in game_engine.get_players(session, game)
            )
            count = game_engine.player_count(session, game)

        text = (
            T.GROUP_REGISTER_OPEN.format(sid=sid)
            + "\n\n"
            + T.GROUP_PLAYERS_LIST.format(count=count, names=names)
        )
        try:
            await context.bot.edit_message_text(
                text=text,
                inline_message_id=inline_message_id,
                reply_markup=kb.join_group_game(sid),
            )
        except Exception:
            pass
        return

    if result_id == RESULT_START_CHANNEL:
        st.set_state(tg.id, mode="channel", wait="channel_id")
        text = T.CHANNEL_ID_ASK + T.CHANNEL_INTRO.format(bot=mention)
        if inline_message_id:
            try:
                await context.bot.edit_message_text(
                    text=text,
                    inline_message_id=inline_message_id,
                )
            except Exception:
                pass
        try:
            await context.bot.send_message(tg.id, text, reply_markup=main_menu())
        except Exception:
            pass
        return
