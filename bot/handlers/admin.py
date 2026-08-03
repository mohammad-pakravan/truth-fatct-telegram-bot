from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.keyboards import main_menu
from bot.provinces import PROVINCES
from bot.services import admins as admin_svc
from bot.services import membership as mem_svc
from bot.services import reports as report_svc
from bot.texts import fa as T


def _require_admin(session, tg_id: int) -> bool:
    return admin_svc.is_admin(session, tg_id)


async def open_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        if not _require_admin(session, tg.id):
            await update.message.reply_text(T.ADMIN_DENIED, reply_markup=main_menu())
            return
    st.set_state(tg.id, mode="admin", waiting=None)
    await update.message.reply_text(T.ADMIN_HOME, reply_markup=kb.admin_home_keyboard())


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    tg = update.effective_user
    data = query.data

    with get_session() as session:
        if not _require_admin(session, tg.id):
            await query.answer(T.ADMIN_DENIED, show_alert=True)
            return

    await query.answer()

    if data in ("admin:home", "admin:noop"):
        st.set_state(tg.id, mode="admin", waiting=None, admin_ch_province=None)
        await query.edit_message_text(T.ADMIN_HOME, reply_markup=kb.admin_home_keyboard())
        return

    if data == "admin:channels":
        await _show_channels(query)
        return

    if data == "admin:reports":
        await query.edit_message_text(
            T.ADMIN_REPORTS_HOME,
            reply_markup=kb.admin_reports_keyboard("day"),
        )
        return

    if data.startswith("admin:rep:"):
        await _show_report(query, data)
        return

    if data == "admin:ch_add":
        st.set_state(tg.id, mode="admin", waiting=None, admin_ch_province=None)
        await query.edit_message_text(
            T.ADMIN_ADD_CHANNEL_PROVINCE,
            reply_markup=kb.provinces_pick_one("admin:ch_prov"),
        )
        return

    if data.startswith("admin:ch_prov:"):
        idx = int(data.split(":")[2])
        province = PROVINCES[idx]
        st.set_state(tg.id, mode="admin", waiting="admin_ch_add", admin_ch_province=province)
        await query.edit_message_text(T.ADMIN_ADD_CHANNEL_ASK.format(province=province))
        return

    if data.startswith("admin:ch_toggle:"):
        cid = int(data.split(":")[2])
        with get_session() as session:
            from bot.models import SponsoredChannel

            ch = session.get(SponsoredChannel, cid)
            if ch:
                ch.active = not ch.active
        await _show_channels(query)
        return

    if data.startswith("admin:ch_del:"):
        cid = int(data.split(":")[2])
        with get_session() as session:
            mem_svc.delete_channel(session, cid)
        await _show_channels(query)
        return

    if data == "admin:admins":
        await _show_admins(query)
        return

    if data == "admin:ad_add":
        st.set_state(tg.id, mode="admin", waiting="admin_ad_add")
        await query.edit_message_text(T.ADMIN_ADD_ADMIN_ASK)
        return

    if data.startswith("admin:ad_del:"):
        tid = int(data.split(":")[2])
        with get_session() as session:
            admin_svc.remove_admin(session, tid)
        await _show_admins(query)
        return


async def _show_report(query, data: str) -> None:
    parts = data.split(":")
    # admin:rep:overview:day | admin:rep:users | admin:rep:provinces | admin:rep:sponsors:week
    kind = parts[2] if len(parts) > 2 else "overview"
    period = parts[3] if len(parts) > 3 else "day"
    if period not in ("day", "week", "month"):
        period = "day"

    with get_session() as session:
        if kind == "overview":
            body = report_svc.overview_report(session, period)
        elif kind == "users":
            body = report_svc.users_period_report(session)
        elif kind == "provinces":
            body = report_svc.provinces_report(session)
        elif kind == "sponsors":
            body = report_svc.sponsors_report(session, period)
        elif kind == "games":
            body = report_svc.games_report(session, period)
        else:
            body = T.ADMIN_REPORTS_HOME

    if len(body) > 3900:
        body = body[:3900] + "\n\n…"

    await query.edit_message_text(body, reply_markup=kb.admin_reports_keyboard(period))


async def _show_channels(query) -> None:
    with get_session() as session:
        channels = mem_svc.list_all_channels(session)
        if not channels:
            body = T.ADMIN_CHANNELS_EMPTY
        else:
            lines = []
            for ch in channels:
                flag = "✅" if ch.active else "⏸"
                link = ch.invite_link or "—"
                prov = ch.province or "—"
                lines.append(
                    f"{flag} #{ch.id} [{prov}] «{ch.title}»\n"
                    f"   id: `{ch.chat_id}`\n"
                    f"   link: {link}"
                )
            body = T.ADMIN_CHANNELS_HEADER.format(n=len(channels), list="\n".join(lines))
        markup = kb.admin_channels_keyboard(channels)
    try:
        await query.edit_message_text(body, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        await query.edit_message_text(body.replace("`", ""), reply_markup=markup)


async def _show_admins(query) -> None:
    from bot.config import ADMIN_IDS

    with get_session() as session:
        ids = admin_svc.list_admin_ids(session)
        rows_ui: list[tuple[int, str]] = []
        lines = []
        for tid in ids:
            tag = "env" if tid in ADMIN_IDS else "db"
            rows_ui.append((tid, tag))
            label = T.ADMIN_ENV_TAG if tag == "env" else T.ADMIN_DB_TAG
            lines.append(f"• `{tid}` {label}")
        body = T.ADMIN_ADMINS_HEADER.format(n=len(ids), list="\n".join(lines) or "—")
        markup = kb.admin_admins_keyboard(rows_ui)
    try:
        await query.edit_message_text(body, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        await query.edit_message_text(body.replace("`", ""), reply_markup=markup)


async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle admin waiting inputs. Returns True if handled."""
    if not update.message or not update.effective_user or not update.message.text:
        return False
    tg = update.effective_user
    state = st.get(tg.id)
    if state.get("mode") != "admin":
        return False
    waiting = state.get("waiting")
    text = update.message.text.strip()

    with get_session() as session:
        if not _require_admin(session, tg.id):
            return False

    if text == T.BTN_CANCEL or text == T.BTN_BACK:
        st.set_state(tg.id, mode="admin", waiting=None, admin_ch_province=None)
        await update.message.reply_text(T.ADMIN_CANCELLED, reply_markup=kb.admin_home_keyboard())
        return True

    if waiting == "admin_ch_add":
        province = state.get("admin_ch_province")
        if not province:
            await update.message.reply_text(
                T.ADMIN_CHANNEL_NEED_PROVINCE,
                reply_markup=kb.admin_home_keyboard(),
            )
            st.set_state(tg.id, waiting=None)
            return True

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            await update.message.reply_text(T.ADMIN_CHANNEL_BAD_ID)
            return True
        id_part = lines[0].replace(" ", "")
        try:
            chat_id = int(id_part)
        except ValueError:
            await update.message.reply_text(T.ADMIN_CHANNEL_BAD_ID)
            return True
        invite = lines[1] if len(lines) > 1 else None
        title = ""
        try:
            chat = await context.bot.get_chat(chat_id)
            title = chat.title or getattr(chat, "username", None) or ""
            if not invite:
                invite = getattr(chat, "invite_link", None)
            if not invite:
                try:
                    invite = await context.bot.export_chat_invite_link(chat_id)
                except Exception:
                    invite = None
        except Exception:
            title = ""
        if not title:
            title = "کانال اسپانسری"
        with get_session() as session:
            row = mem_svc.add_channel(
                session,
                chat_id,
                province=province,
                title=title,
                invite_link=invite,
                created_by=tg.id,
            )
            title = row.title
            cid = row.chat_id
            prov = row.province
        st.set_state(tg.id, waiting=None, admin_ch_province=None)
        await update.message.reply_text(
            T.ADMIN_CHANNEL_ADDED.format(title=title, province=prov, chat_id=cid),
            reply_markup=kb.admin_home_keyboard(),
        )
        return True

    if waiting == "admin_ad_add":
        raw = text.replace(" ", "")
        if not raw.isdigit():
            await update.message.reply_text(T.ADMIN_ADD_ADMIN_ASK)
            return True
        tid = int(raw)
        with get_session() as session:
            _, status = admin_svc.add_admin(session, tid, added_by=tg.id)
        st.set_state(tg.id, waiting=None)
        msg = {
            "added": T.ADMIN_ADMIN_ADDED.format(tid=tid),
            "exists": T.ADMIN_ADMIN_EXISTS,
            "env_exists": T.ADMIN_ADMIN_ENV,
        }.get(status, T.ERROR_GENERIC)
        await update.message.reply_text(msg, reply_markup=kb.admin_home_keyboard())
        return True

    return False
