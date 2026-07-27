from __future__ import annotations

import logging

from telegram.ext import ContextTypes

from bot.db import get_session
from bot.services import match_flow
from bot.services import matchmaker

logger = logging.getLogger(__name__)


async def match_queue_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic matcher for users already sitting in the waiting queue."""
    try:
        with matchmaker.match_section():
            with get_session() as session:
                results = matchmaker.process_queue_batch(session)
        for result in results:
            try:
                await match_flow.deliver_match(context, result)
            except Exception:
                logger.exception("Failed delivering match game_id=%s", result.game_id)
    except Exception:
        logger.exception("match_queue_job failed")
