from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.config import contact_display
from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import users as user_svc
from bot.texts import fa as T


async def open_hub_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    st.set_state(update.effective_user.id, mode="hub_play")
    await update.message.reply_text(T.HUB_PLAY_TEXT, reply_markup=kb.hub_play_menu())


async def open_hub_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    st.set_state(update.effective_user.id, mode="hub_profile")
    await update.message.reply_text(T.HUB_PROFILE_TEXT, reply_markup=kb.hub_profile_menu())


async def open_hub_friends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    st.set_state(update.effective_user.id, mode="hub_friends")
    await update.message.reply_text(T.HUB_FRIENDS_TEXT, reply_markup=kb.hub_friends_inline())


async def hub_friends_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    tg = update.effective_user
    data = query.data
    await query.answer()

    if data == "hubf:back":
        st.clear(tg.id)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await context.bot.send_message(tg.id, T.MAIN_MENU_TITLE, reply_markup=main_menu(tg.id))
        return

    if data == "hubf:link":
        from bot.handlers import wizard

        if await wizard.maybe_require_wizard(update, context, feature=T.BTN_FRIENDS):
            return
        st.clear(tg.id)
        st.set_state(tg.id, mode="friends")
        await context.bot.send_message(
            tg.id, T.FRIENDS_INTRO, reply_markup=kb.invite_display_mode()
        )
        return

    if data == "hubf:group":
        from bot.config import BOT_USERNAME
        from bot.handlers import wizard

        if await wizard.maybe_require_wizard(update, context, feature=T.BTN_GROUP_CHANNEL):
            return
        st.clear(tg.id)
        mention = f"@{BOT_USERNAME}" if BOT_USERNAME else "@YourBot"
        await context.bot.send_message(
            tg.id,
            T.GC_MENU_INTRO.format(bot=mention),
            reply_markup=kb.group_channel_help(),
        )
        return


async def open_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        T.HELP_TEXT.format(contact=contact_display()),
        reply_markup=main_menu(update.effective_user.id),
    )

async def open_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        T.CONTACT_TEXT.format(contact=contact_display()),
        reply_markup=main_menu(update.effective_user.id),
    )


async def hub_play_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle buttons inside play hub. Returns True if handled."""
    if not update.message or not update.effective_user:
        return False
    if st.get(update.effective_user.id).get("mode") != "hub_play":
        return False

    text = (update.message.text or "").strip()
    tg = update.effective_user

    if text == T.BTN_BACK:
        st.clear(tg.id)
        await update.message.reply_text(T.MAIN_MENU_TITLE, reply_markup=main_menu(tg.id))
        return True

    launchers = {
        T.BTN_PLAY_NORMAL: "stranger",
        T.BTN_STRANGER: "stranger",
        T.BTN_ANON: "anon",
        T.BTN_FAKE: "fake",
        T.BTN_NEARBY: "nearby",
        T.BTN_PLAY_FRIEND_LINK: "friends",
        T.BTN_FRIENDS: "friends",
        T.BTN_GROUP_CHANNEL: "group",
    }
    kind = launchers.get(text)
    if not kind:
        return False

    # Soft-gate profile before leaving hub
    feature = text
    from bot.handlers import wizard

    if await wizard.maybe_require_wizard(update, context, feature=feature):
        return True

    # Leave hub so the target flow owns conversation state
    st.clear(tg.id)

    if kind == "stranger":
        from bot.handlers import stranger

        await stranger.open_stranger(update, context)
    elif kind == "anon":
        from bot.handlers import stranger

        await stranger.open_anonymous(update, context)
    elif kind == "fake":
        from bot.handlers import fake

        await fake.open_fake(update, context)
    elif kind == "nearby":
        from bot.handlers import stranger

        await stranger.open_nearby(update, context)
    elif kind == "friends":
        from bot.handlers import friends

        await friends.open_friends(update, context)
    elif kind == "group":
        from bot.handlers import group

        await group.open_group_channel(update, context)
    return True


async def hub_profile_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle buttons inside profile hub. Returns True if handled."""
    if not update.message or not update.effective_user:
        return False
    if st.get(update.effective_user.id).get("mode") != "hub_profile":
        return False

    text = (update.message.text or "").strip()
    tg = update.effective_user

    if text == T.BTN_BACK:
        st.clear(tg.id)
        await update.message.reply_text(T.MAIN_MENU_TITLE, reply_markup=main_menu(tg.id))
        return True

    if text == T.BTN_SHOW_PROFILE:
        from bot.services.profile_card import send_profile_card

        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            session.expunge(user)
        await send_profile_card(
            update.message,
            context,
            user,
            with_main_menu=False,
            edit_mode=True,
        )
        await update.message.reply_text(T.HUB_PROFILE_TEXT, reply_markup=kb.hub_profile_menu())
        return True

    if text == T.BTN_PROFILE:
        from bot.handlers import profile

        await profile.open_profile(update, context)
        return True

    if text == T.BTN_RUN_WIZARD:
        from bot.handlers import wizard

        await wizard.start_wizard(update, context, force=True)
        return True

    if text == T.BTN_HISTORY:
        from bot.handlers import history

        st.clear(tg.id)
        await history.open_history(update, context)
        return True

    if text == T.BTN_HELP:
        await open_help(update, context)
        return True

    if text == T.BTN_GAME_SETTINGS:
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            markup = kb.settings_keyboard(user)
        await update.message.reply_text(T.SETTINGS_MENU, reply_markup=markup)
        return True

    return False


async def hub_friends_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user:
        return False
    if st.get(update.effective_user.id).get("mode") != "hub_friends":
        return False

    text = (update.message.text or "").strip()
    tg = update.effective_user

    if text == T.BTN_BACK:
        st.clear(tg.id)
        await update.message.reply_text(T.MAIN_MENU_TITLE, reply_markup=main_menu(tg.id))
        return True

    if text in (T.BTN_FRIENDS, T.BTN_PLAY_FRIEND_LINK):
        from bot.handlers import friends
        from bot.handlers import wizard

        if await wizard.maybe_require_wizard(update, context, feature=text):
            return True
        st.clear(tg.id)
        await friends.open_friends(update, context)
        return True

    if text == T.BTN_CONTACTS:
        # Prefer inline list; keep a short reply pointing there
        await update.message.reply_text(
            "برای دیدن مخاطبین با عکس، از دکمهٔ شیشه‌ای «📒 مخاطبین» بالا استفاده کن.",
            reply_markup=kb.hub_friends_inline(),
        )
        return True

    if text == T.BTN_GROUP_CHANNEL:
        from bot.handlers import group
        from bot.handlers import wizard

        if await wizard.maybe_require_wizard(update, context, feature=text):
            return True
        st.clear(tg.id)
        await group.open_group_channel(update, context)
        return True

    return False


async def open_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    from bot.services import social as social_svc

    with get_session() as session:
        user = user_svc.get_or_create_user(
            session, update.effective_user.id, update.effective_user.username
        )
        rows = social_svc.list_contacts(session, user)
        if not rows:
            await update.message.reply_text(T.CONTACTS_EMPTY, reply_markup=kb.hub_friends_menu())
            return
        items: list[tuple[int, str]] = []
        lines = []
        for row in rows:
            c = row.contact
            if not c:
                continue
            name = user_svc.public_name(c)
            likes = int(getattr(c, "likes_count", 0) or 0)
            from bot.services.presence import format_last_seen

            seen = format_last_seen(getattr(c, "last_active_at", None))
            items.append((c.id, name))
            lines.append(f"• {name} — ❤️ {likes}\n  {seen}")
        body = T.CONTACTS_HEADER.format(n=len(items)) + "\n" + "\n".join(lines)
        markup = kb.contacts_list_keyboard(items)
    await update.message.reply_text(body, reply_markup=markup)


async def contacts_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    from bot.services import social as social_svc
    from bot.models import User

    data = query.data
    tg = update.effective_user

    if data == "contact:back":
        await query.answer()
        try:
            await query.edit_message_text(T.HUB_FRIENDS_TEXT)
        except Exception:
            pass
        return

    if data.startswith("contact:del:"):
        cid = int(data.split(":")[2])
        with get_session() as session:
            me = user_svc.get_or_create_user(session, tg.id, tg.username)
            social_svc.remove_contact(session, me, cid)
            rows = social_svc.list_contacts(session, me)
            if not rows:
                await query.answer(T.CONTACT_REMOVED)
                await query.edit_message_text(T.CONTACTS_EMPTY)
                return
            items = []
            lines = []
            for row in rows:
                c = row.contact
                if not c:
                    continue
                name = user_svc.public_name(c)
                likes = int(getattr(c, "likes_count", 0) or 0)
                from bot.services.presence import format_last_seen

                seen = format_last_seen(getattr(c, "last_active_at", None))
                items.append((c.id, name))
                lines.append(f"• {name} — ❤️ {likes}\n  {seen}")
            body = T.CONTACTS_HEADER.format(n=len(items)) + "\n" + "\n".join(lines)
            markup = kb.contacts_list_keyboard(items)
        await query.answer(T.CONTACT_REMOVED)
        await query.edit_message_text(body, reply_markup=markup)
        return

    if data.startswith("contact:view:"):
        cid = int(data.split(":")[2])
        await query.answer()
        from bot.handlers import user_profile

        await user_profile.show_user_profile(update, context, cid)
        return

    await query.answer()
