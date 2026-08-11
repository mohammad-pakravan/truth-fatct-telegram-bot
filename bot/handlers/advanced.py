from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import User
from bot.provinces import PROVINCES
from bot.services import game_engine
from bot.services import search as search_svc
from bot.services import users as user_svc
from bot.texts import fa as T


def _prefs(tg_id: int) -> dict:
    return st.get(tg_id).setdefault("adv", {})


def _summary_message(prefs: dict, question: str) -> str:
    return f"{search_svc.filters_summary(prefs)}\n\n{question}"


async def open_advanced(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    tg = update.effective_user
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if not user_svc.profile_complete(user):
            await update.message.reply_text(T.PROFILE_INCOMPLETE, reply_markup=main_menu(tg.id))
            return
        if game_engine.active_session_for_user(session, user):
            from bot.handlers import gameplay

            await gameplay.resume_active_game_keyboard(
                context, tg.id, reply_to=update.message
            )
            return
    st.set_state(tg.id, mode="advanced", wait="partner_gender", adv={})
    await update.message.reply_text(
        T.ADVANCED_PARTNER_ASK,
        reply_markup=kb.partner_gender_inline("adv_partner"),
    )


async def advanced_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    tg = update.effective_user
    data = query.data
    prefs = _prefs(tg.id)

    # --- gender ---
    if data.startswith("adv_partner:"):
        prefs["gender"] = data.split(":")[1]
        prefs["provinces"] = []
        st.set_state(tg.id, mode="advanced", wait="province", adv=prefs)
        await query.answer()
        await query.edit_message_text(
            _summary_message(prefs, T.ADV_PROVINCE_ASK),
            reply_markup=kb.provinces_keyboard(set()),
        )
        return

    # --- provinces ---
    if data.startswith("adv_prov:"):
        idx = int(data.split(":")[1])
        name = PROVINCES[idx]
        selected = set(prefs.get("provinces") or [])
        if name in selected:
            selected.remove(name)
        else:
            selected.add(name)
        prefs["provinces"] = sorted(selected, key=lambda p: PROVINCES.index(p))
        st.set_state(tg.id, adv=prefs)
        await query.answer()
        await query.edit_message_text(
            _summary_message(prefs, T.ADV_PROVINCE_ASK),
            reply_markup=kb.provinces_keyboard(selected),
        )
        return

    if data == "adv_prov_all":
        prefs["provinces"] = list(PROVINCES)
        st.set_state(tg.id, adv=prefs)
        await query.answer("✅ همه استان‌ها انتخاب شد")
        await query.edit_message_text(
            _summary_message(prefs, T.ADV_PROVINCE_ASK),
            reply_markup=kb.provinces_keyboard(set(PROVINCES)),
        )
        return

    if data == "adv_prov_clear":
        prefs["provinces"] = []
        st.set_state(tg.id, adv=prefs)
        await query.answer("پاک شد")
        await query.edit_message_text(
            _summary_message(prefs, T.ADV_PROVINCE_ASK),
            reply_markup=kb.provinces_keyboard(set()),
        )
        return

    if data == "adv_prov_ok":
        if not prefs.get("provinces"):
            await query.answer("حداقل یک استان انتخاب کن", show_alert=True)
            return
        await query.answer()
        st.set_state(tg.id, wait="age_min", adv=prefs)

        from bot.handlers import membership as mem_handler

        gated = await mem_handler.maybe_prompt_sponsor(
            context=context,
            query=query,
            provinces=list(prefs.get("provinces") or []),
            continue_to="advanced_age",
        )
        if gated:
            return

        await query.edit_message_text(
            _summary_message(prefs, T.ADV_AGE_MIN_ASK),
            reply_markup=kb.age_min_keyboard(),
        )
        return

    # --- age ---
    if data.startswith("adv_age:"):
        await query.answer()
        kind, val = data.split(":")[1], data.split(":")[2]
        if kind == "min":
            if val == "any":
                prefs["age_from"] = None
            else:
                prefs["age_from"] = int(val)
            prefs["age_step_done"] = False
            st.set_state(tg.id, wait="age_max", adv=prefs)
            await query.edit_message_text(
                _summary_message(prefs, T.ADV_AGE_MAX_ASK),
                reply_markup=kb.age_max_keyboard(prefs.get("age_from")),
            )
            return
        if kind == "max":
            if val == "any":
                prefs["age_to"] = None
            else:
                prefs["age_to"] = int(val)
            prefs["age_step_done"] = True
            st.set_state(tg.id, wait="last_seen", adv=prefs)
            await query.edit_message_text(
                _summary_message(prefs, T.ADV_LAST_SEEN_ASK),
                reply_markup=kb.last_seen_keyboard(),
            )
            return

    # --- last seen ---
    if data.startswith("adv_seen:"):
        await query.answer()
        prefs["last_seen_hours"] = int(data.split(":")[1])
        st.set_state(tg.id, wait="sort", adv=prefs)
        await query.edit_message_text(
            _summary_message(prefs, T.ADV_SORT_ASK),
            reply_markup=kb.sort_keyboard(),
        )
        return

    # --- sort + results ---
    if data.startswith("adv_sort:"):
        await query.answer("در حال جستجو…")
        prefs["sort_by"] = data.split(":")[1]
        st.set_state(tg.id, wait="results", adv=prefs)
        await _show_results(query, context, tg, prefs, page=0)
        return

    if data.startswith("adv_page:"):
        await query.answer()
        page = int(data.split(":")[1])
        await _show_results(query, context, tg, prefs, page=page)
        return

    if data == "adv_research":
        await query.answer()
        st.set_state(tg.id, mode="advanced", wait="partner_gender", adv={})
        await query.edit_message_text(
            T.ADVANCED_PARTNER_ASK,
            reply_markup=kb.partner_gender_inline("adv_partner"),
        )
        return

    if data == "adv_queue":
        await query.answer()
        await _enqueue_from_prefs(query, context, tg, prefs)
        return

    if data.startswith("adv_prof:"):
        await query.answer()
        target_id = int(data.split(":")[1])
        from bot.handlers import user_profile

        # Profile is a separate new message — keep results list intact.
        await user_profile.show_user_profile(update, context, target_id)
        return

    if data.startswith("adv_busy:"):
        await query.answer(T.INVITE_IN_GAME, show_alert=True)
        return

    if data.startswith("adv_play:"):
        await query.answer()
        target_id = int(data.split(":")[1])
        from bot.handlers import play_invite

        async def _notify(text: str) -> None:
            # Keep results list; busy/errors as a separate message only.
            try:
                await context.bot.send_message(tg.id, text)
            except Exception:
                pass

        await play_invite.send_play_invite(
            context, from_tg=tg, to_user_id=target_id, notify=_notify
        )
        return


_PAGE_SIZE = 10


async def _show_results(query, context, tg, prefs, page: int) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from bot.services.presence import presence_label

    with get_session() as session:
        me = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        found = search_svc.search_partners(
            session,
            me,
            gender=prefs["gender"],
            provinces=prefs.get("provinces") or [],
            age_from=prefs.get("age_from"),
            age_to=prefs.get("age_to"),
            last_seen_hours=prefs.get("last_seen_hours"),
            sort_by=prefs.get("sort_by") or "online",
            limit=50,
        )
        ids = [u.id for u in found]
        st.set_state(tg.id, adv={**prefs, "result_ids": ids, "page": page})

        summary = search_svc.filters_summary(prefs)
        gender = prefs.get("gender")
        provs = prefs.get("provinces") or []
        g_word = "پسر" if gender == "male" else "دختر" if gender == "female" else ""
        inline_q = f"{g_word} {provs[0]}".strip() if len(provs) == 1 else g_word or "جستجو"
        inline_row = [
            InlineKeyboardButton(
                T.BTN_ADV_INLINE_LIST,
                switch_inline_query_current_chat=inline_q,
            )
        ]
        if not ids:
            markup = InlineKeyboardMarkup(
                [
                    inline_row,
                    [InlineKeyboardButton(T.BTN_NEW_SEARCH, callback_data="adv_research")],
                    [InlineKeyboardButton(T.BTN_WAIT_QUEUE, callback_data="adv_queue")],
                ]
            )
            await query.edit_message_text(
                f"{summary}\n\n{T.ADV_NO_RESULTS}",
                reply_markup=markup,
            )
            return

        from bot.services.profile_links import profile_command

        start = page * _PAGE_SIZE
        page_ids = ids[start : start + _PAGE_SIZE]
        lines = []
        button_rows = [inline_row]
        for n, uid in enumerate(page_ids, start + 1):
            u = session.get(User, uid)
            if not u:
                continue
            name = user_svc.public_name(u)
            cmd = profile_command(uid)
            in_game = bool(game_engine.active_session_for_user(session, u))
            status = presence_label(last_active_at=u.last_active_at, in_game=in_game)
            # One compact row: name · last-seen · profile command
            lines.append(f"{n}. {name} · {status} · {cmd}")
            if in_game:
                invite_btn = InlineKeyboardButton(
                    T.BTN_ADV_IN_GAME,
                    callback_data=f"adv_busy:{uid}",
                )
            else:
                invite_btn = InlineKeyboardButton(
                    f"{T.BTN_ADV_INVITE} {name}"[:40],
                    callback_data=f"adv_play:{uid}",
                )
            button_rows.append([invite_btn])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(T.BTN_PREV_PAGE, callback_data=f"adv_page:{page-1}"))
        if start + _PAGE_SIZE < len(ids):
            nav.append(InlineKeyboardButton(T.BTN_NEXT_PAGE, callback_data=f"adv_page:{page+1}"))
        if nav:
            button_rows.append(nav)
        button_rows.append(
            [
                InlineKeyboardButton(T.BTN_NEW_SEARCH, callback_data="adv_research"),
                InlineKeyboardButton(T.BTN_WAIT_QUEUE, callback_data="adv_queue"),
            ]
        )

        text = (
            f"{summary}\n\n"
            f"{T.ADV_RESULTS_HEADER.format(n=len(ids))}\n\n"
            + "\n".join(lines)
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(button_rows))



async def _enqueue_from_prefs(query, context, tg, prefs) -> None:
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        provinces = prefs.get("provinces") or []
        same_city = bool(user.city and prefs.get("same_city"))
        if not same_city and user.province and provinces == [user.province]:
            # single-province search for own province ≈ nearby-ish, but keep city soft
            same_city = False

    queue_prefs = {
        "same_city": same_city,
        "gender": prefs.get("gender") or "any",
        "age_from": prefs.get("age_from"),
        "age_to": prefs.get("age_to"),
        "require_identity": True,
        "play_anonymous": False,
        "provinces": provinces,
    }
    from bot.services import match_flow

    await match_flow.enqueue_and_maybe_match(
        context,
        telegram_user=tg,
        prefs=queue_prefs,
        queue_mode="advanced",
        edit_message=query.message,
    )
