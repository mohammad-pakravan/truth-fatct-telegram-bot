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
    Status hub: prefer edit-in-place so searching/waiting messages update
    instead of stacking. Never deletes Q&A history messages.
    """
    if message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
            )
            if replace_keyboard and reply_kb is not None:
                # ReplyKeyboard can't be set via edit — push it with a
                # disposable message, then remove that bubble.
                try:
                    tmp = await bot.send_message(
                        chat_id, "\u2060", reply_markup=reply_kb
                    )
                    try:
                        await bot.delete_message(chat_id, tmp.message_id)
                    except Exception:
                        pass
                except Exception:
                    logger.debug("keyboard bump failed", exc_info=True)
            return message_id
        except Exception:
            logger.debug("hub edit failed chat=%s mid=%s", chat_id, message_id, exc_info=True)

    sent = await bot.send_message(chat_id, text, reply_markup=reply_kb)
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
    Action strip: truth/dare glass, ask-prompt, etc.
    Edits in place when possible; never deletes prior messages.
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


async def _strip_inline(bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
    except Exception:
        logger.debug("strip inline failed mid=%s", message_id, exc_info=True)


async def show_td_glass(
    bot,
    chat_id: int,
    *,
    session_id: int,
    chooser_id: int,
    turn_text: str,
    glass_message_id: int | None = None,
    bump: bool = True,
    peer_answer: str | None = None,
    clear_hub: bool = False,
) -> int:
    """
    Show truth-dare glass for the answerer.

    bump=True: send a fresh message at the bottom (old glass keeps text, buttons stripped).
    Never deletes hub / Q&A history.
    """
    from bot import keyboards as kb
    from bot.texts import fa as T

    if peer_answer:
        body = T.TURN_WITH_PEER_ANSWER.format(answer=peer_answer, turn=turn_text)
    else:
        body = T.TURN_ACTION.format(turn=turn_text)

    # clear_hub used to delete history — now only forget the tracked id.
    if clear_hub:
        st.set_state(chat_id, game_hub_message_id=None)

    if bump and glass_message_id:
        await _strip_inline(bot, chat_id, glass_message_id)
        glass_message_id = None
        st.set_state(chat_id, game_glass_message_id=None)

    return await upsert_action(
        bot,
        chat_id,
        body,
        message_id=glass_message_id,
        inline_kb=kb.truth_dare(session_id, chooser_id),
    )


async def clear_td_glass(bot, chat_id: int, glass_message_id: int | None = None) -> None:
    """Remove inline buttons from the action message — do not delete chat history."""
    mid = glass_message_id
    if mid is None:
        mid = st.get(chat_id).get("game_glass_message_id")
    if not mid:
        return
    await _strip_inline(bot, chat_id, mid)
    st.set_state(chat_id, game_glass_message_id=None)


async def send_game_message(bot, chat_id: int, text: str, *, reply_kb=None, inline_kb=None) -> None:
    await upsert_hub(bot, chat_id, text, reply_kb=reply_kb, replace_keyboard=True)
