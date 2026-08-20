from __future__ import annotations

import logging

from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from bot.config import (
    IDLE_NUDGE_JOB_SECONDS,
    MATCH_JOB_INTERVAL_SECONDS,
    TELEGRAM_CONNECT_TIMEOUT,
    TELEGRAM_POOL_TIMEOUT,
    TELEGRAM_PROXY,
    TELEGRAM_READ_TIMEOUT,
    TELEGRAM_WRITE_TIMEOUT,
    require_token,
)
from bot.jobs.idle_nudge import idle_nudge_job
from bot.jobs.matcher import match_queue_job
from bot.db import get_session, init_db
from bot.handlers import (
    admin,
    advanced,
    channel,
    fake,
    friends,
    gameplay,
    group,
    history,
    inline_mode,
    membership,
    menu,
    play_invite,
    profile,
    start,
    stranger,
    user_profile,
    wizard,
)
from bot.services import fake_identity as fake_svc
from bot.services import placeholders as ph_svc
from bot.services import storage
from bot.texts import fa as T
from bot import state as st
from bot.filelog import setup_file_logging

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
_log_path = setup_file_logging()
logger = logging.getLogger(__name__)

# Browse / settings OK without full profile; game & chat need it
_OPEN_WITHOUT_PROFILE = {
    T.BTN_HELP,
    T.BTN_CONTACT,
    T.BTN_ADMIN,
    T.BTN_HUB_PLAY,  # hub itself; modes inside gate via their open_* handlers
    T.BTN_HUB_PROFILE,
    T.BTN_HUB_FRIENDS,
    T.BTN_PROFILE,
    T.BTN_HISTORY,
    T.BTN_SHOW_PROFILE,
    T.BTN_RUN_WIZARD,
    T.BTN_COMPLETE_PROFILE,
    T.BTN_GAME_SETTINGS,
}


async def on_menu_buttons(update, context):
    if not update.message or not update.message.text or not update.effective_user:
        return
    text = update.message.text.strip()

    # Wizard has priority
    if await wizard.wizard_text(update, context):
        return

    if await admin.admin_text(update, context):
        return

    if await user_profile.uprofile_text(update, context):
        return

    if await stranger.leave_queue(update, context):
        return

    # Hub submenus first (mode-scoped)
    if await menu.hub_play_text(update, context):
        return
    if await menu.hub_profile_text(update, context):
        return
    if await menu.hub_friends_text(update, context):
        return

    mapping = {
        T.BTN_HUB_PLAY: menu.open_hub_play,
        T.BTN_ADVANCED: advanced.open_advanced,
        T.BTN_HUB_PROFILE: menu.open_hub_profile,
        T.BTN_HUB_FRIENDS: menu.open_hub_friends,
        T.BTN_HELP: menu.open_help,
        T.BTN_CONTACT: menu.open_contact,
        T.BTN_ADMIN: admin.open_admin,
        # Legacy direct entries (old keyboards)
        T.BTN_STRANGER: stranger.open_stranger,
        T.BTN_PLAY_NORMAL: stranger.open_stranger,
        T.BTN_NEARBY: stranger.open_nearby,
        T.BTN_ANON: stranger.open_anonymous,
        T.BTN_FAKE: fake.open_fake,
        T.BTN_FRIENDS: friends.open_friends,
        T.BTN_PLAY_FRIEND_LINK: friends.open_friends,
        T.BTN_GROUP_CHANNEL: group.open_group_channel,
        T.BTN_PROFILE: profile.open_profile,
        T.BTN_HISTORY: history.open_history,
        T.BTN_COMPLETE_PROFILE: lambda u, c: wizard.start_wizard(u, c, force=True),
        T.BTN_RUN_WIZARD: lambda u, c: wizard.start_wizard(u, c, force=True),
    }

    # Only gate game/chat entry points
    if text in mapping and text not in _OPEN_WITHOUT_PROFILE:
        if await wizard.maybe_require_wizard(update, context, feature=text):
            return

    handler = mapping.get(text)
    if handler:
        await handler(update, context)
        return

    if text == T.BTN_BACK:
        mode = st.get(update.effective_user.id).get("mode")
        if mode == "profile":
            await profile.profile_text(update, context)
            return
        if mode in ("hub_profile", "hub_friends", "hub_play"):
            if await menu.hub_play_text(update, context):
                return
            if await menu.hub_profile_text(update, context):
                return
            if await menu.hub_friends_text(update, context):
                return
        await start.menu_router(update, context)
        return

    if await gameplay.game_menu_text(update, context):
        return

    if await gameplay.report_other_text(update, context):
        return

    if await gameplay.custom_prompt_text(update, context):
        return

    if await gameplay.answer_text(update, context):
        return

    if await gameplay.relay_private_chat(update, context):
        return

    await profile.profile_text(update, context)
    await friends.friends_text(update, context)
    await channel.channel_text(update, context)
    await channel.discussion_comment(update, context)


async def on_photo(update, context):
    if await admin.admin_media(update, context):
        return
    if await wizard.wizard_photo(update, context):
        return
    if await gameplay.on_game_media(update, context):
        return
    # Inline find sends CachedPhoto with /Profile_… caption
    cap = (update.message.caption or "").strip() if update.message else ""
    if cap.lower().startswith("/profile_"):
        await user_profile.on_profile_command(update, context)


async def on_voice_or_video(update, context):
    if await admin.admin_media(update, context):
        return
    if await gameplay.on_game_media(update, context):
        return


async def on_document_or_audio(update, context):
    """Files / audio / gif / stickers — used mainly for admin broadcast."""
    if await admin.admin_media(update, context):
        return


async def on_location(update, context):
    if await stranger.nearby_location(update, context):
        return


async def match_pref_callbacks(update, context):
    if not update.effective_user:
        return
    if st.get(update.effective_user.id).get("mode") == "fake_match":
        await fake.fake_callbacks(update, context)
    else:
        await stranger.stranger_callbacks(update, context)


async def on_error(update, context) -> None:
    err = context.error
    if isinstance(err, (TimedOut, NetworkError)):
        logger.warning("Telegram network issue: %s", err)
        return
    if isinstance(err, Forbidden):
        # User blocked the bot — common, not a crash.
        logger.info("Forbidden (user blocked bot): %s", err)
        return
    if isinstance(err, BadRequest):
        msg = str(err).lower()
        if any(
            s in msg
            for s in (
                "message is not modified",
                "message to edit not found",
                "message to delete not found",
                "query is too old",
                "message can't be edited",
                "message_id_invalid",
            )
        ):
            logger.debug("Ignorable BadRequest: %s", err)
            return
        logger.warning("BadRequest: %s | update=%s", err, update)
        return
    logger.exception("Unhandled error while processing update: %s", update)


async def post_init(app: Application) -> None:
    init_db()
    try:
        storage.ensure_bucket()
    except Exception:
        logger.exception("MinIO bucket check failed (bot still runs; photo upload may fail)")
    with get_session() as session:
        n = fake_svc.seed_from_json(session)
        if n:
            logger.info("Seeded %s fake identities", n)
    try:
        await ph_svc.ensure_placeholder_file_ids(app.bot)
    except Exception:
        logger.exception("Placeholder upload failed (inline thumbs may miss gender defaults)")
    if app.job_queue:
        app.job_queue.run_repeating(
            match_queue_job,
            interval=MATCH_JOB_INTERVAL_SECONDS,
            first=2,
            name="match_queue",
            job_kwargs={"max_instances": 1, "coalesce": True, "misfire_grace_time": 15},
        )
        app.job_queue.run_repeating(
            idle_nudge_job,
            interval=IDLE_NUDGE_JOB_SECONDS,
            first=20,
            name="idle_nudge",
            job_kwargs={"max_instances": 1, "coalesce": True, "misfire_grace_time": 30},
        )
        logger.info(
            "Background jobs: match every %ss, idle nudge every %ss",
            MATCH_JOB_INTERVAL_SECONDS,
            IDLE_NUDGE_JOB_SECONDS,
        )
    else:
        logger.warning(
            "JobQueue unavailable — install python-telegram-bot[job-queue] for background matching"
        )


async def post_stop(app: Application) -> None:
    logger.warning("Bot stopping (post_stop)")


def build_app(token: str | None = None) -> Application:
    request_kwargs = {
        "connect_timeout": TELEGRAM_CONNECT_TIMEOUT,
        "read_timeout": TELEGRAM_READ_TIMEOUT,
        "write_timeout": TELEGRAM_WRITE_TIMEOUT,
        "pool_timeout": TELEGRAM_POOL_TIMEOUT,
    }
    if TELEGRAM_PROXY:
        request_kwargs["proxy"] = TELEGRAM_PROXY
        logger.info("Using TELEGRAM_PROXY")

    request = HTTPXRequest(**request_kwargs)
    app = (
        Application.builder()
        .token(token or require_token())
        .request(request)
        .get_updates_request(HTTPXRequest(**request_kwargs))
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )
    app.add_error_handler(on_error)

    app.add_handler(CommandHandler("start", start.start))
    app.add_handler(CommandHandler("admin", admin.open_admin))
    app.add_handler(CommandHandler("group_game", group.group_game_cmd))
    app.add_handler(CommandHandler("channel_game", channel.channel_game_cmd))
    app.add_handler(CommandHandler("cancel_match", stranger.cancel_match_cmd))
    app.add_handler(CommandHandler("set_private", profile.set_private_cmd))
    app.add_handler(
        MessageHandler(
            filters.Regex(r"(?i)^/profile_[A-Za-z0-9_-]+(?:@\w+)?\s*$"),
            user_profile.on_profile_command,
        )
    )

    app.add_handler(InlineQueryHandler(inline_mode.inline_query))
    app.add_handler(ChosenInlineResultHandler(inline_mode.chosen_inline_result))

    app.add_handler(CallbackQueryHandler(friends.friends_callbacks, pattern=r"^inv_disp:"))
    app.add_handler(
        CallbackQueryHandler(
            profile.profile_callbacks,
            pattern=r"^(pgender:|pprov:|set:|profile_card:|pedit:|own:likes)",
        )
    )
    app.add_handler(CallbackQueryHandler(wizard.wizard_callbacks, pattern=r"^(wiz_prov:|wiz_gender:)"))
    app.add_handler(CallbackQueryHandler(membership.membership_callbacks, pattern=r"^mem_"))
    app.add_handler(CallbackQueryHandler(admin.admin_callbacks, pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(gameplay.on_user_report, pattern=r"^ureport:"))
    app.add_handler(CallbackQueryHandler(gameplay.on_post_game_action, pattern=r"^pgact:"))
    app.add_handler(CallbackQueryHandler(menu.contacts_callbacks, pattern=r"^contact:"))
    app.add_handler(CallbackQueryHandler(menu.hub_friends_callbacks, pattern=r"^hubf:"))
    app.add_handler(CallbackQueryHandler(profile.privacy_callbacks, pattern=r"^priv:"))
    app.add_handler(CallbackQueryHandler(user_profile.on_uprofile_callback, pattern=r"^up:"))
    app.add_handler(CallbackQueryHandler(user_profile.on_upreport_callback, pattern=r"^upreport:"))
    app.add_handler(CallbackQueryHandler(group.gc_help_callback, pattern=r"^gc:"))
    app.add_handler(CallbackQueryHandler(group.group_callbacks, pattern=r"^(gjoin:|gstart:|grejoin:|gcat:|greshuf:|gdone:|gnext:|gend:)"))
    app.add_handler(CallbackQueryHandler(gameplay.on_truth_dare, pattern=r"^td:"))
    app.add_handler(CallbackQueryHandler(gameplay.on_asker_bank, pattern=r"^1vq:"))
    app.add_handler(CallbackQueryHandler(gameplay.on_game_action, pattern=r"^gact:"))
    app.add_handler(CallbackQueryHandler(gameplay.on_end_confirm, pattern=r"^end(ok|no):"))
    app.add_handler(CallbackQueryHandler(gameplay.on_game_after, pattern=r"^gafter:"))
    app.add_handler(CallbackQueryHandler(gameplay.on_skip, pattern=r"^skip:"))
    app.add_handler(CallbackQueryHandler(stranger.nearby_callbacks, pattern=r"^near_r:"))
    app.add_handler(
        CallbackQueryHandler(
            match_pref_callbacks,
            pattern=r"^(str_city:|pref_gender:|age_from:|age_to:|str_id:|str_allow:|str_cancel$)",
        )
    )
    app.add_handler(CallbackQueryHandler(play_invite.on_invite_callback, pattern=r"^invite:"))
    app.add_handler(
        CallbackQueryHandler(
            advanced.advanced_callbacks,
            pattern=r"^(adv_partner:|adv_prov|adv_age:|adv_seen:|adv_sort:|adv_page:|adv_play:|adv_busy:|adv_prof:|adv_research$|adv_queue$)",
        )
    )
    app.add_handler(
        CallbackQueryHandler(fake.fake_callbacks, pattern=r"^(fake_gender:|fake_go:|fake_reroll:|fguess:)")
    )
    app.add_handler(
        CallbackQueryHandler(
            channel.channel_callbacks,
            pattern=r"^(ch_mode:|ch_ask:|ch_opt:|ch_close:|ch_next:|ch_end:)",
        )
    )

    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(
        MessageHandler(filters.VOICE | filters.VIDEO | filters.VIDEO_NOTE, on_voice_or_video)
    )
    app.add_handler(
        MessageHandler(
            filters.Document.ALL | filters.AUDIO | filters.ANIMATION | filters.Sticker.ALL,
            on_document_or_audio,
        )
    )
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_menu_buttons))

    return app


def main() -> None:
    app = build_app()
    logger.info("Bot starting… file log: %s (last %s lines)", _log_path, 500)
    try:
        app.run_polling(
            allowed_updates=[
                "message",
                "callback_query",
                "channel_post",
                "inline_query",
                "chosen_inline_result",
            ]
        )
    except KeyboardInterrupt:
        logger.warning("Bot stopped by KeyboardInterrupt")
        raise
    except Exception:
        logger.exception("Bot crashed in run_polling")
        raise
    finally:
        logger.warning("Bot main() exited")


if __name__ == "__main__":
    main()
