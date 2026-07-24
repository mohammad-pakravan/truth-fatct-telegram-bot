from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import HISTORY_LIMIT
from bot.db import get_session
from bot.keyboards import main_menu
from bot.services import game_engine
from bot.services import users as user_svc
from bot.texts import fa as T


async def open_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    with get_session() as session:
        user = user_svc.get_or_create_user(
            session,
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.full_name,
        )
        games = game_engine.user_recent_games(session, user, HISTORY_LIMIT)
        if not games:
            await update.message.reply_text(T.HISTORY_EMPTY, reply_markup=main_menu())
            return
        lines = [T.HISTORY_HEADER, ""]
        for i, g in enumerate(games, 1):
            summary = g.summary or f"نوع {g.game_type} — وضعیت {g.status}"
            lines.append(f"{i}. {summary}")
        await update.message.reply_text("\n".join(lines), reply_markup=main_menu())
