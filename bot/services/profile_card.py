from __future__ import annotations

from io import BytesIO
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Message
from telegram.ext import ContextTypes

from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import User
from bot.services import storage


def profile_edit_inline() -> InlineKeyboardMarkup:
    """Single button — used after wizard completion."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data="profile_card:edit")]]
    )


def profile_fields_inline() -> InlineKeyboardMarkup:
    """Full edit pad under the profile card."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👤 نام", callback_data="pedit:name"),
                InlineKeyboardButton("📷 عکس", callback_data="pedit:photo"),
            ],
            [
                InlineKeyboardButton("🗺 استان", callback_data="pedit:province"),
                InlineKeyboardButton("🏙 شهر", callback_data="pedit:city"),
            ],
            [
                InlineKeyboardButton("🎂 سن", callback_data="pedit:age"),
                InlineKeyboardButton("🚻 جنسیت", callback_data="pedit:gender"),
            ],
            [
                InlineKeyboardButton("🦇 لقب", callback_data="pedit:nickname"),
                InlineKeyboardButton("⚙️ تنظیمات بازی", callback_data="pedit:settings"),
            ],
        ]
    )


def format_card_caption(user: User, *, intro: Optional[str] = None) -> str:
    """Human profile card — photo is sent separately, no URL."""
    gender_map = {"male": "پسر 👦", "female": "دختر 👧"}
    lines = []
    if intro:
        lines.append(intro.strip())
        lines.append("")
    lines.extend(
        [
            "🪪 پروفایل تو",
            "",
            f"👤 نام: {user.display_name or '—'}",
            f"🦇 لقب: {user.nickname or '—'}",
            f"🚻 جنسیت: {gender_map.get(user.gender or '', '—')}",
            f"🗺 استان: {user.province or '—'}",
            f"🏙 شهر: {user.city or '—'}",
            f"🎂 سن: {user.age or '—'}",
            f"❤️ لایک: {int(getattr(user, 'likes_count', 0) or 0)}",
            _last_seen_line(user),
        ]
    )
    return "\n".join(lines)


def _last_seen_line(user: User) -> str:
    from bot.services.presence import format_last_seen

    return format_last_seen(getattr(user, "last_active_at", None))


async def send_profile_card(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    *,
    intro: Optional[str] = None,
    with_main_menu: bool = True,
    edit_mode: bool = False,
) -> None:
    caption = format_card_caption(user, intro=intro)
    if len(caption) > 1000:
        caption = caption[:997] + "…"

    markup = profile_fields_inline() if edit_mode else profile_edit_inline()
    sent = False

    if user.profile_photo_file_id:
        try:
            await message.reply_photo(
                photo=user.profile_photo_file_id,
                caption=caption,
                reply_markup=markup,
            )
            sent = True
        except Exception:
            sent = False

    if not sent and user.profile_photo_key:
        data = storage.download_bytes(user.profile_photo_key)
        if data:
            try:
                result = await message.reply_photo(
                    photo=InputFile(BytesIO(data), filename="profile.jpg"),
                    caption=caption,
                    reply_markup=markup,
                )
                if result.photo:
                    with get_session() as session:
                        db_user = session.get(User, user.id)
                        if db_user:
                            db_user.profile_photo_file_id = result.photo[-1].file_id
                sent = True
            except Exception:
                sent = False

    if not sent:
        await message.reply_text(caption, reply_markup=markup)

    if with_main_menu and not edit_mode:
        await message.reply_text("منوی بازی آماده‌ست 👇", reply_markup=main_menu())
