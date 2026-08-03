from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.models import SponsoredChannel
from bot.services import membership as mem_svc
from bot.services import reports as report_svc
from bot.texts import fa as T


async def maybe_prompt_sponsor(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    query,
    provinces: list[str] | str,
    continue_to: str,
) -> bool:
    """
    If active sponsored channels exist for the given province(s), show join UI.
    provinces: one province name or a list (e.g. advanced partner provinces).
    continue_to: 'wizard_city' | 'profile_done' | 'advanced_age'
    """
    if isinstance(provinces, str):
        prov_list = [provinces] if provinces else []
    else:
        prov_list = [p for p in provinces if p]

    with get_session() as session:
        channels = mem_svc.list_active_for_provinces(session, prov_list)
        if channels:
            await mem_svc.refresh_channel_meta(context, session, channels)
        snap = mem_svc.snapshot_channels(channels)

    if not snap:
        return False

    tg_id = query.from_user.id
    label = "، ".join(prov_list)
    st.set_state(
        tg_id,
        waiting="sponsor",
        sponsor_continue=continue_to,
        sponsor_provinces=prov_list,
        sponsor_province=label,
    )
    mode = st.get(tg_id).get("mode")
    if mode == "wizard":
        st.set_state(tg_id, wizard_step="sponsor")

    text = T.SPONSOR_ASK.format(province=label)
    try:
        if continue_to == "advanced_age":
            await query.edit_message_text(
                f"استان‌ها ثبت شد 🗺\n\n{text}",
                reply_markup=kb.sponsor_join_keyboard(snap),
            )
            return True
        await query.edit_message_text(f"استان «{label}» ثبت شد 🗺✨")
    except Exception:
        pass
    await query.message.reply_text(text, reply_markup=kb.sponsor_join_keyboard(snap))
    return True


async def membership_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    tg = update.effective_user
    data = query.data

    if data == "mem_noop":
        await query.answer(T.SPONSOR_NO_LINK, show_alert=True)
        return

    if data.startswith("mem_join:"):
        channel_id = int(data.split(":")[1])
        with get_session() as session:
            ch = session.get(SponsoredChannel, channel_id)
            if not ch:
                await query.answer("کانال پیدا نشد.", show_alert=True)
                return
            report_svc.log_event(
                session,
                report_svc.EVENT_JOIN_CLICK,
                telegram_id=tg.id,
                channel_id=ch.id,
                province=ch.province,
            )
            title = mem_svc.channel_label(ch)
            link = ch.invite_link
        if not link:
            await query.answer(T.SPONSOR_NO_LINK, show_alert=True)
            return
        await query.answer("لینک برات آماده شد 👇")
        await query.message.reply_text(
            T.SPONSOR_OPEN_LINK.format(title=title),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(T.SPONSOR_BTN_OPEN, url=link)]]
            ),
        )
        return

    if data != "mem_check":
        return

    await query.answer("دارم چک می‌کنم… 🔍")
    prov_list = st.get(tg.id).get("sponsor_provinces") or []
    if not prov_list:
        single = st.get(tg.id).get("sponsor_province")
        if single:
            prov_list = [p.strip() for p in str(single).split("،") if p.strip()]

    with get_session() as session:
        channels = mem_svc.list_active_for_provinces(session, prov_list)
        if channels:
            await mem_svc.refresh_channel_meta(context, session, channels)
        report_svc.log_event(
            session,
            report_svc.EVENT_CHECK,
            telegram_id=tg.id,
            province=prov_list[0] if len(prov_list) == 1 else None,
        )
        missing = await mem_svc.missing_channels(context, session, tg.id, prov_list)
        missing_lines = [
            f"🔸 «{mem_svc.channel_label(c)}»"
            + (f" — {c.province}" if c.province else "")
            for c in missing
        ]
        all_snap = mem_svc.snapshot_channels(channels)

        if not missing:
            for ch in channels:
                report_svc.log_event(
                    session,
                    report_svc.EVENT_VERIFIED,
                    telegram_id=tg.id,
                    channel_id=ch.id,
                    province=ch.province,
                )

    if missing_lines:
        await query.edit_message_text(
            T.SPONSOR_MISSING.format(missing="\n".join(missing_lines)),
            reply_markup=kb.sponsor_join_keyboard(all_snap),
        )
        return

    continue_to = st.get(tg.id).get("sponsor_continue") or "wizard_city"
    province_label = st.get(tg.id).get("sponsor_province") or "، ".join(prov_list)
    st.set_state(tg.id, waiting=None, sponsor_continue=None, sponsor_provinces=None)

    await query.edit_message_text(T.SPONSOR_OK)

    if continue_to == "wizard_city":
        st.set_state(tg.id, mode="wizard", wizard_step="city")
        await query.message.reply_text(
            T.WIZARD_ASK_CITY,
            reply_markup=kb.wizard_cancel_menu(),
        )
        return

    if continue_to == "advanced_age":
        prefs = st.get(tg.id).get("adv") or {}
        st.set_state(tg.id, mode="advanced", wait="age_min", adv=prefs)
        from bot.handlers.advanced import _summary_message

        await query.message.reply_text(
            _summary_message(prefs, T.ADV_AGE_MIN_ASK),
            reply_markup=kb.age_min_keyboard(),
        )
        return

    await query.message.reply_text(
        f"استان «{province_label}» اوکیه و عضویتت هم تأیید شد 🎉"
        if province_label
        else "عضویتت تأیید شد 🎉"
    )
