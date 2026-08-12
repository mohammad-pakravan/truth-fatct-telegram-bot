from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import keyboards as kb
from bot import state as st
from bot.db import get_session
from bot.keyboards import main_menu
from bot.provinces import PROVINCES
from bot.services import storage
from bot.services import users as user_svc
from bot.texts import fa as T

logger = logging.getLogger(__name__)

FEATURE_LABELS = {
    T.BTN_HUB_PLAY: "شروع بازی",
    T.BTN_PLAY_NORMAL: "بازی عادی",
    T.BTN_ADVANCED: "چت و بازی پیشرفته",
    T.BTN_NEARBY: "افراد نزدیک",
    T.BTN_ANON: "بازی با ناشناس",
    T.BTN_HUB_PROFILE: "پروفایل و لیست‌ها",
    T.BTN_HUB_FRIENDS: "بازی با دوستان",
    T.BTN_FRIENDS: "لینک شخصی",
    T.BTN_PLAY_FRIEND_LINK: "لینک دوست",
    T.BTN_GROUP_CHANNEL: "بازی در کانال / گروه",
    T.BTN_STRANGER: "بازی با غریبه",
    T.BTN_FAKE: "بازی با هویت رندوم",
    "دعوت دوست": "قبول دعوت دوست",
}


def _first_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "رفیق"
    return (user.first_name or user.full_name or "رفیق").split()[0]


async def start_wizard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    force: bool = False,
    feature: str | None = None,
) -> None:
    """Begin profile completion wizard (usually when entering a game feature)."""
    if not update.effective_user:
        return
    tg = update.effective_user
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not message:
        return

    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        if user_svc.profile_complete(user) and not force:
            return

    st.set_state(tg.id, mode="wizard", wizard_step="name", pending_feature=feature)
    name = _first_name(update)

    if feature:
        label = FEATURE_LABELS.get(feature, feature)
        await message.reply_text(
            T.WIZARD_SOFT_GATE.format(feature=label),
            reply_markup=kb.wizard_cancel_menu(),
        )
    else:
        await message.reply_text(T.WIZARD_INTRO, reply_markup=kb.wizard_cancel_menu())

    hint = ""
    if tg.first_name and len(tg.first_name.strip()) >= 2:
        hint = f"\n\n💡 اگر خواستی همون «{tg.first_name}» باشه، همون رو بفرست."

    await message.reply_text(
        T.WIZARD_ASK_NAME + hint,
        reply_markup=kb.wizard_cancel_menu(),
    )


async def maybe_require_wizard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    feature: str | None = None,
) -> bool:
    """Return True if wizard blocked the action (caller should stop)."""
    if not update.effective_user:
        return False
    if st.get(update.effective_user.id).get("mode") == "wizard":
        return True
    with get_session() as session:
        user = user_svc.get_or_create_user(
            session,
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.full_name,
        )
        complete = user_svc.profile_complete(user)
    if complete:
        return False
    await start_wizard(update, context, feature=feature)
    return True


async def wizard_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user:
        return False
    tg = update.effective_user
    if st.get(tg.id).get("mode") != "wizard":
        return False

    text = (update.message.text or "").strip()
    step = st.get(tg.id).get("wizard_step")
    name = _first_name(update)

    if text == T.BTN_CANCEL:
        st.clear(tg.id)
        await update.message.reply_text(T.WIZARD_CANCELLED, reply_markup=main_menu(tg.id))
        return True

    if step == "name":
        if not text:
            await update.message.reply_text("فقط یه اسم یا لقب بفرست 😊")
            return True
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.display_name = text[:128]
            display = user.display_name
        st.set_state(tg.id, wizard_step="province")
        await update.message.reply_text(
            T.WIZARD_ASK_PROVINCE.format(name=display),
            reply_markup=kb.provinces_pick_one("wiz_prov"),
        )
        return True

    if step == "city":
        if len(text) < 2:
            await update.message.reply_text("اسم شهر رو کامل‌تر بنویس 🙂")
            return True
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.city = text[:64]
        st.set_state(tg.id, wizard_step="gender")
        await update.message.reply_text(
            T.WIZARD_ASK_GENDER,
            reply_markup=kb.gender_inline("wiz_gender"),
        )
        return True

    if step == "age":
        from bot.config import MAX_USER_AGE, MIN_USER_AGE

        if not text.isdigit() or not (MIN_USER_AGE <= int(text) <= MAX_USER_AGE):
            await update.message.reply_text(T.AGE_INVALID)
            return True
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.age = int(text)
        st.set_state(tg.id, wizard_step="photo")
        await update.message.reply_text(T.WIZARD_ASK_PHOTO, reply_markup=kb.skip_photo_menu())
        return True

    if step == "photo" and (
        text.replace("\ufe0f", "")
        in {
            T.BTN_SKIP_PHOTO.replace("\ufe0f", ""),
            T.BTN_SKIP.replace("\ufe0f", ""),
            "⏭ فعلاً بدون عکس",
        }
    ):
        await _finish_wizard(update, context)
        return True

    if step == "photo":
        await update.message.reply_text(
            "عکس بفرست، یا دکمه «فعلاً بدون عکس» رو بزن 📸",
            reply_markup=kb.skip_photo_menu(),
        )
        return True

    return True


async def wizard_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_user or not update.message.photo:
        return False
    tg = update.effective_user
    if st.get(tg.id).get("mode") != "wizard" or st.get(tg.id).get("wizard_step") != "photo":
        if st.get(tg.id).get("waiting") == "photo":
            await _save_photo(update, context)
            st.set_state(tg.id, waiting=None, mode="hub_profile")
            await update.message.reply_text(
                "عکس عوض شد ✅", reply_markup=kb.hub_profile_menu()
            )
            return True
        return False

    await _save_photo(update, context)
    await _finish_wizard(update, context)
    return True


async def wizard_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    tg = update.effective_user
    if st.get(tg.id).get("mode") != "wizard":
        return
    await query.answer()
    data = query.data
    step = st.get(tg.id).get("wizard_step")

    if data.startswith("wiz_prov:") and step == "province":
        idx = int(data.split(":")[1])
        province = PROVINCES[idx]
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.province = province

        from bot.handlers import membership as mem_handler

        gated = await mem_handler.maybe_prompt_sponsor(
            context=context,
            query=query,
            provinces=province,
            continue_to="wizard_city",
        )
        if gated:
            return

        st.set_state(tg.id, wizard_step="city")
        await query.edit_message_text(f"استان «{province}» ثبت شد 🗺")
        await query.message.reply_text(T.WIZARD_ASK_CITY, reply_markup=kb.wizard_cancel_menu())
        return

    if data.startswith("wiz_gender:") and step == "gender":
        gender = data.split(":")[1]
        with get_session() as session:
            user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
            user.gender = gender
        st.set_state(tg.id, wizard_step="age")
        label = "پسر" if gender == "male" else "دختر"
        await query.edit_message_text(f"جنسیت: {label} 👍")
        await query.message.reply_text(T.WIZARD_ASK_AGE, reply_markup=kb.wizard_cancel_menu())
        return


async def _save_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    data = await tg_file.download_as_bytearray()
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        old_key = user.profile_photo_key
        try:
            key = storage.upload_profile_photo(bytes(data), user_id=user.id)
            user.profile_photo_key = key
            user.profile_photo_file_id = photo.file_id
            user.show_photo = True
            if old_key and old_key != key:
                storage.delete_object(old_key)
        except Exception:
            logger.exception("MinIO upload failed; keeping telegram file_id only")
            user.profile_photo_file_id = photo.file_id
            user.show_photo = True


async def _finish_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.services.profile_card import send_profile_card

    tg = update.effective_user
    data = st.get(tg.id)
    pending = data.get("pending_feature")
    pending_invite = data.get("pending_invite")
    st.clear(tg.id)
    with get_session() as session:
        user = user_svc.get_or_create_user(session, tg.id, tg.username, tg.full_name)
        display = user.display_name or _first_name(update)
        # detach for use after session
        session.expunge(user)

    done = T.WIZARD_DONE.format(name=display)

    # Friend invite deep-link: resume match after profile is complete
    if pending_invite:
        await send_profile_card(
            update.message,
            context,
            user,
            intro=done,
            with_main_menu=False,
        )
        from bot.handlers import friends

        await friends.accept_invite_and_notify(
            update, context, pending_invite, intro=T.INVITE_RESUMED
        )
        return

    if pending:
        label = FEATURE_LABELS.get(pending, pending)
        done += f"\n\nحالا دوباره «{label}» رو از منو بزن تا بریم 🚀"

    await send_profile_card(
        update.message,
        context,
        user,
        intro=done,
        with_main_menu=True,
    )
