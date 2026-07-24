from __future__ import annotations

import io
import logging

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Profile photos: small enough for cheap storage, still look fine in chat
MAX_EDGE = 720
JPEG_QUALITY = 72


def compress_profile_image(data: bytes) -> bytes:
    """
    Resize + JPEG-compress profile photo.
    Keeps visual quality acceptable while cutting size a lot.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)

        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        longest = max(w, h)
        if longest > MAX_EDGE:
            scale = MAX_EDGE / longest
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        img.save(
            out,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
            progressive=True,
        )
        compressed = out.getvalue()
        if len(compressed) < len(data):
            logger.info("Photo compressed %s → %s bytes", len(data), len(compressed))
            return compressed
        return compressed
    except Exception:
        logger.exception("Image compress failed; using original bytes")
        return data
