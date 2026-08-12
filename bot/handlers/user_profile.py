from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.models import User, UserReport
from bot.services import social as social_svc
from bot.services import users as user_svc
from bot.services.profile_card import (
    friend_request_keyboard,
    profile_report_keyboard,
    public_profile_keyboard,
    send_public_profile,
)
from bot.texts import fa as T

logger = logging.getLogger(__name__)


async def flush_online_notifies(
    context: ContextTypes.DEFAULT_TYPE, session, user: User
) -> None:
    """If user just came online, ping watchers."""
    became = bool(getattr(user, "_became_online", False))
    if not became:
        return
    name = user_svc.public_name(user)
    watchers = social_svc.collect_online_watchers(session, user, was_offline=True)
    for tid in watchers:
        try:
            await context.bot.send_message(tid, T.UP_ONLINE_PING.format(name=name))
        except Exception:
            pass


async def maybe_notify_profile_visit(
    context: ContextTypes.DEFAULT_TYPE, viewer: User, target: User
) -> None:
    if viewer.id == target.id:
        return
    if not bool(getattr(target, "notify_profile_visit", False)):
        return
    from bot.services.profile_links import profile_command

    try:
        await context.bot.send_message(
            target.telegram_id,
            T.PROFILE_VISIT_ALARM.format(profile=profile_command(viewer.id)),
        )
    except Exception:
        pass


async def maybe_notify_follow(
    context: ContextTypes.DEFAULT_TYPE, follower: User, followed: User
) -> None:
    if follower.id == followed.id:
        return
    if not bool(getattr(followed, "notify_follow", False)):
        return
    from bot.services.profile_links import profile_command

    try:
        await context.bot.send_message(
            followed.telegram_id,
            T.FOLLOW_ALARM.format(profile=profile_command(follower.id)),
        )
    except Exception:
        pass


async def _refresh_markup(query, session, me: User, target: User) -> None:
    likes = int(getattr(target, "likes_count", 0) or 0)
    markup = public_profile_keyboard(
        target,
        likes=likes,
        liked=social_svc.has_liked(session, me, target.id),
        blocked=social_svc.is_blocked(session, me, target.id),
        watching=social_svc.has_online_notify(session, me, target.id),
        is_contact=social_svc.has_contact(session, me, target.id),
    )
    try:
        await query.edit_message_reply_markup(reply_markup=markup)
    except Exception:
        pass


async def on_uprofile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    parts = query.data.split(":")
    if len(parts) < 3:
        await query.answer()
        return
    action, sid = parts[1], parts[2]
    target_id = int(sid)
    tg = update.effective_user

    with get_session() as session:
        me = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        await flush_online_notifies(context, session, me)
        target = session.get(User, target_id)
        if not target:
            await query.answer("پیدا نشد.", show_alert=True)
            return

        if action == "like":
            status, n = social_svc.like_user(session, me, target)
            msg = {
                "liked": T.LIKE_OK.format(n=n),
                "unliked": T.LIKE_REMOVED.format(n=n),
                "self": T.LIKE_SELF,
            }.get(status, T.ERROR_GENERIC)
            await query.answer(msg, show_alert=True)
            await _refresh_markup(query, session, me, target)
            return

        if action == "block":
            status = social_svc.toggle_block(session, me, target)
            msg = {
                "blocked": T.UP_BLOCKED,
                "unblocked": T.UP_UNBLOCKED,
                "self": T.UP_SELF,
            }.get(status, T.ERROR_GENERIC)
            await query.answer(msg, show_alert=True)
            await _refresh_markup(query, session, me, target)
            return

        if action == "notify":
            status = social_svc.toggle_online_notify(session, me, target)
            msg = {
                "on": T.UP_NOTIFY_ON,
                "off": T.UP_NOTIFY_OFF,
                "self": T.UP_SELF,
            }.get(status, T.ERROR_GENERIC)
            await query.answer(msg, show_alert=True)
            await _refresh_markup(query, session, me, target)
            return

        if action == "friend":
            if me.id == target.id:
                await query.answer(T.UP_SELF, show_alert=True)
                return
            if social_svc.has_contact(session, me, target.id):
                await query.answer(T.CONTACT_EXISTS, show_alert=True)
                return
            if social_svc.either_blocked(session, me, target):
                await query.answer(T.UP_BLOCKED_ACTION, show_alert=True)
                return
            me_name = user_svc.public_name(me)
            to_tg = target.telegram_id
            await query.answer(T.UP_FRIEND_SENT, show_alert=True)
            try:
                await context.bot.send_message(
                    to_tg,
                    T.UP_FRIEND_RECV.format(name=me_name),
                    reply_markup=friend_request_keyboard(me.id),
                )
            except Exception:
                await context.bot.send_message(tg.id, T.UP_DM_FAIL)
            return

        if action == "friend_ok":
            other = session.get(User, target_id)
            if not other:
                await query.answer(T.UP_GONE, show_alert=True)
                return
            status_me = social_svc.add_contact(session, me, other)
            status_other = social_svc.add_contact(session, other, me)
            await query.answer(T.UP_FRIEND_ACCEPTED, show_alert=True)
            try:
                await query.edit_message_text(T.UP_FRIEND_ACCEPTED)
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    other.telegram_id,
                    T.UP_FRIEND_ACCEPTED_PEER.format(name=user_svc.public_name(me)),
                )
            except Exception:
                pass
            if status_me == "added":
                await maybe_notify_follow(context, me, other)
            if status_other == "added":
                await maybe_notify_follow(context, other, me)
            return

        if action == "friend_no":
            await query.answer(T.UP_FRIEND_REJECTED)
            try:
                await query.edit_message_text(T.UP_FRIEND_REJECTED)
            except Exception:
                pass
            return

        if action == "play":
            if me.id == target.id:
                await query.answer(T.UP_SELF, show_alert=True)
                return
            if social_svc.either_blocked(session, me, target):
                await query.answer(T.UP_BLOCKED_ACTION, show_alert=True)
                return
            if social_svc.stranger_blocked_by_private(session, me, target):
                await query.answer(T.ACCOUNT_PRIVATE_BLOCKED, show_alert=True)
                return
            await query.answer()
            from bot.handlers import play_invite

            await play_invite.send_play_invite(context, from_tg=tg, to_user_id=target.id)
            return

        if action == "dm":
            if me.id == target.id:
                await query.answer(T.UP_SELF, show_alert=True)
                return
            if social_svc.either_blocked(session, me, target):
                await query.answer(T.UP_BLOCKED_ACTION, show_alert=True)
                return
            if social_svc.stranger_blocked_by_private(session, me, target):
                await query.answer(T.ACCOUNT_PRIVATE_BLOCKED, show_alert=True)
                return
            await query.answer()
            if target.show_private_id and target.username:
                await context.bot.send_message(
                    tg.id, T.UP_DM_USERNAME.format(username=target.username)
                )
                return
            st.set_state(tg.id, waiting="uprofile_dm", uprofile_dm_to=target.id)
            await context.bot.send_message(tg.id, T.UP_DM_ASK)
            return

        if action == "report":
            await query.answer()
            await context.bot.send_message(
                tg.id,
                T.REPORT_PICK_REASON,
                reply_markup=profile_report_keyboard(target.id),
            )
            return

    await query.answer()


async def on_upreport_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, reason, sid = parts
    target_id = int(sid)
    tg = update.effective_user

    if reason == "other":
        st.set_state(tg.id, waiting="uprofile_report", uprofile_report_to=target_id)
        await query.answer()
        try:
            await query.edit_message_text(T.REPORT_ASK_OTHER)
        except Exception:
            await context.bot.send_message(tg.id, T.REPORT_ASK_OTHER)
        return

    with get_session() as session:
        me = user_svc.get_or_create_user(session, tg.id, tg.username)
        target = session.get(User, target_id)
        if not target or me.id == target.id:
            await query.answer(T.REPORT_SELF, show_alert=True)
            return
        session.add(
            UserReport(
                reporter_id=me.id,
                reported_id=target.id,
                session_id=None,
                reason_code=reason,
                status="open",
            )
        )
    await query.answer(T.REPORT_OK, show_alert=True)
    try:
        await query.edit_message_text(T.REPORT_OK)
    except Exception:
        pass


async def uprofile_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle DM compose / report other text for public profiles."""
    if not update.message or not update.effective_user or not update.message.text:
        return False
    tg = update.effective_user
    state = st.get(tg.id)
    waiting = state.get("waiting")
    text = update.message.text.strip()

    if waiting == "uprofile_report":
        target_id = state.get("uprofile_report_to")
        st.set_state(tg.id, waiting=None, uprofile_report_to=None)
        if text in (T.BTN_CANCEL, T.BTN_BACK):
            await update.message.reply_text(T.ADMIN_CANCELLED)
            return True
        with get_session() as session:
            me = user_svc.get_or_create_user(session, tg.id, tg.username)
            target = session.get(User, int(target_id)) if target_id else None
            if not target:
                await update.message.reply_text(T.UP_GONE)
                return True
            session.add(
                UserReport(
                    reporter_id=me.id,
                    reported_id=target.id,
                    session_id=None,
                    reason_code="other",
                    reason_text=text[:500],
                    status="open",
                )
            )
        await update.message.reply_text(T.REPORT_OK)
        return True

    if waiting != "uprofile_dm":
        return False

    target_id = state.get("uprofile_dm_to")
    if text in (T.BTN_CANCEL, T.BTN_BACK):
        st.set_state(tg.id, waiting=None, uprofile_dm_to=None)
        await update.message.reply_text(T.ADMIN_CANCELLED)
        return True

    with get_session() as session:
        me = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        target = session.get(User, int(target_id)) if target_id else None
        if not target:
            st.set_state(tg.id, waiting=None, uprofile_dm_to=None)
            await update.message.reply_text(T.UP_GONE)
            return True
        if social_svc.either_blocked(session, me, target):
            st.set_state(tg.id, waiting=None, uprofile_dm_to=None)
            await update.message.reply_text(T.UP_BLOCKED_ACTION)
            return True
        if social_svc.stranger_blocked_by_private(session, me, target):
            st.set_state(tg.id, waiting=None, uprofile_dm_to=None)
            await update.message.reply_text(T.ACCOUNT_PRIVATE_BLOCKED)
            return True
        from bot.services.profile_links import profile_command

        me_profile = profile_command(me.id)
        to_tg = target.telegram_id
        from_id = me.id

    st.set_state(tg.id, waiting=None, uprofile_dm_to=None)
    try:
        await context.bot.send_message(
            to_tg,
            T.UP_DM_RECV.format(profile=me_profile, text=text),
            reply_markup=kb.dm_received_keyboard(from_id),
        )
        try:
            await context.bot.send_message(to_tg, T.SET_PRIVATE_HINT)
        except Exception:
            pass
    except Exception:
        await update.message.reply_text(T.UP_DM_FAIL)
        return True
    await update.message.reply_text(T.UP_DM_SENT)
    return True


async def show_user_profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int,
) -> None:
    """Helper: show public profile in reply to current message/callback."""
    if not update.effective_user:
        return
    message = update.message or (
        update.callback_query.message if update.callback_query else None
    )
    if not message:
        return
    with get_session() as session:
        me = user_svc.get_or_create_user(
            session,
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.full_name,
        )
        await flush_online_notifies(context, session, me)
        target = session.get(User, target_user_id)
        if not target:
            await message.reply_text(T.UP_GONE)
            return
        session.expunge(me)
        session.expunge(target)
    if me.id == target.id:
        from bot.services.profile_card import send_profile_card

        await send_profile_card(
            message,
            context,
            target,
            with_main_menu=False,
            edit_mode=True,
        )
        return
    await send_public_profile(message, context, viewer=me, target=target)
    if me.id != target.id:
        await maybe_notify_profile_visit(context, me, target)


async def on_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /Profile_<code> from text or photo caption (inline CachedPhoto)."""
    if not update.message or not update.effective_user:
        return
    from bot.services.profile_links import decode_profile_code, parse_profile_command

    raw = (update.message.text or update.message.caption or "").strip()
    # Caption may be only the command, or command on the first line.
    first = raw.splitlines()[0].strip() if raw else ""
    code = parse_profile_command(first) or parse_profile_command(raw)
    if not code:
        return
    uid = decode_profile_code(code)
    if not uid:
        await update.message.reply_text(T.UP_GONE)
        return
    await show_user_profile(update, context, uid)
