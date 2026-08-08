from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from telegram import Bot
from telegram.error import Forbidden, RetryAfter, TelegramError

from bot.config import BROADCAST_RATE_PER_SECOND

logger = logging.getLogger(__name__)

# Only one broadcast at a time across the process
_busy = False


def is_busy() -> bool:
    return _busy


async def copy_to_users(
    bot: Bot,
    *,
    from_chat_id: int,
    message_id: int,
    user_ids: list[int],
    rate_per_second: float | None = None,
    on_progress: Callable[[int, int, int, int], Awaitable[None]] | None = None,
    progress_every: int = 50,
) -> dict[str, int]:
    """
    Copy one message to many users with a safe send rate.

    Telegram allows roughly ~30 msg/s to different chats; we stay under that
    and respect RetryAfter when Telegram asks us to slow down.
    """
    global _busy
    if _busy:
        raise RuntimeError("broadcast_busy")
    _busy = True

    rate = rate_per_second if rate_per_second and rate_per_second > 0 else BROADCAST_RATE_PER_SECOND
    delay = 1.0 / max(rate, 0.5)
    ok = fail = blocked = 0
    total = len(user_ids)

    try:
        for i, tid in enumerate(user_ids, start=1):
            for attempt in range(3):
                try:
                    await bot.copy_message(
                        chat_id=tid,
                        from_chat_id=from_chat_id,
                        message_id=message_id,
                    )
                    ok += 1
                    sent = True
                    break
                except RetryAfter as e:
                    wait = float(e.retry_after) + 0.5
                    logger.warning("broadcast RetryAfter %.1fs (user %s)", wait, tid)
                    await asyncio.sleep(wait)
                except Forbidden:
                    blocked += 1
                    sent = True
                    break
                except TelegramError:
                    if attempt >= 2:
                        fail += 1
                        logger.exception("broadcast failed user=%s", tid)
                    else:
                        await asyncio.sleep(0.5)
                except Exception:
                    fail += 1
                    logger.exception("broadcast unexpected user=%s", tid)
                    sent = True
                    break

            if on_progress and (i % progress_every == 0 or i == total):
                try:
                    await on_progress(i, total, ok, fail + blocked)
                except Exception:
                    pass

            await asyncio.sleep(delay)
    finally:
        _busy = False

    return {"ok": ok, "fail": fail, "blocked": blocked, "total": total}
