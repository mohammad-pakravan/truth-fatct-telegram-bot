from __future__ import annotations

import logging
from datetime import datetime, timedelta

from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from bot.config import (
    IDLE_NUDGE_COOLDOWN_SECONDS,
    IDLE_NUDGE_MIN_WAIT_SECONDS,
    IDLE_OFFLINE_SECONDS,
)
from bot.db import get_session
from bot.models import GameSession, Round, User
from bot.services import game_engine
from bot.texts import fa as T

logger = logging.getLogger(__name__)

_ONE_V_ONE = frozenset(
    {"friends", "stranger", "anonymous", "nearby", "fake_identity"}
)


def _round_wait_state(rnd: Round) -> tuple[int, int, str] | None:
    """
    Return (due_user_id, waiter_user_id, reason) for an open round.
    due = whose action is needed; waiter = who is stuck waiting.
    reason: pick | prompt | answer
    """
    if rnd.status != "open":
        return None
    if not rnd.choice:
        return rnd.target_user_id, rnd.chooser_user_id, "pick"
    if not game_engine.round_has_prompt(rnd):
        return rnd.chooser_user_id, rnd.target_user_id, "prompt"
    return rnd.target_user_id, rnd.chooser_user_id, "answer"


async def idle_nudge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ping both players when someone goes idle mid-1v1 game."""
    now = datetime.utcnow()
    offline_before = now - timedelta(seconds=IDLE_OFFLINE_SECONDS)
    min_wait_before = now - timedelta(seconds=IDLE_NUDGE_MIN_WAIT_SECONDS)
    cooldown_before = now - timedelta(seconds=IDLE_NUDGE_COOLDOWN_SECONDS)

    try:
        with get_session() as session:
            games = (
                session.query(GameSession)
                .filter(
                    GameSession.status == "playing",
                    GameSession.game_type.in_(list(_ONE_V_ONE)),
                )
                .all()
            )
            payloads: list[tuple[int, int, int, str]] = []
            for game in games:
                if game.last_idle_nudge_at and game.last_idle_nudge_at > cooldown_before:
                    continue
                rnd = game_engine.get_active_round(session, game)
                if not rnd or rnd.created_at > min_wait_before:
                    continue
                state = _round_wait_state(rnd)
                if not state:
                    continue
                due_id, waiter_id, reason = state
                due = session.get(User, due_id)
                waiter = session.get(User, waiter_id)
                if not due or not waiter:
                    continue
                # Treat as idle after IDLE_OFFLINE_SECONDS (not the global presence window).
                if due.last_active_at and due.last_active_at > offline_before:
                    continue
                payloads.append(
                    (game.id, due.telegram_id, waiter.telegram_id, reason)
                )
                game.last_idle_nudge_at = now
    except Exception:
        logger.exception("idle_nudge_job: DB scan failed")
        return

    waiter_map = {
        "pick": T.IDLE_WAITER_PICK,
        "prompt": T.IDLE_WAITER_PROMPT,
        "answer": T.IDLE_WAITER_ANSWER,
    }
    due_map = {
        "pick": T.IDLE_DUE_PICK,
        "prompt": T.IDLE_DUE_PROMPT,
        "answer": T.IDLE_DUE_ANSWER,
    }
    for game_id, due_tg, waiter_tg, reason in payloads:
        for tg_id, text in (
            (waiter_tg, waiter_map.get(reason, T.IDLE_WAITER_ANSWER)),
            (due_tg, due_map.get(reason, T.IDLE_DUE_ANSWER)),
        ):
            try:
                await context.bot.send_message(tg_id, text)
            except Forbidden:
                logger.info(
                    "idle nudge: user blocked bot tg=%s game=%s", tg_id, game_id
                )
            except BadRequest as exc:
                logger.debug("idle nudge bad request tg=%s: %s", tg_id, exc)
            except Exception:
                logger.exception("idle nudge failed tg=%s game=%s", tg_id, game_id)
