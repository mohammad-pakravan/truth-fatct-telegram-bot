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
RESULT_RESUME = "gc_resume"

_START_WORDS = ("شروع", "start", "بازی", "game")
_GAME_LOBBY_WORDS = ("game", "بازی", "شروع", "start", "گروه", "group")


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


def _is_game_lobby_query(query: str) -> bool:
    """Friends/group lobby (HJPlayBot-style) — including in channels."""
    q = _norm(query)
    if not q:
        return True
    return any(w in q for w in _GAME_LOBBY_WORDS)


def _wants_channel_mode(query: str) -> bool:
    q = _norm(query)
    return any(k in q for k in ("کانال", "channel"))


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


_THUMB_CACHE: dict[str, str] = {}


async def _thumbnail_url(bot, user) -> str | None:
    """HTTPS thumb for Article rows (list UI with avatar)."""
    return await ph_svc.thumb_url_for_user(bot, user)


async def _find_result(bot, user):
    """
    Vertical list row: avatar thumb + name + last-seen.
    Selecting sends only /Profile_… so the bot opens the profile in one step.
    """
    from bot.services.presence import presence_label
    from bot.services.profile_links import profile_command

    uid = int(getattr(user, "id", 0) or 0)
    in_game = bool(getattr(user, "in_game", False))
    name = user_svc.public_name(user)
    cmd = profile_command(uid)
    status = presence_label(
        last_active_at=getattr(user, "last_active_at", None), in_game=in_game
    )
    gender = getattr(user, "gender", None)
    # Emoji prefix so rows still look gendered if thumbnail_url fails to load.
    prefix = "👩 " if gender == "female" else "👨 " if gender == "male" else "👤 "
    title = (prefix + name)[:64]
    desc = status[:120]
    thumb = await _thumbnail_url(bot, user)
    kwargs = dict(
        id=f"find:{uid}",
        title=title,
        description=desc,
        input_message_content=InputTextMessageContent(cmd),
    )
    # Only attach thumbnail_url when we have a real public HTTPS link.
    # Broken/local URLs produce empty gray squares (worse than no thumb).
    if thumb and str(thumb).startswith("https://"):
        kwargs["thumbnail_url"] = thumb
        kwargs["thumbnail_width"] = 128
        kwargs["thumbnail_height"] = 128
    return InlineQueryResultArticle(**kwargs)


def _photo_result(prefix: str, user, *, with_play: bool = False):
    file_id = ph_svc.photo_file_id_for_user(user)
    caption = _profile_caption(user)
    title = _profile_title(user)
    desc = _profile_description(user)
    uid = int(getattr(user, "id", 0) or 0)
    rid = f"{prefix}:{uid}"
    play_kb = None
    if with_play and uid:
        in_game = bool(getattr(user, "in_game", False))
        if in_game:
            invite_btn = InlineKeyboardButton(
                T.BTN_ADV_IN_GAME,
                callback_data=f"adv_busy:{uid}",
            )
        else:
            invite_btn = InlineKeyboardButton(
                T.BTN_ADV_INVITE,
                callback_data=f"adv_play:{uid}",
            )
        play_kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"{T.BTN_VIEW_PROFILE} #{uid}"[:40],
                        callback_data=f"adv_prof:{uid}",
                    ),
                    invite_btn,
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


def _article_start_group(tg_user) -> InlineQueryResultArticle:
    """
    Build lobby card immediately (no placeholder).
    Avoids depending on chosen_inline_result / Inline Feedback.
    """
    from bot.handlers.group import _lobby_markup

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, tg_user.id, tg_user.username, tg_user.full_name
        )
        game = game_engine.create_session(
            session,
            "group",
            starter=user,
            max_rounds=0,
        )
        game.status = "registering"
        game_engine.add_player(session, game, user)
        sid = game.id
        names = "\n".join(
            f"• {game_engine.display_for_player(p)}"
            for p in game_engine.get_players(session, game)
        ) or "—"
        text = T.GROUP_REGISTER_OPEN.format(names=names)
        markup = _lobby_markup(session, sid)

    return InlineQueryResultArticle(
        id=f"{RESULT_START_GROUP}:{sid}",
        title=T.INLINE_TITLE_START_GROUP,
        description=T.INLINE_DESC_START_GROUP,
        input_message_content=InputTextMessageContent(text),
        reply_markup=markup,
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
    # Ready-to-send help (no placeholder stuck state)
    mention = _bot_mention()
    text = T.CHANNEL_ID_ASK + T.CHANNEL_INTRO.format(bot=mention)
    return InlineQueryResultArticle(
        id=RESULT_START_CHANNEL,
        title=T.INLINE_TITLE_START_CHANNEL,
        description=T.INLINE_DESC_START_CHANNEL,
        input_message_content=InputTextMessageContent(text),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📩 ادامه در پیوی ربات",
                        url=f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else "https://t.me/",
                    )
                ]
            ]
        ),
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


async def _find_results(tg_user, parsed: dict, bot) -> list:
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
            limit=50,
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
                    "age": u.age,
                    "likes_count": u.likes_count,
                    "last_active_at": u.last_active_at,
                    "profile_photo_file_id": u.profile_photo_file_id,
                    "profile_photo_key": u.profile_photo_key,
                    "show_photo": bool(u.show_photo),
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

    # Vertical article list: thumb + name + last-seen (not photo grid).
    out = []
    for s in snaps:
        out.append(await _find_result(bot, type("U", (), s)()))
    return out

def _parse_resume_sid(qtext: str) -> int | None:
    """Parse 'go 12' / 'go:12' / 'ادامه 12' for bump-to-bottom resume."""
    import re

    raw = (qtext or "").strip()
    m = re.match(
        r"^(?:go|cont|continue|resume|ادامه)\s*[#:]?\s*(\d+)\s*$",
        raw,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _article_resume_game(sid: int) -> InlineQueryResultArticle:
    from bot.handlers.group import build_game_card

    with get_session() as session:
        game = game_engine.get_session(session, sid)
        if not game or game.status not in ("playing", "registering"):
            return InlineQueryResultArticle(
                id=f"{RESULT_RESUME}:dead:{sid}",
                title="بازی تموم شده",
                description="این بازی دیگه فعال نیست",
                input_message_content=InputTextMessageContent(T.GROUP_ENDED),
            )
        text, markup = build_game_card(session, game)

    return InlineQueryResultArticle(
        id=f"{RESULT_RESUME}:{sid}",
        title="⬇️ انتقال بازی به پایین",
        description="همین کارت بازی رو پایین چت می‌فرسته",
        input_message_content=InputTextMessageContent(text),
        reply_markup=markup,
    )


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if not query:
        return

    qtext = query.query or ""
    chat_type = (query.chat_type or "").lower()
    mention = _bot_mention()

    resume_sid = _parse_resume_sid(qtext)
    if resume_sid is not None:
        await query.answer(
            [_article_resume_game(resume_sid)],
            cache_time=0,
            is_personal=True,
        )
        return

    social_mode, social_filt = _parse_social_query(qtext)
    if social_mode:
        results = await _social_results(query.from_user, social_mode, social_filt)
        await query.answer(results[:50], cache_time=0, is_personal=True)
        return

    from bot.services import search as search_svc

    find_parsed = search_svc.parse_gender_province_query(qtext)
    if find_parsed:
        results = await _find_results(query.from_user, find_parsed, context.bot)
        await query.answer(results[:50], cache_time=0, is_personal=True)
        return

    results: list[InlineQueryResultArticle] = []
    start_q = _is_start_query(qtext)
    lobby_q = _is_game_lobby_query(qtext)
    channel_q = _wants_channel_mode(qtext)

    is_group = chat_type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
        "group",
        "supergroup",
    )
    is_channel = chat_type in (ChatType.CHANNEL, "channel")

    # Friends lobby (@bot game) works in group, channel, and private.
    # Channel voting mode only when query explicitly says کانال/channel.
    if lobby_q and not channel_q:
        results.append(_article_start_group(query.from_user))
        if _wants(qtext, "گروه", "group", "راهنما", "help") or start_q:
            results.append(_article_help_group(mention))
    elif channel_q or (is_channel and start_q):
        results.append(_article_start_channel())
        results.append(_article_help_channel(mention))
    elif is_group:
        results.append(_article_start_group(query.from_user))
        results.append(_article_help_group(mention))
    else:
        # Private / unknown
        if lobby_q or _wants(qtext, "گروه", "group"):
            results.append(_article_start_group(query.from_user))
        if channel_q or _wants(qtext, "کانال", "channel"):
            results.append(_article_start_channel())
        if not results:
            results.append(_article_start_group(query.from_user))
            results.append(_article_start_channel())
        if _wants(qtext, "گروه", "group", "راهنما", "help") or start_q:
            results.append(_article_help_group(mention))
        if _wants(qtext, "کانال", "channel", "راهنما", "help") or start_q:
            results.append(_article_help_channel(mention))

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
        results = [
            _article_start_group(query.from_user),
            _article_help_group(mention),
        ]

    await query.answer(results[:50], cache_time=0, is_personal=True)


async def chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Optional: bind inline_message_id when Inline Feedback is enabled."""
    chosen = update.chosen_inline_result
    if not chosen or not chosen.from_user:
        return

    result_id = chosen.result_id or ""
    inline_message_id = chosen.inline_message_id
    tg = chosen.from_user
    mention = _bot_mention()

    # New format: gc_start_group:{sid} — lobby already in message; just bind id
    if result_id.startswith(f"{RESULT_START_GROUP}:"):
        if not inline_message_id:
            return
        try:
            sid = int(result_id.split(":", 1)[1])
        except ValueError:
            return
        with get_session() as session:
            game = game_engine.get_session(session, sid)
            if game:
                game.inline_message_id = inline_message_id
        return

    # Bump / resume card at bottom
    if result_id.startswith(f"{RESULT_RESUME}:"):
        parts = result_id.split(":")
        if len(parts) < 2 or parts[1] == "dead":
            return
        try:
            sid = int(parts[1])
        except ValueError:
            return
        with get_session() as session:
            game = game_engine.get_session(session, sid)
            if not game:
                return
            old_inline = game.inline_message_id
            if inline_message_id:
                game.inline_message_id = inline_message_id
        # Soften previous card if we still know it
        if old_inline and old_inline != inline_message_id:
            try:
                await context.bot.edit_message_text(
                    text="⬇️ بازی پایین‌تر منتقل شد.",
                    inline_message_id=old_inline,
                )
            except Exception:
                pass
        return

    # Legacy placeholder id (pre-fix)
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
                    max_rounds=0,
                    inline_message_id=inline_message_id,
                )
                game.status = "registering"
                game_engine.add_player(session, game, user)
            sid = game.id
            names = "\n".join(
                f"• {game_engine.display_for_player(p)}"
                for p in game_engine.get_players(session, game)
            ) or "—"
            from bot.handlers.group import _lobby_markup

            text = T.GROUP_REGISTER_OPEN.format(names=names)
            markup = _lobby_markup(session, sid)

        try:
            await context.bot.edit_message_text(
                text=text,
                inline_message_id=inline_message_id,
                reply_markup=markup,
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
