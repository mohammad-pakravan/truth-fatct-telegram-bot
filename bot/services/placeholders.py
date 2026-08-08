from __future__ import annotations

import json
import logging
from pathlib import Path

from telegram import Bot

from bot.config import ADMIN_IDS, DATA_DIR

logger = logging.getLogger(__name__)

PLACEHOLDER_DIR = DATA_DIR / "placeholders"
FILE_IDS_PATH = DATA_DIR / "placeholder_file_ids.json"

_KEYS = ("male", "female", "unknown")


def _load_ids() -> dict[str, str]:
    if not FILE_IDS_PATH.exists():
        return {}
    try:
        return json.loads(FILE_IDS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_ids(data: dict[str, str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILE_IDS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_cached_file_id(gender: str | None) -> str | None:
    ids = _load_ids()
    key = "male" if gender == "male" else "female" if gender == "female" else "unknown"
    return ids.get(key) or ids.get("unknown")


async def ensure_placeholder_file_ids(bot: Bot) -> dict[str, str]:
    """
    Upload local placeholder images once (to an admin chat) and cache Telegram file_ids.
    Needed for inline CachedPhoto results when the user has no profile photo.
    """
    ids = _load_ids()
    missing = [k for k in _KEYS if not ids.get(k)]
    if not missing:
        return ids

    if not ADMIN_IDS:
        logger.warning("No ADMIN_IDS — cannot upload gender placeholders for inline thumbs")
        return ids

    chat_id = next(iter(ADMIN_IDS))
    for key in missing:
        path = PLACEHOLDER_DIR / f"{key}.jpg"
        if not path.exists():
            logger.warning("Placeholder file missing: %s", path)
            continue
        try:
            with path.open("rb") as fh:
                msg = await bot.send_photo(
                    chat_id,
                    photo=fh,
                    caption=f"[bot] placeholder:{key}",
                    disable_notification=True,
                )
            file_id = msg.photo[-1].file_id
            ids[key] = file_id
            try:
                await bot.delete_message(chat_id, msg.message_id)
            except Exception:
                pass
            logger.info("Cached placeholder file_id for %s", key)
        except Exception:
            logger.exception("Failed to upload placeholder %s", key)

    if ids:
        _save_ids(ids)
    return ids


def photo_file_id_for_user(user) -> str | None:
    """Prefer real profile photo; else gender placeholder file_id."""
    if getattr(user, "profile_photo_file_id", None):
        return user.profile_photo_file_id
    return get_cached_file_id(getattr(user, "gender", None))
