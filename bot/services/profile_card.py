from __future__ import annotations

from io import BytesIO
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Message
from telegram.ext import ContextTypes

from bot.db import get_session
from bot.keyboards import main_menu
from bot.models import User
from bot.services import social as social_svc
from bot.services import storage
from bot.services.textfmt import btn, fa_num, format_profile_card
from bot.texts import fa as T


def _likes_btn(likes: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        f"❤️ ({fa_num(likes)})", callback_data="own:likes"
    )


def profile_edit_inline(likes: int = 0) -> InlineKeyboardMarkup:
    """After wizard completion: likes + edit."""
    return InlineKeyboardMarkup(
        [
            [_likes_btn(likes)],
            [InlineKeyboardButton(btn("✏️", "ویرایش مشخصات"), callback_data="profile_card:edit")],
        ]
    )


def profile_fields_inline(likes: int = 0) -> InlineKeyboardMarkup:
    """Full edit pad under the profile card."""
    return InlineKeyboardMarkup(
        [
            [_likes_btn(likes)],
            [
                InlineKeyboardButton(btn("👤", "نام"), callback_data="pedit:name"),
                InlineKeyboardButton(btn("📷", "عکس"), callback_data="pedit:photo"),
            ],
            [
                InlineKeyboardButton(btn("🗺", "استان"), callback_data="pedit:province"),
                InlineKeyboardButton(btn("🏙", "شهر"), callback_data="pedit:city"),
            ],
            [
                InlineKeyboardButton(btn("🎂", "سن"), callback_data="pedit:age"),
                InlineKeyboardButton(btn("🚻", "جنسیت"), callback_data="pedit:gender"),
            ],
            [
                InlineKeyboardButton(btn("🦇", "لقب"), callback_data="pedit:nickname"),
                InlineKeyboardButton(btn("⚙️", "تنظیمات"), callback_data="pedit:settings"),
            ],
        ]
    )


def format_card_caption(user: User, *, intro: Optional[str] = None) -> str:
    """Own profile card caption."""
    return format_public_caption(user, apply_privacy=False, intro=intro, own=True)


def format_public_caption(
    user: User,
    *,
    apply_privacy: bool = True,
    intro: Optional[str] = None,
    own: bool = False,
    in_game: bool = False,
) -> str:
    """Public profile caption — compact RTL, HTML-safe for Telegram captions."""
    return format_profile_card(
        user,
        apply_privacy=apply_privacy,
        own=own,
        in_game=in_game,
        intro=intro,
        html=True,
        show_likes=False,
        show_status=not own,
    )


def public_profile_keyboard(
    target: User,
    *,
    likes: int,
    liked: bool = False,
    blocked: bool = False,
    watching: bool = False,
    is_contact: bool = False,
) -> InlineKeyboardMarkup:
    uid = target.id
    like_label = f"❤️ ({fa_num(likes)})"
    block_label = btn("🔓", "آنبلاک") if blocked else btn("🚫", "بلاک")
    friend_label = btn("✅", "مخاطب") if is_contact else btn("➕", "دوستی")
    notify_label = (
        btn("🔕", "لغو اطلاع") if watching else btn("🛎️", "اطلاع آنلاین")
    )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(like_label, callback_data=f"up:like:{uid}")],
            [
                InlineKeyboardButton(btn("📝", "دایرکت"), callback_data=f"up:dm:{uid}"),
                InlineKeyboardButton(btn("🎮", "دعوت بازی"), callback_data=f"up:play:{uid}"),
            ],
            [
                InlineKeyboardButton(block_label, callback_data=f"up:block:{uid}"),
                InlineKeyboardButton(friend_label, callback_data=f"up:friend:{uid}"),
            ],
            [InlineKeyboardButton(btn("⭕", "گزارش"), callback_data=f"up:report:{uid}")],
            [InlineKeyboardButton(notify_label, callback_data=f"up:notify:{uid}")],
        ]
    )


def friend_request_keyboard(from_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ قبول دوستی", callback_data=f"up:friend_ok:{from_user_id}"
                ),
                InlineKeyboardButton(
                    "❌ رد", callback_data=f"up:friend_no:{from_user_id}"
                ),
            ]
        ]
    )


def profile_report_keyboard(target_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.REPORT_REASON_ABUSE, callback_data=f"upreport:abuse:{target_user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    T.REPORT_REASON_SEXUAL,
                    callback_data=f"upreport:sexual:{target_user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    T.REPORT_REASON_SPAM, callback_data=f"upreport:spam:{target_user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    T.REPORT_REASON_OTHER, callback_data=f"upreport:other:{target_user_id}"
                )
            ],
        ]
    )


async def _send_photo_card(
    message: Message,
    user: User,
    caption: str,
    markup: InlineKeyboardMarkup | None,
    *,
    force_photo: bool = False,
) -> bool:
    wants_photo = force_photo or bool(getattr(user, "show_photo", False))

    if wants_photo and user.profile_photo_file_id:
        try:
            await message.reply_photo(
                photo=user.profile_photo_file_id,
                caption=caption[:1024],
                parse_mode="HTML",
                reply_markup=markup,
            )
            return True
        except Exception:
            pass

    if wants_photo and user.profile_photo_key:
        data = storage.download_bytes(user.profile_photo_key)
        if data:
            try:
                result = await message.reply_photo(
                    photo=InputFile(BytesIO(data), filename="profile.jpg"),
                    caption=caption[:1024],
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                if result.photo:
                    with get_session() as session:
                        db_user = session.get(User, user.id)
                        if db_user:
                            db_user.profile_photo_file_id = result.photo[-1].file_id
                return True
            except Exception:
                pass

    from bot.services import placeholders as ph_svc

    placeholder_id = ph_svc.get_cached_file_id(
        user.gender if wants_photo else None
    )
    if placeholder_id:
        try:
            await message.reply_photo(
                photo=placeholder_id,
                caption=caption[:1024],
                parse_mode="HTML",
                reply_markup=markup,
            )
            return True
        except Exception:
            pass

    await message.reply_text(caption, parse_mode="HTML", reply_markup=markup)
    return False


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
    if len(caption) > 1024:
        caption = format_card_caption(user, intro=None)[:1024]

    likes = int(getattr(user, "likes_count", 0) or 0)
    markup = (
        profile_fields_inline(likes) if edit_mode else profile_edit_inline(likes)
    )
    await _send_photo_card(message, user, caption, markup, force_photo=True)

    if with_main_menu and not edit_mode:
        await message.reply_text(
            "منوی بازی آماده‌ست 👇", reply_markup=main_menu(user.telegram_id)
        )


async def send_public_profile(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    viewer: User,
    target: User,
    in_game: bool = False,
) -> None:
    """Send another user's profile with social action buttons."""
    with get_session() as session:
        # Refresh counts / flags inside session
        t = session.get(User, target.id) or target
        v = session.get(User, viewer.id) or viewer
        likes = int(getattr(t, "likes_count", 0) or 0)
        liked = social_svc.has_liked(session, v, t.id)
        blocked = social_svc.is_blocked(session, v, t.id)
        watching = social_svc.has_online_notify(session, v, t.id)
        is_contact = social_svc.has_contact(session, v, t.id)
        session.expunge(t)
        caption = format_public_caption(t, apply_privacy=True, in_game=in_game)
        markup = public_profile_keyboard(
            t,
            likes=likes,
            liked=liked,
            blocked=blocked,
            watching=watching,
            is_contact=is_contact,
        )
        photo_user = t

    await _send_photo_card(message, photo_user, caption, markup)
