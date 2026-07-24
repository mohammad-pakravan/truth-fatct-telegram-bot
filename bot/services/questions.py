from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Literal

from bot.config import QUESTIONS_PATH

Kind = Literal["truth", "dare"]

_DEFAULT = {
    "truth": [
        "آخرین باری که دروغ گفتی چی بود؟",
        "بزرگ‌ترین ترس زندگیت چیه؟",
        "اگه فردا همه پول‌دار بشی اولین کارت چیه؟",
        "یکی از خجالت‌آورترین خاطراتت رو بگو.",
        "آخرین کسی که بهش پیام دادی کی بود و چی گفتی؟",
        "بیشتر از همه از کدوم عادتت خجالت می‌کشی؟",
        "اگه می‌تونستی یه چیز از گذشته‌ت عوض کنی چی بود؟",
        "تا حالا عاشق کسی شدی که بهت نگفته باشه؟",
        "بدترین هدیه‌ای که گرفتی چی بوده؟",
        "یه راز کوچیک که هیچ‌کس نمی‌دونه بگو.",
    ],
    "dare": [
        "یه ایموجی رندم بفرست و بگو چرا همون رو انتخاب کردی.",
        "اسمت رو برعکس بنویس و با همون خودت رو معرفی کن.",
        "یه تعریف اغراق‌آمیز از طرف مقابلت بگو.",
        "۳۰ ثانیه فقط با سوال حرف بزن.",
        "یه جوک بد بگو عمداً.",
        "بگو اگه حیوون بودی چی بودی و چرا.",
        "یه قانون مسخره برای ادامه بازی بساز.",
        "آخرین استیکری که ذخیره کردی رو بفرست.",
        "با لحن رسمی و جدی یه جمله خیلی پیش‌پاافتاده بگو.",
        "یه چالش دو دقیقه‌ای برای طرف مقابل پیشنهاد بده.",
    ],
}


def _load() -> dict:
    path = Path(QUESTIONS_PATH)
    if path.exists():
        with path.open(encoding="utf-8-sig") as f:
            data = json.load(f)
        return {
            "truth": data.get("truth") or _DEFAULT["truth"],
            "dare": data.get("dare") or _DEFAULT["dare"],
        }
    return _DEFAULT


def random_prompt(kind: Kind) -> str:
    bank = _load()
    return random.choice(bank[kind])
