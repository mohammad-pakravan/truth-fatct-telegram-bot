from __future__ import annotations

import asyncio
import logging

from telegram.ext import ContextTypes

from bot.db import get_session
from bot.services import match_flow
from bot.services import matchmaker

logger = logging.getLogger(__name__)

_DELIVER_TIMEOUT = 45


async def match_queue_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic matcher for users already sitting in the waiting queue."""
    try:
        with matchmaker.match_section():
            with get_session() as session:
                results = matchmaker.process_queue_batch(session)
    except Exception:
        logger.exception("match_queue_job failed")
        return

    for result in results:
        try:
            await asyncio.wait_for(
                match_flow.deliver_match(context, result),
                timeout=_DELIVER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(
                "deliver_match timed out game_id=%s", getattr(result, "game_id", "?")
            )
        except Exception:
            logger.exception(
                "Failed delivering match game_id=%s", getattr(result, "game_id", "?")
            )