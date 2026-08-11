from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
from typing import Optional

from bot.config import BOT_TOKEN

_PROFILE_RE = re.compile(r"(?i)^/profile_([A-Za-z0-9_-]+)(?:@\w+)?\s*$")


def _key() -> bytes:
    return (BOT_TOKEN or "jorat-profile").encode()


def encode_profile_code(user_id: int) -> str:
    """Short opaque code for /Profile_<code> links (no DB column)."""
    raw = struct.pack(">I", int(user_id))
    mac = hmac.new(_key(), raw, hashlib.sha256).digest()[:3]
    return base64.urlsafe_b64encode(raw + mac).decode().rstrip("=")


def decode_profile_code(code: str) -> Optional[int]:
    if not code:
        return None
    pad = "=" * (-len(code) % 4)
    try:
        data = base64.urlsafe_b64decode(code + pad)
    except Exception:
        return None
    if len(data) != 7:
        return None
    raw, mac = data[:4], data[4:]
    expect = hmac.new(_key(), raw, hashlib.sha256).digest()[:3]
    if not hmac.compare_digest(mac, expect):
        return None
    return int(struct.unpack(">I", raw)[0])


def profile_command(user_id: int) -> str:
    """Clickable bot command, e.g. /Profile_FxqYTyzMY."""
    return f"/Profile_{encode_profile_code(user_id)}"


def parse_profile_command(text: str) -> Optional[str]:
    """Return profile code from a /Profile_… message, or None."""
    m = _PROFILE_RE.match((text or "").strip())
    return m.group(1) if m else None
