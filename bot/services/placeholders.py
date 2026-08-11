from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
from telegram import Bot

from bot.config import ADMIN_IDS, DATA_DIR

logger = logging.getLogger(__name__)

PLACEHOLDER_DIR = DATA_DIR / "placeholders"
PLACEHOLDER_VERSION = 3
FILE_IDS_PATH = DATA_DIR / f"placeholder_file_ids_v{PLACEHOLDER_VERSION}.json"
THUMB_URLS_PATH = DATA_DIR / f"placeholder_thumb_urls_v{PLACEHOLDER_VERSION}.json"

_KEYS = ("male", "female", "unknown")
_THUMB_URLS: dict[str, str] = {}


def _load_json(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_json(path: Path, data: dict[str, str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _gender_key(gender: str | None) -> str:
    if gender == "male":
        return "male"
    if gender == "female":
        return "female"
    return "unknown"


def get_cached_file_id(gender: str | None) -> str | None:
    ids = _load_json(FILE_IDS_PATH)
    key = _gender_key(gender)
    return ids.get(key) or ids.get("unknown")


def get_cached_thumb_url(gender: str | None) -> str | None:
    """Public HTTPS URL for InlineQueryResultArticle.thumbnail_url."""
    key = _gender_key(gender)
    if not _THUMB_URLS:
        _THUMB_URLS.update(_load_json(THUMB_URLS_PATH))
    return _THUMB_URLS.get(key) or _THUMB_URLS.get("unknown")


def _upload_public_image(path: Path) -> str | None:
    """
    Upload JPEG to a public host and return https://… URL.

    Article thumbs cannot use localhost MinIO or api.telegram.org/file/bot… —
    Telegram clients leave those blank.
    """
    raw = path.read_bytes()
    # litterbox: temporary but reliable anonymous HTTPS (catbox often blocks bots).
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "72h"},
                files={"fileToUpload": (path.name, raw, "image/jpeg")},
            )
            text = (resp.text or "").strip()
            if resp.status_code == 200 and text.startswith("https://"):
                return text
            logger.warning(
                "litterbox upload failed for %s: %s %s",
                path.name,
                resp.status_code,
                text[:200],
            )
    except Exception as exc:
        logger.warning("litterbox upload error for %s: %s", path.name, exc)
    return None


async def _ensure_public_thumb_urls(*, force: bool = False) -> dict[str, str]:
    """Upload local placeholders to a public HTTPS host; cache URLs."""
    global _THUMB_URLS
    urls = {} if force else _load_json(THUMB_URLS_PATH)
    _THUMB_URLS.update(urls)
    missing = [k for k in _KEYS if not urls.get(k)]
    if not missing:
        return urls

    for key in missing:
        path = PLACEHOLDER_DIR / f"{key}.jpg"
        if not path.exists():
            logger.warning("Placeholder file missing: %s", path)
            continue
        url = await asyncio.to_thread(_upload_public_image, path)
        if url:
            urls[key] = url
            _THUMB_URLS[key] = url
            logger.info("Cached public thumb URL for %s: %s", key, url)

    if urls:
        _save_json(THUMB_URLS_PATH, urls)
    return urls


async def ensure_placeholder_file_ids(bot: Bot) -> dict[str, str]:
    """
    1) Upload placeholders to admin chat → Telegram file_ids (CachedPhoto).
    2) Upload same files to public HTTPS host → Article thumbnail_url.
    """
    ids = _load_json(FILE_IDS_PATH)
    missing = [k for k in _KEYS if not ids.get(k)]

    if missing:
        if not ADMIN_IDS:
            logger.warning("No ADMIN_IDS — cannot upload gender placeholders for file_ids")
        else:
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
                            caption=f"[bot] placeholder:{key}:v{PLACEHOLDER_VERSION}",
                            disable_notification=True,
                        )
                    ids[key] = msg.photo[-1].file_id
                    try:
                        await bot.delete_message(chat_id, msg.message_id)
                    except Exception:
                        pass
                    logger.info("Cached placeholder file_id for %s", key)
                except Exception:
                    logger.exception("Failed to upload placeholder %s", key)

            if ids:
                _save_json(FILE_IDS_PATH, ids)

    # Always refresh public thumbs on startup (litterbox links expire).
    await _ensure_public_thumb_urls(force=True)
    return ids


def photo_file_id_for_user(user) -> str | None:
    """Prefer real profile photo when visible; else gender placeholder file_id."""
    show = getattr(user, "show_photo", True)
    if show and getattr(user, "profile_photo_file_id", None):
        return user.profile_photo_file_id
    return get_cached_file_id(getattr(user, "gender", None))


async def thumb_url_for_user(bot: Bot, user) -> str | None:
    """Public HTTPS URL for Article row thumbnails (or None if unavailable)."""
    url = get_cached_thumb_url(getattr(user, "gender", None))
    if url:
        return url
    await _ensure_public_thumb_urls(force=False)
    return get_cached_thumb_url(getattr(user, "gender", None))
