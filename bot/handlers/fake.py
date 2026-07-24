from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.models import GamePlayer
from bot.services import fake_identity as fake_svc
from bot.services import users as user_svc
from bot.handlers.stranger import _enqueue_and_match
from bot.texts import fa as T


async def open_fake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بازی با هویت رندوم (جدا از جستجوی پیشرفته)."""
    if not update.message:
        return
    st.set_state(update.effective_user.id, mode="fake", wait="fake_gender")
    await update.message.reply_text(
        T.FAKE_INTRO,
        reply_markup=kb.gender_inline("fake_gender"),
    )


async def fake_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    await query.answer()
    tg = update.effective_user
    data = query.data

    if data.startswith("fake_gender:"):
        gender = data.split(":")[1]
        with get_session() as session:
            fi = fake_svc.acquire(session, gender=gender)
            if not fi:
                await query.edit_message_text(T.FAKE_POOL_EMPTY)
                return
            token = f"{tg.id}_{fi.id}"
            st.set_state(
                tg.id,
                mode="fake",
                fake_id=fi.id,
                fake_token=token,
                pending_fake_card=True,
            )
            card = fake_svc.format_card(fi)
        await query.edit_message_text(card, reply_markup=kb.fake_continue(token))
        return

    if data.startswith("fake_go:"):
        mode = data.split(":")[-1]
        fake_id = st.get(tg.id).get("fake_id")
        if mode == "real":
            fake_id = None
            identity_mode = "real"
        else:
            identity_mode = "fake"
            if not fake_id:
                await query.edit_message_text("هویت فیک پیدا نشد؛ دوباره شروع کن.")
                return

        st.set_state(
            tg.id,
            mode="fake_match",
            fake_identity_id=fake_id,
            identity_mode=identity_mode,
            stranger={},
            wait="city",
        )
        await query.edit_message_text(
            "همشهری می‌خوای یا هرجا اوکیه؟",
            reply_markup=kb.city_pref(),
        )
        return

    if st.get(tg.id).get("mode") == "fake_match":
        s = st.get(tg.id).setdefault("stranger", {})
        if data.startswith("str_city:"):
            s["same_city"] = data.endswith(":same")
            st.set_state(tg.id, stranger=s)
            await query.edit_message_text(
                "جنسیت طرف مقابل؟", reply_markup=kb.gender_any_inline("pref_gender")
            )
            return
        if data.startswith("pref_gender:"):
            s["gender"] = data.split(":")[1]
            from bot.config import AGE_FROM_OPTIONS

            await query.edit_message_text(
                "رنج سنی — از؟",
                reply_markup=kb.age_options("age_from", AGE_FROM_OPTIONS),
            )
            return
        if data.startswith("age_from:"):
            s["age_from"] = int(data.split(":")[1])
            from bot.config import AGE_TO_OPTIONS

            opts = [a for a in AGE_TO_OPTIONS if a >= s["age_from"]]
            await query.edit_message_text(
                "رنج سنی — تا؟", reply_markup=kb.age_options("age_to", opts)
            )
            return
        if data.startswith("age_to:"):
            s["age_to"] = int(data.split(":")[1])
            await query.edit_message_text(
                "هویت طرف مشخص باشه؟", reply_markup=kb.identity_pref()
            )
            return
        if data.startswith("str_id:"):
            s["require_identity"] = data.endswith(":visible")
            s["play_anonymous"] = not s["require_identity"]
            await _enqueue_and_match(
                query,
                context,
                tg,
                s,
                use_fake=True,
                identity_mode=st.get(tg.id).get("identity_mode", "fake"),
                fake_id=st.get(tg.id).get("fake_identity_id"),
            )
            return

    if data.startswith("fguess:"):
        _, sid, guess = data.split(":")
        session_id = int(sid)
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username)
            player = (
                session.query(GamePlayer)
                .filter_by(session_id=session_id, user_id=user.id)
                .one_or_none()
            )
            if not player:
                await query.edit_message_text("تو این بازی نیستی.")
                return
            if player.final_guess:
                await query.edit_message_text("قبلاً حدست رو زدی.")
                return
            others = (
                session.query(GamePlayer)
                .filter(
                    GamePlayer.session_id == session_id,
                    GamePlayer.user_id != user.id,
                )
                .all()
            )
            if not others:
                await query.edit_message_text("حریف پیدا نشد.")
                return
            opp = others[0]
            truth = "fake" if opp.identity_mode == "fake" else "real"
            player.final_guess = guess
            player.guess_correct = guess == truth
            all_players = session.query(GamePlayer).filter_by(session_id=session_id).all()
            if all(p.final_guess for p in all_players):
                from bot.services import game_engine

                game = game_engine.get_session(session, session_id)
                if game:
                    game.status = "finished"
                    winners = [
                        user_svc.public_name(p.user)
                        for p in all_players
                        if p.guess_correct
                    ]
                    game.summary = (game.summary or "") + (
                        f" | برندگان حدس هویت: {'، '.join(winners) or 'هیچ‌کس'}"
                    )

            verdict = "درست گفتی 🎯" if player.guess_correct else "اشتباه بود 😅"
            guess_fa = T.GUESS_FAKE if guess == "fake" else T.GUESS_REAL
            truth_fa = T.GUESS_FAKE if truth == "fake" else T.GUESS_REAL
            await query.edit_message_text(
                T.FINAL_RESULT.format(
                    your_guess=guess_fa, truth=truth_fa, verdict=verdict
                )
            )
