from __future__ import annotations

import logging

from bot import state as st

logger = logging.getLogger(__name__)


async def upsert_hub(
    bot,
    chat_id: int,
    text: str,
    *,
    message_id: int | None = None,
    reply_kb=None,
    replace_keyboard: bool = False,
) -> int:
    """
    Status hub: match info / waiting / answering.
    Reply keyboard (profile / end / skip) lives here.
    Prefers edit-in-place; only resends when the reply keyboard must change.
    """
    if message_id is not None and not replace_keyboard:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
            )
            return message_id
        except Exception:
            logger.debug("hub edit failed chat=%s mid=%s", chat_id, message_id, exc_info=True)

    sent = await bot.send_message(chat_id, text, reply_markup=reply_kb)
    if message_id is not None and message_id != sent.message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.debug("old hub delete failed", exc_info=True)
    return sent.message_id


async def upsert_action(
    bot,
    chat_id: int,
    text: str,
    *,
    message_id: int | None = None,
    inline_kb=None,
) -> int:
    """
    Action strip under the hub: truth/dare glass, then ask-prompt, then 'sent'.
    Same message is edited through the chooser flow — no delete/flash.
    """
    if message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=inline_kb,
            )
            return message_id
        except Exception:
            logger.debug("action edit failed chat=%s mid=%s", chat_id, message_id, exc_info=True)

    sent = await bot.send_message(chat_id, text, reply_markup=inline_kb)
    return sent.message_id


async def show_td_glass(
    bot,
    chat_id: int,
    *,
    session_id: int,
    chooser_id: int,
    turn_text: str,
    glass_message_id: int | None = None,
) -> int:
    """Show / refresh the truth-dare action message."""
    from bot import keyboards as kb
    from bot.texts import fa as T

    body = T.TURN_ACTION.format(turn=turn_text)
    return await upsert_action(
        bot,
        chat_id,
        body,
        message_id=glass_message_id,
        inline_kb=kb.truth_dare(session_id, chooser_id),
    )


async def clear_td_glass(bot, chat_id: int, glass_message_id: int | None = None) -> None:
    """Drop the action message when the game ends or role no longer needs it."""
    mid = glass_message_id
    if mid is None:
        mid = st.get(chat_id).get("game_glass_message_id")
    if not mid:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=mid)
    except Exception:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=mid, reply_markup=None
            )
        except Exception:
            logger.debug("action clear failed", exc_info=True)
    st.set_state(chat_id, game_glass_message_id=None)


async def send_game_message(bot, chat_id: int, text: str, *, reply_kb=None, inline_kb=None) -> None:
    await upsert_hub(bot, chat_id, text, reply_kb=reply_kb, replace_keyboard=True)
