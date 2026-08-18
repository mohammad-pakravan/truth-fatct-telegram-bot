from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.config import BROADCAST_RATE_PER_SECOND
from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import User
from bot.provinces import PROVINCES
from bot.services import admins as admin_svc
from bot.services import broadcast as bc_svc
from bot.services import membership as mem_svc
from bot.services import moderation as mod_svc
from bot.services import reports as report_svc
from bot.services import matchmaker
from bot.services import game_engine
from bot.services import questions as qbank_svc
from bot.services import search as search_svc
from bot.services.presence import format_last_seen, online_emoji
from bot.texts import fa as T

logger = logging.getLogger(__name__)


def _require_admin(session, tg_id: int) -> bool:
    return admin_svc.is_admin(session, tg_id)


def _all_telegram_ids() -> list[int]:
    with get_session() as session:
        rows = session.query(User.telegram_id).order_by(User.id.asc()).all()
        return [int(r[0]) for r in rows if r[0]]


async def open_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        if not _require_admin(session, tg.id):
            await update.message.reply_text(T.ADMIN_DENIED, reply_markup=main_menu(tg.id))
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
        st.set_state(
            tg.id,
            mode="admin",
            waiting=None,
            admin_ch_province=None,
            admin_bc_target=None,
            admin_bc_from=None,
            admin_bc_mid=None,
            admin_qbank_bucket=None,
        )
        await query.edit_message_text(T.ADMIN_HOME, reply_markup=kb.admin_home_keyboard())
        return

    if data == "admin:broadcast":
        st.set_state(
            tg.id,
            mode="admin",
            waiting=None,
            admin_bc_target=None,
            admin_bc_from=None,
            admin_bc_mid=None,
        )
        await query.edit_message_text(T.ADMIN_BC_MENU, reply_markup=kb.admin_broadcast_keyboard())
        return

    if data == "admin:bc:all":
        if bc_svc.is_busy():
            await query.edit_message_text(T.ADMIN_BC_BUSY, reply_markup=kb.admin_broadcast_keyboard())
            return
        st.set_state(tg.id, mode="admin", waiting="admin_bc_msg", admin_bc_target="all")
        await query.edit_message_text(T.ADMIN_BC_ASK_MSG)
        return

    if data == "admin:bc:one":
        if bc_svc.is_busy():
            await query.edit_message_text(T.ADMIN_BC_BUSY, reply_markup=kb.admin_broadcast_keyboard())
            return
        st.set_state(tg.id, mode="admin", waiting="admin_bc_target", admin_bc_target=None)
        await query.edit_message_text(T.ADMIN_BC_ASK_TARGET)
        return

    if data == "admin:bc:go":
        await _start_broadcast(query, context, tg.id)
        return

    if data == "admin:usearch" or data.startswith("admin:usearch:"):
        await _user_search_callbacks(query, context, tg, data)
        return

    if data == "admin:mod" or data.startswith("admin:mod:"):
        await _moderation_callbacks(query, context, tg, data)
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

    if data == "admin:qbank" or data.startswith("admin:qbank:"):
        await _qbank_callbacks(query, tg, data)
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


async def _qbank_callbacks(query, tg, data: str) -> None:
    if data == "admin:qbank":
        st.set_state(tg.id, mode="admin", waiting=None, admin_qbank_bucket=None)
        with get_session() as session:
            counts = qbank_svc.counts_summary(session)
        await query.edit_message_text(
            T.ADMIN_QBANK_MENU,
            reply_markup=kb.admin_question_bank_keyboard(counts),
        )
        return

    if data == "admin:qbank:userq":
        with get_session() as session:
            items = qbank_svc.list_user_submitted(session, limit=25)
        if not items:
            await query.edit_message_text(
                T.ADMIN_USER_Q_EMPTY,
                reply_markup=kb.admin_user_questions_keyboard([]),
            )
            return
        rows_ui = []
        lines = []
        for i, item in enumerate(items, 1):
            kind = "حقیقت" if item.kind == "truth" else "جرئت"
            label = f"{i}. {kind} — {(item.text or '')[:36]}"
            rows_ui.append((item.id, label))
            lines.append(label)
        await query.edit_message_text(
            T.ADMIN_USER_Q_LIST.format(n=len(items), list="\n".join(lines)),
            reply_markup=kb.admin_user_questions_keyboard(rows_ui),
        )
        return

    if data.startswith("admin:qbank:uq:"):
        qid = int(data.split(":")[3])
        with get_session() as session:
            item = qbank_svc.get_user_submitted(session, qid)
            if not item:
                await query.edit_message_text(
                    T.ADMIN_USER_Q_EMPTY,
                    reply_markup=kb.admin_user_questions_keyboard([]),
                )
                return
            body = T.ADMIN_USER_Q_DETAIL.format(
                id=item.id,
                kind="حقیقت" if item.kind == "truth" else "جرئت",
                bucket=qbank_svc.BUCKET_LABELS.get(item.suggested_bucket or "", item.suggested_bucket or "نامشخص"),
                submitter=f"#{item.submitter_user_id}" if item.submitter_user_id else "نامشخص",
                text=item.text,
            )
        await query.edit_message_text(
            body,
            reply_markup=kb.admin_user_question_detail_keyboard(
                qid, added=bool(item.added_to_bank)
            ),
        )
        return

    if data.startswith("admin:qbank:uqadd:"):
        qid = int(data.split(":")[3])
        with get_session() as session:
            row, _item = qbank_svc.add_submitted_to_bank(
                session, submitted_id=qid, admin_tg=tg.id
            )
            if not row:
                await query.answer("قبلاً اضافه شده یا پیدا نشد.", show_alert=True)
                return
            label = qbank_svc.BUCKET_LABELS.get(row.added_bucket or "", row.added_bucket or "نامشخص")
        await query.edit_message_text(
            T.ADMIN_USER_Q_ADDED.format(label=label),
            reply_markup=kb.admin_user_question_detail_keyboard(qid, added=True),
        )
        return

    parts = data.split(":")
    # admin:qbank:b:female | admin:qbank:add:female | list | clear
    if len(parts) < 4:
        return
    action, bucket = parts[2], parts[3]
    if bucket not in qbank_svc.BUCKETS:
        return

    label = qbank_svc.BUCKET_LABELS[bucket]

    if action == "b":
        st.set_state(tg.id, mode="admin", waiting=None, admin_qbank_bucket=bucket)
        with get_session() as session:
            n = qbank_svc.count_bucket(session, bucket)
        await query.edit_message_text(
            T.ADMIN_QBANK_BUCKET.format(label=label, n=n),
            reply_markup=kb.admin_question_bucket_keyboard(bucket),
        )
        return

    if action == "add":
        st.set_state(tg.id, mode="admin", waiting="admin_qbank_add", admin_qbank_bucket=bucket)
        await query.edit_message_text(T.ADMIN_QBANK_ASK.format(label=label))
        return

    if action == "list":
        with get_session() as session:
            items = qbank_svc.list_bucket(session, bucket, limit=25)
            n = qbank_svc.count_bucket(session, bucket)
        if not items:
            body = T.ADMIN_QBANK_LIST_EMPTY
        else:
            numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(items, 1))
            body = T.ADMIN_QBANK_LIST.format(label=label, n=n, list=numbered)
            if len(body) > 3800:
                body = body[:3800] + "…"
        await query.edit_message_text(
            body,
            reply_markup=kb.admin_question_bucket_keyboard(bucket),
        )
        return

    if action == "clear":
        with get_session() as session:
            n = qbank_svc.clear_bucket(session, bucket)
        await query.edit_message_text(
            T.ADMIN_QBANK_CLEARED.format(n=n, label=label),
            reply_markup=kb.admin_question_bucket_keyboard(bucket),
        )
        return


async def _resolve_targets(target) -> list[int]:
    if target == "all" or target is None:
        return _all_telegram_ids()
    try:
        return [int(target)]
    except (TypeError, ValueError):
        return []


async def _start_broadcast(query, context: ContextTypes.DEFAULT_TYPE, admin_tg: int) -> None:
    state = st.get(admin_tg)
    from_chat = state.get("admin_bc_from")
    mid = state.get("admin_bc_mid")
    target = state.get("admin_bc_target")
    if not from_chat or not mid:
        await query.edit_message_text(T.ADMIN_BC_NO_PENDING, reply_markup=kb.admin_home_keyboard())
        return
    if bc_svc.is_busy():
        await query.edit_message_text(T.ADMIN_BC_BUSY, reply_markup=kb.admin_home_keyboard())
        return

    user_ids = await _resolve_targets(target)
    if not user_ids:
        await query.edit_message_text(T.ADMIN_BC_EMPTY, reply_markup=kb.admin_home_keyboard())
        return

    st.set_state(
        admin_tg,
        waiting=None,
        admin_bc_from=None,
        admin_bc_mid=None,
        admin_bc_target=None,
    )
    await query.edit_message_text(T.ADMIN_BC_STARTED)

    status_chat = query.message.chat_id
    status_mid = query.message.message_id

    async def on_progress(done: int, total: int, ok: int, bad: int) -> None:
        try:
            await context.bot.edit_message_text(
                T.ADMIN_BC_PROGRESS.format(done=done, total=total, ok=ok, bad=bad),
                chat_id=status_chat,
                message_id=status_mid,
            )
        except Exception:
            pass

    async def runner() -> None:
        try:
            result = await bc_svc.copy_to_users(
                context.bot,
                from_chat_id=int(from_chat),
                message_id=int(mid),
                user_ids=user_ids,
                on_progress=on_progress,
            )
            await context.bot.edit_message_text(
                T.ADMIN_BC_DONE.format(**result),
                chat_id=status_chat,
                message_id=status_mid,
                reply_markup=kb.admin_home_keyboard(),
            )
        except RuntimeError:
            await context.bot.edit_message_text(
                T.ADMIN_BC_BUSY,
                chat_id=status_chat,
                message_id=status_mid,
                reply_markup=kb.admin_home_keyboard(),
            )
        except Exception:
            logger.exception("broadcast runner failed")
            try:
                await context.bot.edit_message_text(
                    T.ERROR_GENERIC,
                    chat_id=status_chat,
                    message_id=status_mid,
                    reply_markup=kb.admin_home_keyboard(),
                )
            except Exception:
                pass

    context.application.create_task(runner())


async def _show_report(query, data: str) -> None:
    parts = data.split(":")
    # admin:rep:overview:day | admin:rep:users | admin:rep:provinces | admin:rep:sponsors:week
    kind = parts[2] if len(parts) > 2 else "overview"
    period = parts[3] if len(parts) > 3 else "day"
    if period not in ("minute", "hour", "day", "week", "month"):
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


async def _confirm_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Store admin message for copy_message and ask confirmation."""
    if not update.message or not update.effective_user:
        return False
    tg = update.effective_user
    state = st.get(tg.id)
    if state.get("mode") != "admin" or state.get("waiting") != "admin_bc_msg":
        return False

    with get_session() as session:
        if not _require_admin(session, tg.id):
            return False

    msg = update.message
    # Albums: Telegram sends multiple updates; we can only copy one message_id
    if getattr(msg, "media_group_id", None):
        await msg.reply_text(
            "آلبوم چندتایی پشتیبانی نمی‌شه — فقط یک عکس/فایل جدا بفرست."
        )
        return True

    target = state.get("admin_bc_target")
    user_ids = await _resolve_targets(target)
    if not user_ids:
        await msg.reply_text(T.ADMIN_BC_EMPTY, reply_markup=kb.admin_home_keyboard())
        st.set_state(tg.id, waiting=None, admin_bc_target=None)
        return True

    kind = _broadcast_kind_label(msg)
    st.set_state(
        tg.id,
        waiting="admin_bc_confirm",
        admin_bc_from=update.effective_chat.id,
        admin_bc_mid=msg.message_id,
    )
    await msg.reply_text(
        T.ADMIN_BC_CONFIRM.format(
            kind=kind, n=len(user_ids), rate=int(BROADCAST_RATE_PER_SECOND)
        ),
        reply_markup=kb.admin_broadcast_confirm_keyboard(),
    )
    return True


def _broadcast_kind_label(message) -> str:
    if message.photo:
        return T.ADMIN_BC_KIND_PHOTO
    if message.document:
        return T.ADMIN_BC_KIND_DOCUMENT
    if message.video:
        return T.ADMIN_BC_KIND_VIDEO
    if message.voice:
        return T.ADMIN_BC_KIND_VOICE
    if message.video_note:
        return T.ADMIN_BC_KIND_VIDEO_NOTE
    if message.audio:
        return T.ADMIN_BC_KIND_AUDIO
    if message.animation:
        return T.ADMIN_BC_KIND_ANIMATION
    if message.sticker:
        return T.ADMIN_BC_KIND_STICKER
    if message.text:
        return T.ADMIN_BC_KIND_TEXT
    return T.ADMIN_BC_KIND_OTHER


async def admin_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Accept photo / file / video / … while admin is composing a broadcast."""
    return await _confirm_broadcast_message(update, context)


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
        st.set_state(
            tg.id,
            mode="admin",
            waiting=None,
            admin_ch_province=None,
            admin_bc_target=None,
            admin_bc_from=None,
            admin_bc_mid=None,
            admin_qbank_bucket=None,
        )
        await update.message.reply_text(T.ADMIN_CANCELLED, reply_markup=kb.admin_home_keyboard())
        return True

    if waiting == "admin_qbank_add":
        bucket = state.get("admin_qbank_bucket")
        if not bucket or bucket not in qbank_svc.BUCKETS:
            st.set_state(tg.id, waiting=None, admin_qbank_bucket=None)
            await update.message.reply_text(T.ERROR_GENERIC, reply_markup=kb.admin_home_keyboard())
            return True
        questions = qbank_svc.parse_question_list(text)
        if not questions:
            await update.message.reply_text(T.ADMIN_QBANK_EMPTY_PARSE)
            return True
        label = qbank_svc.BUCKET_LABELS[bucket]
        with get_session() as session:
            added = qbank_svc.add_questions(
                session,
                bucket=bucket,
                questions=questions,
                kind="any",
                created_by=tg.id,
            )
            total = qbank_svc.count_bucket(session, bucket)
        st.set_state(tg.id, waiting=None)
        await update.message.reply_text(
            T.ADMIN_QBANK_ADDED.format(added=added, label=label, total=total),
            reply_markup=kb.admin_question_bucket_keyboard(bucket),
        )
        return True

    if waiting == "admin_bc_target":
        raw = text.replace(" ", "")
        if not raw.isdigit():
            await update.message.reply_text(T.ADMIN_BC_BAD_TARGET)
            return True
        tid = int(raw)
        with get_session() as session:
            exists = session.query(User.id).filter(User.telegram_id == tid).first()
        if not exists:
            await update.message.reply_text(T.ADMIN_BC_USER_NOT_FOUND)
            return True
        st.set_state(tg.id, waiting="admin_bc_msg", admin_bc_target=tid)
        await update.message.reply_text(T.ADMIN_BC_ASK_MSG_ONE.format(tid=tid))
        return True

    if waiting == "admin_bc_msg":
        return await _confirm_broadcast_message(update, context)

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

    if waiting == "admin_mod_ban_reason":
        hours = state.get("admin_mod_ban_hours")
        report_id = state.get("admin_mod_report_id")
        target_user_id = state.get("admin_mod_user_id")
        reason = None if text in ("بدون دلیل", "-", "—") else text
        st.set_state(
            tg.id,
            waiting=None,
            admin_mod_ban_hours=None,
            admin_mod_report_id=None,
            admin_mod_user_id=None,
        )
        if report_id is not None:
            await _apply_ban_from_report(
                context,
                admin_tg=tg.id,
                report_id=int(report_id),
                hours=hours,
                reason=reason,
                reply_to=update.message,
            )
            return True
        if target_user_id is not None:
            await _apply_ban_to_user(
                context,
                admin_tg=tg.id,
                user_id=int(target_user_id),
                hours=hours,
                reason=reason,
                reply_to=update.message,
            )
            return True
        await update.message.reply_text(T.ERROR_GENERIC, reply_markup=kb.admin_home_keyboard())
        return True

    if waiting == "admin_user_search":
        q = text.strip()
        with get_session() as session:
            rows = search_svc.admin_search_users(session, q, limit=20)
            if not rows:
                await update.message.reply_text(
                    T.ADMIN_USER_SEARCH_EMPTY, reply_markup=kb.admin_home_keyboard()
                )
                return True
            lines = []
            ids = []
            for u in rows:
                ids.append(u.id)
                uname = f"@{u.username}" if u.username else "—"
                lines.append(
                    f"{online_emoji(u.last_active_at)} #{u.id} tg:`{u.telegram_id}` {uname}\n"
                    f"   {u.display_name or '—'} · {u.city or '—'} · {u.province or '—'}\n"
                    f"   {format_last_seen(u.last_active_at)} · ❤️ {int(u.likes_count or 0)}"
                )
            body = T.ADMIN_USER_SEARCH_HEADER.format(n=len(rows), list="\n".join(lines))
            markup = kb.admin_user_search_results_keyboard(ids)
        st.set_state(tg.id, waiting=None)
        try:
            await update.message.reply_text(body, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(body.replace("`", ""), reply_markup=markup)
        return True

    return False


_BAN_HOURS = {
    "1h": 1,
    "6h": 6,
    "24h": 24,
    "7d": 24 * 7,
    "30d": 24 * 30,
    "perm": None,
}


async def _moderation_callbacks(query, context, tg, data: str) -> None:
    if data == "admin:mod":
        with get_session() as session:
            open_n = mod_svc.count_open_reports(session)
            ban_n = len(mod_svc.list_active_restrictions(session))
        await query.edit_message_text(
            T.ADMIN_MOD_HOME.format(open_n=open_n, ban_n=ban_n),
            reply_markup=kb.admin_mod_home_keyboard(),
        )
        return

    if data == "admin:mod:open":
        await _show_mod_reports(query)
        return

    if data == "admin:mod:bans":
        await _show_mod_bans(query)
        return

    if data.startswith("admin:mod:r:"):
        rid = int(data.split(":")[3])
        with get_session() as session:
            rep = mod_svc.get_report(session, rid)
            if not rep:
                await query.edit_message_text(
                    T.ADMIN_MOD_EMPTY_REPORTS, reply_markup=kb.admin_mod_home_keyboard()
                )
                return
            body = mod_svc.format_report_detail(session, rep)
        try:
            await query.edit_message_text(
                body,
                reply_markup=kb.admin_mod_report_actions_keyboard(rid),
                parse_mode="Markdown",
            )
        except Exception:
            await query.edit_message_text(
                body.replace("`", ""),
                reply_markup=kb.admin_mod_report_actions_keyboard(rid),
            )
        return

    if data.startswith("admin:mod:dismiss:"):
        rid = int(data.split(":")[3])
        with get_session() as session:
            rep = mod_svc.get_report(session, rid)
            if rep:
                mod_svc.set_report_status(session, rep, "dismissed", admin_tg=tg.id)
        await query.edit_message_text(
            T.ADMIN_MOD_DISMISSED, reply_markup=kb.admin_mod_home_keyboard()
        )
        return

    if data.startswith("admin:mod:ban:"):
        parts = data.split(":")
        rid = int(parts[3])
        preset = parts[4] if len(parts) > 4 else "24h"
        hours = _BAN_HOURS.get(preset, 24)
        st.set_state(
            tg.id,
            mode="admin",
            waiting="admin_mod_ban_reason",
            admin_mod_report_id=rid,
            admin_mod_ban_hours=hours,
        )
        await query.edit_message_text(T.ADMIN_MOD_ASK_REASON)
        return

    if data.startswith("admin:mod:lift:"):
        rid = int(data.split(":")[3])
        with get_session() as session:
            mod_svc.lift_restriction(session, rid)
        await query.edit_message_text(T.ADMIN_MOD_LIFTED, reply_markup=kb.admin_mod_home_keyboard())
        return

    if data.startswith("admin:mod:b:"):
        await _show_mod_bans(query)
        return


async def _show_mod_reports(query) -> None:
    with get_session() as session:
        reports = mod_svc.list_open_reports(session, limit=20)
        if not reports:
            await query.edit_message_text(
                T.ADMIN_MOD_EMPTY_REPORTS, reply_markup=kb.admin_mod_home_keyboard()
            )
            return
        lines = []
        for r in reports:
            reported = r.reported
            tg_id = reported.telegram_id if reported else "?"
            lines.append(
                f"#{r.id} → tg:{tg_id} · {mod_svc.reason_label(r.reason_code)}"
            )
        body = T.ADMIN_MOD_REPORTS_HEADER.format(n=len(reports), list="\n".join(lines))
        markup = kb.admin_mod_reports_keyboard(reports)
    await query.edit_message_text(body, reply_markup=markup)


async def _show_mod_bans(query) -> None:
    with get_session() as session:
        rows = mod_svc.list_active_restrictions(session, limit=30)
        if not rows:
            await query.edit_message_text(
                T.ADMIN_MOD_EMPTY_BANS, reply_markup=kb.admin_mod_home_keyboard()
            )
            return
        lines = []
        buttons: list[tuple[int, str]] = []
        for row in rows:
            user = session.get(User, row.user_id)
            lines.append(mod_svc.format_restriction_line(row, user))
            label = f"#{row.id} tg:{user.telegram_id if user else '?'}"
            buttons.append((row.id, label))
        body = T.ADMIN_MOD_BANS_HEADER.format(n=len(rows), list="\n".join(lines))
        markup = kb.admin_mod_bans_keyboard(buttons)
    try:
        await query.edit_message_text(body, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        await query.edit_message_text(body.replace("`", ""), reply_markup=markup)


async def _apply_ban_from_report(
    context,
    *,
    admin_tg: int,
    report_id: int,
    hours: int | None,
    reason: str | None,
    reply_to=None,
) -> None:
    notify_tg = None
    detail = ""
    with get_session() as session:
        rep = mod_svc.get_report(session, report_id)
        if not rep:
            if reply_to:
                await reply_to.reply_text(T.ERROR_GENERIC, reply_markup=kb.admin_home_keyboard())
            return
        user = session.get(User, rep.reported_id)
        if not user:
            if reply_to:
                await reply_to.reply_text(T.ERROR_GENERIC, reply_markup=kb.admin_home_keyboard())
            return
        ban_reason = reason or mod_svc.reason_label(rep.reason_code)
        mod_svc.apply_restriction(
            session,
            user,
            hours=hours,
            reason=ban_reason,
            admin_tg=admin_tg,
            report_id=report_id,
        )
        matchmaker.cancel(session, user)
        game = game_engine.active_session_for_user(session, user)
        if game and game.status in ("playing", "guessing"):
            players = game_engine.get_players(session, game)
            game_engine.finish_game(session, game)
            for p in players:
                try:
                    peer = p.user.telegram_id if p.user else None
                    if peer:
                        await context.bot.send_message(
                            peer,
                            T.GAME_ENDED_BY_USER,
                            reply_markup=kb.main_menu(peer),
                        )
                except Exception:
                    pass
        notify_tg = user.telegram_id
        detail = mod_svc.restriction_message(session, user) or ""

    if reply_to:
        await reply_to.reply_text(T.ADMIN_MOD_RESTRICTED, reply_markup=kb.admin_home_keyboard())
    if notify_tg:
        try:
            await context.bot.send_message(
                notify_tg,
                T.ADMIN_MOD_USER_NOTIFIED.format(detail=detail),
                reply_markup=kb.main_menu(notify_tg),
            )
        except Exception:
            pass


async def _user_search_callbacks(query, context, tg, data: str) -> None:
    if data == "admin:usearch":
        st.set_state(tg.id, mode="admin", waiting="admin_user_search")
        await query.edit_message_text(T.ADMIN_USER_SEARCH_ASK)
        return

    if data.startswith("admin:usearch:u:"):
        uid = int(data.split(":")[3])
        with get_session() as session:
            user = session.get(User, uid)
            if not user:
                await query.edit_message_text(
                    T.ADMIN_USER_SEARCH_EMPTY, reply_markup=kb.admin_home_keyboard()
                )
                return
            uname = f"@{user.username}" if user.username else "—"
            body = (
                f"{online_emoji(user.last_active_at)} کاربر #{user.id}\n"
                f"tg: `{user.telegram_id}` {uname}\n"
                f"نام: {user.display_name or '—'}\n"
                f"لقب: {user.nickname or '—'}\n"
                f"جنسیت: {user.gender or '—'}\n"
                f"سن: {user.age or '—'}\n"
                f"استان: {user.province or '—'}\n"
                f"شهر: {user.city or '—'}\n"
                f"❤️ لایک: {int(user.likes_count or 0)}\n"
                f"{format_last_seen(user.last_active_at)}\n"
                f"گزارش‌ها علیه: {mod_svc.count_reports_against(session, user.id)}"
            )
            markup = kb.admin_user_detail_keyboard(user.id)
        try:
            await query.edit_message_text(body, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            await query.edit_message_text(body.replace("`", ""), reply_markup=markup)
        return

    if data.startswith("admin:usearch:ban:"):
        parts = data.split(":")
        uid = int(parts[3])
        preset = parts[4] if len(parts) > 4 else "24h"
        hours = _BAN_HOURS.get(preset, 24)
        st.set_state(
            tg.id,
            mode="admin",
            waiting="admin_mod_ban_reason",
            admin_mod_user_id=uid,
            admin_mod_report_id=None,
            admin_mod_ban_hours=hours,
        )
        await query.edit_message_text(T.ADMIN_MOD_ASK_REASON)
        return


async def _apply_ban_to_user(
    context,
    *,
    admin_tg: int,
    user_id: int,
    hours: int | None,
    reason: str | None,
    reply_to=None,
) -> None:
    notify_tg = None
    detail = ""
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            if reply_to:
                await reply_to.reply_text(T.ERROR_GENERIC, reply_markup=kb.admin_home_keyboard())
            return
        mod_svc.apply_restriction(
            session,
            user,
            hours=hours,
            reason=(reason or "محدودیت ادمین").strip(),
            admin_tg=admin_tg,
            report_id=None,
        )
        matchmaker.cancel(session, user)
        game = game_engine.active_session_for_user(session, user)
        if game and game.status in ("playing", "guessing"):
            players = game_engine.get_players(session, game)
            game_engine.finish_game(session, game)
            for p in players:
                try:
                    peer = p.user.telegram_id if p.user else None
                    if peer:
                        await context.bot.send_message(
                            peer,
                            T.GAME_ENDED_BY_USER,
                            reply_markup=kb.main_menu(peer),
                        )
                except Exception:
                    pass
        notify_tg = user.telegram_id
        detail = mod_svc.restriction_message(session, user) or ""

    if reply_to:
        await reply_to.reply_text(T.ADMIN_MOD_RESTRICTED, reply_markup=kb.admin_home_keyboard())
    if notify_tg:
        try:
            await context.bot.send_message(
                notify_tg,
                T.ADMIN_MOD_USER_NOTIFIED.format(detail=detail),
                reply_markup=kb.main_menu(notify_tg),
            )
        except Exception:
            pass
