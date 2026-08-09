from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
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
from bot.services import placeholders as ph_svc
from bot.services import social as social_svc
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


def _parse_social_query(qtext: str) -> tuple[str | None, str]:
    """
    Return (mode, filter) where mode is 'likes' | 'contacts' | None.
    Examples: likes / لایک / contacts ali / مخاطب تهران
    """
    raw = (qtext or "").strip()
    if not raw:
        return None, ""
    parts = raw.split(None, 1)
    head = parts[0].lower()
    filt = parts[1].strip() if len(parts) > 1 else ""
    like_keys = ("likes", "like", "liked", "لایک", "لایکها", "لایک‌ها", "لایکشده", "لایک‌شده")
    contact_keys = ("contacts", "contact", "مخاطب", "مخاطبین", "کانتکت")
    if head in like_keys or any(head.startswith(k) for k in ("لایک", "like")):
        return "likes", filt
    if head in contact_keys or any(head.startswith(k) for k in ("مخاطب", "contact")):
        return "contacts", filt
    return None, ""


def _user_matches_filter(user, filt: str) -> bool:
    if not filt:
        return True
    f = filt.lower()
    blob = " ".join(
        [
            getattr(user, "display_name", None) or "",
            getattr(user, "nickname", None) or "",
            getattr(user, "city", None) or "",
            getattr(user, "province", None) or "",
            getattr(user, "username", None) or "",
        ]
    ).lower()
    return f in blob


def _profile_caption(user) -> str:
    from bot.services.presence import presence_label

    name = user_svc.public_name(user)
    city = getattr(user, "city", None) or getattr(user, "province", None) or "—"
    likes = int(getattr(user, "likes_count", 0) or 0)
    in_game = bool(getattr(user, "in_game", False))
    status = presence_label(
        last_active_at=getattr(user, "last_active_at", None), in_game=in_game
    )
    return (
        f"👤 {name}\n"
        f"🏙 {city}\n"
        f"❤️ {likes}\n"
        f"{status}"
    )


def _profile_title(user) -> str:
    from bot.services.presence import presence_badge

    in_game = bool(getattr(user, "in_game", False))
    dot = presence_badge(
        last_active_at=getattr(user, "last_active_at", None), in_game=in_game
    )
    return f"{dot} {user_svc.public_name(user)}"[:64]


def _profile_description(user) -> str:
    from bot.services.presence import presence_label

    city = getattr(user, "city", None) or getattr(user, "province", None) or "—"
    in_game = bool(getattr(user, "in_game", False))
    status = presence_label(
        last_active_at=getattr(user, "last_active_at", None), in_game=in_game
    )
    return f"{city} · {status}"[:120]


def _photo_result(prefix: str, user, *, with_play: bool = False):
    file_id = ph_svc.photo_file_id_for_user(user)
    caption = _profile_caption(user)
    title = _profile_title(user)
    desc = _profile_description(user)
    uid = int(getattr(user, "id", 0) or 0)
    rid = f"{prefix}:{uid}"
    play_kb = None
    if with_play and uid:
        play_kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📨 دعوت به بازی",
                        callback_data=f"adv_play:{uid}",
                    )
                ]
            ]
        )
    if file_id:
        return InlineQueryResultCachedPhoto(
            id=rid,
            photo_file_id=file_id,
            title=title,
            description=desc,
            caption=caption[:1024],
            reply_markup=play_kb,
        )
    return InlineQueryResultArticle(
        id=rid,
        title=title,
        description=desc,
        input_message_content=InputTextMessageContent(caption),
        reply_markup=play_kb,
    )


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


def _empty_social_article(mode: str) -> InlineQueryResultArticle:
    if mode == "likes":
        title = T.INLINE_LIKES_EMPTY_TITLE
        body = T.INLINE_LIKES_EMPTY
    else:
        title = T.INLINE_CONTACTS_EMPTY_TITLE
        body = T.INLINE_CONTACTS_EMPTY
    return InlineQueryResultArticle(
        id=f"empty:{mode}",
        title=title,
        description=body[:120],
        input_message_content=InputTextMessageContent(body),
    )


async def _social_results(tg_user, mode: str, filt: str) -> list:
    with get_session() as session:
        me = user_svc.get_or_create_user(
            session, tg_user.id, tg_user.username, tg_user.full_name
        )
        if mode == "likes":
            users = social_svc.list_liked_users(session, me, limit=40)
        else:
            users = social_svc.list_contact_users(session, me, limit=40)
        users = [u for u in users if _user_matches_filter(u, filt)]
        # Detach needed fields
        snaps = []
        for u in users:
            snaps.append(
                {
                    "id": u.id,
                    "display_name": u.display_name,
                    "nickname": u.nickname,
                    "city": u.city,
                    "province": u.province,
                    "username": u.username,
                    "gender": u.gender,
                    "likes_count": u.likes_count,
                    "last_active_at": u.last_active_at,
                    "profile_photo_file_id": u.profile_photo_file_id,
                    "in_game": bool(game_engine.active_session_for_user(session, u)),
                }
            )

    if not snaps:
        return [_empty_social_article(mode)]

    results = []
    for s in snaps:
        u = type("U", (), s)()
        item = _photo_result(mode, u)
        if item:
            results.append(item)
    return results


async def _find_results(tg_user, parsed: dict) -> list:
    from bot.services import search as search_svc

    with get_session() as session:
        me = user_svc.get_or_create_user(
            session, tg_user.id, tg_user.username, tg_user.full_name
        )
        users = search_svc.public_find_users(
            session,
            me,
            gender=parsed.get("gender"),
            province=parsed.get("province"),
            name_filter=parsed.get("name_filter"),
            limit=30,
        )
        snaps = []
        for u in users:
            snaps.append(
                {
                    "id": u.id,
                    "display_name": u.display_name,
                    "nickname": u.nickname,
                    "city": u.city,
                    "province": u.province,
                    "username": u.username,
                    "gender": u.gender,
                    "likes_count": u.likes_count,
                    "last_active_at": u.last_active_at,
                    "profile_photo_file_id": u.profile_photo_file_id,
                    "in_game": bool(game_engine.active_session_for_user(session, u)),
                }
            )

    if not snaps:
        return [
            InlineQueryResultArticle(
                id="empty:find",
                title=T.INLINE_FIND_EMPTY_TITLE,
                description=T.INLINE_FIND_EMPTY[:120],
                input_message_content=InputTextMessageContent(T.INLINE_FIND_EMPTY),
            )
        ]

    results = []
    for s in snaps:
        u = type("U", (), s)()
        item = _photo_result("find", u, with_play=True)
        if item:
            results.append(item)
    return results


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if not query:
        return

    qtext = query.query or ""
    chat_type = (query.chat_type or "").lower()
    mention = _bot_mention()

    social_mode, social_filt = _parse_social_query(qtext)
    if social_mode:
        results = await _social_results(query.from_user, social_mode, social_filt)
        await query.answer(results[:50], cache_time=0, is_personal=True)
        return

    from bot.services import search as search_svc

    find_parsed = search_svc.parse_gender_province_query(qtext)
    if find_parsed:
        results = await _find_results(query.from_user, find_parsed)
        await query.answer(results[:50], cache_time=0, is_personal=True)
        return

    results: list[InlineQueryResultArticle] = []
    start_q = _is_start_query(qtext)

    is_group = chat_type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
        "group",
        "supergroup",
    )
    is_channel = chat_type in (ChatType.CHANNEL, "channel")

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

        # Hint articles for social lists in private
        if start_q or not qtext.strip():
            results.insert(
                0,
                InlineQueryResultArticle(
                    id="hint:find",
                    title=T.INLINE_FIND_HINT_TITLE,
                    description=T.INLINE_FIND_HINT_DESC,
                    input_message_content=InputTextMessageContent(T.INLINE_FIND_HINT_MSG),
                ),
            )
            results.insert(
                1,
                InlineQueryResultArticle(
                    id="hint:likes",
                    title=T.INLINE_HINT_LIKES_TITLE,
                    description=T.INLINE_HINT_LIKES_DESC,
                    input_message_content=InputTextMessageContent(T.INLINE_HINT_LIKES_MSG),
                ),
            )
            results.insert(
                2,
                InlineQueryResultArticle(
                    id="hint:contacts",
                    title=T.INLINE_HINT_CONTACTS_TITLE,
                    description=T.INLINE_HINT_CONTACTS_DESC,
                    input_message_content=InputTextMessageContent(T.INLINE_HINT_CONTACTS_MSG),
                ),
            )

    # Deduplicate by result id while keeping order
    seen: set[str] = set()
    unique: list = []
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
            await context.bot.send_message(tg.id, text, reply_markup=main_menu(tg.id))
        except Exception:
            pass
        return
