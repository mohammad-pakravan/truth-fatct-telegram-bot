from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import User
from bot.services import game_engine
from bot.services import play_invites as invite_svc
from bot.services import social as social_svc
from bot.services import users as user_svc
from bot.services.glass_msg import show_td_glass, upsert_hub
from bot.texts import fa as T

logger = logging.getLogger(__name__)


def _schedule_expire(context: ContextTypes.DEFAULT_TYPE, invite_id: int) -> None:
    jq = context.application.job_queue
    if not jq:
        logger.warning("No job_queue — invite %s will not auto-expire", invite_id)
        return
    name = f"play_invite_expire_{invite_id}"
    for job in jq.get_jobs_by_name(name):
        job.schedule_removal()
    jq.run_once(
        expire_invite_job,
        when=invite_svc.INVITE_TTL_SECONDS,
        data={"invite_id": invite_id},
        name=name,
    )


def _cancel_expire_job(context: ContextTypes.DEFAULT_TYPE, invite_id: int) -> None:
    jq = context.application.job_queue
    if not jq:
        return
    for job in jq.get_jobs_by_name(f"play_invite_expire_{invite_id}"):
        job.schedule_removal()


async def expire_invite_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    invite_id = int(data.get("invite_id") or 0)
    if not invite_id:
        return
    from_tg = to_tg = None
    from_name = to_name = "?"
    from_mid = to_mid = None
    with get_session() as session:
        inv = invite_svc.get_invite(session, invite_id)
        if not inv or inv.status != "pending":
            return
        invite_svc.set_status(session, inv, "expired")
        fu = session.get(User, inv.from_user_id)
        tu = session.get(User, inv.to_user_id)
        from_tg = fu.telegram_id if fu else None
        to_tg = tu.telegram_id if tu else None
        from_name = user_svc.public_name(fu) if fu else "?"
        to_name = user_svc.public_name(tu) if tu else "?"
        from_mid = inv.from_message_id
        to_mid = inv.to_message_id

    if from_tg:
        try:
            if from_mid:
                await context.bot.edit_message_text(
                    T.INVITE_EXPIRED_FROM.format(name=to_name),
                    chat_id=from_tg,
                    message_id=from_mid,
                )
            else:
                await context.bot.send_message(
                    from_tg, T.INVITE_EXPIRED_FROM.format(name=to_name), reply_markup=main_menu(from_tg)
                )
        except Exception:
            try:
                await context.bot.send_message(
                    from_tg, T.INVITE_EXPIRED_FROM.format(name=to_name), reply_markup=main_menu(from_tg)
                )
            except Exception:
                pass
    if to_tg:
        try:
            if to_mid:
                await context.bot.edit_message_text(
                    T.INVITE_EXPIRED_TO,
                    chat_id=to_tg,
                    message_id=to_mid,
                )
            else:
                await context.bot.send_message(to_tg, T.INVITE_EXPIRED_TO, reply_markup=main_menu(to_tg))
        except Exception:
            try:
                await context.bot.send_message(to_tg, T.INVITE_EXPIRED_TO, reply_markup=main_menu(to_tg))
            except Exception:
                pass


async def send_play_invite(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    from_tg,
    to_user_id: int,
    notify=None,
) -> None:
    """Create a pending invite; target must accept within 2 minutes."""

    async def _say(text: str, reply_markup=None) -> None:
        if notify:
            await notify(text)
            return
        await context.bot.send_message(from_tg.id, text, reply_markup=reply_markup)

    with get_session() as session:
        me = user_svc.get_or_create_user(session, from_tg.id, from_tg.username, from_tg.full_name)
        other = session.get(User, to_user_id)
        if not other:
            await _say("این کاربر پیدا نشد.")
            return
        from bot.services import moderation as mod_svc

        blocked = mod_svc.restriction_message(session, me)
        if blocked:
            await _say(blocked)
            return
        if mod_svc.is_restricted(session, other):
            await _say("این کاربر فعلاً در دسترس نیست.")
            return
        if game_engine.active_session_for_user(session, me):
            await _say(T.ALREADY_IN_GAME)
            return
        if game_engine.active_session_for_user(session, other):
            await _say(T.INVITE_IN_GAME)
            return
        if invite_svc.pending_outgoing(session, me):
            await _say(T.INVITE_BUSY)
            return
        if social_svc.either_blocked(session, me, other):
            await _say(T.UP_BLOCKED_ACTION)
            return
        if social_svc.stranger_blocked_by_private(session, me, other):
            await _say(T.ACCOUNT_PRIVATE_BLOCKED)
            return

        inv = invite_svc.create_invite(session, from_user=me, to_user=other)
        invite_id = inv.id
        from bot.services.profile_links import profile_command

        me_profile = profile_command(me.id)
        other_name = user_svc.public_name(other)
        other_tg = other.telegram_id

    # Messages outside session
    try:
        msg_from = await context.bot.send_message(
            from_tg.id,
            T.INVITE_SENT.format(name=other_name),
            reply_markup=kb.play_invite_keyboard(invite_id, for_target=False),
        )
        from_mid = msg_from.message_id
    except Exception:
        from_mid = None
        await _say(T.INVITE_SENT.format(name=other_name))

    try:
        msg_to = await context.bot.send_message(
            other_tg,
            T.INVITE_RECEIVED.format(profile=me_profile),
            reply_markup=kb.play_invite_keyboard(invite_id, for_target=True),
        )
        to_mid = msg_to.message_id
        try:
            await context.bot.send_message(other_tg, T.SET_PRIVATE_HINT)
        except Exception:
            pass
    except Exception:
        logger.exception("failed to deliver play invite to %s", other_tg)
        to_mid = None
        with get_session() as session:
            inv = invite_svc.get_invite(session, invite_id)
            if inv and inv.status == "pending":
                invite_svc.set_status(session, inv, "cancelled")
        await context.bot.send_message(
            from_tg.id,
            "ارسال دعوت به طرف مقابل ناموفق بود.",
            reply_markup=main_menu(from_tg.id),
        )
        return

    with get_session() as session:
        inv = invite_svc.get_invite(session, invite_id)
        if inv:
            inv.from_message_id = from_mid
            inv.to_message_id = to_mid

    _schedule_expire(context, invite_id)
    # Success already sends a dedicated invite message — do not replace the
    # search/results UI via notify (avoids replaying filter steps).


async def on_invite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, action, sid = parts
    invite_id = int(sid)
    tg = update.effective_user

    if action == "block":
        with get_session() as session:
            inv = invite_svc.get_invite(session, invite_id)
            me = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            if not inv or inv.to_user_id != me.id:
                await query.answer(T.INVITE_GONE, show_alert=True)
                return
            other = session.get(User, inv.from_user_id)
            if not other:
                await query.answer(T.UP_GONE, show_alert=True)
                return
            status = social_svc.toggle_block(session, me, other)
            msg = {
                "blocked": T.UP_BLOCKED,
                "unblocked": T.UP_UNBLOCKED,
                "self": T.UP_SELF,
            }.get(status, T.ERROR_GENERIC)
            if status == "blocked" and inv.status == "pending":
                invite_svc.set_status(session, inv, "rejected")
        await query.answer(msg, show_alert=True)
        return

    await query.answer()

    with get_session() as session:
        inv = invite_svc.get_invite(session, invite_id)
        if not inv:
            await query.edit_message_text(T.INVITE_GONE)
            return
        if invite_svc.expire_if_needed(session, inv):
            await query.edit_message_text(T.INVITE_GONE)
            return
        if inv.status != "pending":
            await query.edit_message_text(T.INVITE_GONE)
            return

        me = user_svc.get_or_create_user(session, tg.id, tg.username)
        fu = session.get(User, inv.from_user_id)
        tu = session.get(User, inv.to_user_id)
        from_tg = fu.telegram_id if fu else None
        to_tg = tu.telegram_id if tu else None
        from_name = user_svc.public_name(fu) if fu else "?"
        to_name = user_svc.public_name(tu) if tu else "?"
        from_mid = inv.from_message_id
        to_mid = inv.to_message_id

        if action == "cancel":
            if me.id != inv.from_user_id:
                await query.answer(T.INVITE_GONE, show_alert=True)
                return
            invite_svc.set_status(session, inv, "cancelled")
            _cancel_expire_job(context, invite_id)
            try:
                await query.edit_message_text(T.INVITE_CANCELLED_FROM)
            except Exception:
                pass
            if to_tg:
                try:
                    if to_mid:
                        await context.bot.edit_message_text(
                            T.INVITE_CANCELLED_TO, chat_id=to_tg, message_id=to_mid
                        )
                    else:
                        await context.bot.send_message(to_tg, T.INVITE_CANCELLED_TO)
                except Exception:
                    pass
            return

        if action == "reject":
            if me.id != inv.to_user_id:
                await query.answer(T.INVITE_GONE, show_alert=True)
                return
            invite_svc.set_status(session, inv, "rejected")
            _cancel_expire_job(context, invite_id)
            try:
                await query.edit_message_text(T.INVITE_REJECTED_TO)
            except Exception:
                pass
            if from_tg:
                try:
                    if from_mid:
                        await context.bot.edit_message_text(
                            T.INVITE_REJECTED_FROM.format(name=to_name),
                            chat_id=from_tg,
                            message_id=from_mid,
                        )
                    else:
                        await context.bot.send_message(
                            from_tg,
                            T.INVITE_REJECTED_FROM.format(name=to_name),
                            reply_markup=main_menu(from_tg),
                        )
                except Exception:
                    pass
            return

        if action != "accept":
            return

        if me.id != inv.to_user_id:
            await query.answer(T.INVITE_GONE, show_alert=True)
            return

        if not fu or not tu:
            invite_svc.set_status(session, inv, "cancelled")
            await query.edit_message_text(T.INVITE_GONE)
            return

        if game_engine.active_session_for_user(session, fu) or game_engine.active_session_for_user(
            session, tu
        ):
            invite_svc.set_status(session, inv, "cancelled")
            await query.edit_message_text(T.INVITE_BUSY)
            if from_tg:
                try:
                    await context.bot.send_message(from_tg, T.INVITE_BUSY, reply_markup=main_menu(from_tg))
                except Exception:
                    pass
            return

        invite_svc.set_status(session, inv, "accepted")
        _cancel_expire_job(context, invite_id)

        game = game_engine.create_session(session, "stranger", starter=fu)
        game_engine.add_player(session, game, fu)
        game_engine.add_player(session, game, tu)
        rnd = game_engine.start_two_player(session, game)
        me_picker = rnd.target_user_id == fu.id
        turn = T.CHOOSE_TRUTH_OR_DARE
        turn = f"{game_engine.format_round_info(game.round_number, game.max_rounds)}\n{turn}"
        game_id = game.id
        picker_uid = rnd.target_user_id
        from_hub = (
            T.MATCH_HUB.format(match_body=T.INVITE_ACCEPTED_FROM.format(name=to_name))
            if me_picker
            else T.MATCH_START_WAITER.format(
                match_body=T.INVITE_ACCEPTED_FROM.format(name=to_name), turn=turn
            )
        )
        to_hub = (
            T.MATCH_START_WAITER.format(
                match_body=T.INVITE_ACCEPTED_TO, turn=turn
            )
            if me_picker
            else T.MATCH_HUB.format(match_body=T.INVITE_ACCEPTED_TO)
        )

    try:
        await query.edit_message_text(T.INVITE_ACCEPTED_TO)
    except Exception:
        pass
    if from_tg and from_mid:
        try:
            await context.bot.edit_message_text(
                T.INVITE_ACCEPTED_FROM.format(name=to_name),
                chat_id=from_tg,
                message_id=from_mid,
            )
        except Exception:
            pass

    # Deliver game hubs — glass goes to answerer (picker)
    try:
        mid = await upsert_hub(
            context.bot,
            from_tg,
            from_hub,
            reply_kb=kb.in_game_menu(is_chooser=False),
            replace_keyboard=True,
        )
        glass_id = None
        if me_picker:
            glass_id = await show_td_glass(
                context.bot,
                from_tg,
                session_id=game_id,
                chooser_id=picker_uid,
                turn_text=turn,
            )
        st.set_state(from_tg, game_hub_message_id=mid, game_glass_message_id=glass_id)
    except Exception:
        logger.exception("invite accept hub from failed")

    try:
        mid = await upsert_hub(
            context.bot,
            to_tg,
            to_hub,
            reply_kb=kb.in_game_menu(is_chooser=False),
            replace_keyboard=True,
        )
        glass_id = None
        if not me_picker:
            glass_id = await show_td_glass(
                context.bot,
                to_tg,
                session_id=game_id,
                chooser_id=picker_uid,
                turn_text=turn,
            )
        st.set_state(to_tg, game_hub_message_id=mid, game_glass_message_id=glass_id)
    except Exception:
        logger.exception("invite accept hub to failed")
