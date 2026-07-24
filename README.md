# ربات جرئت حقیقت تلگرام

ربات فارسی جرئت‌حقیقت با Postgres، MinIO و Docker.

## اجرای سریع با Docker

```bash
cp .env.example .env
# BOT_TOKEN و BOT_USERNAME را پر کن

docker compose up -d --build
```

سرویس‌ها:
| سرویس | نقش | پورت |
|--------|------|------|
| `bot` | ربات تلگرام | — |
| `db` | PostgreSQL | داخلی |
| `minio` | ذخیره عکس پروفایل | `9000` API / `9001` Console |

MinIO Console: http://localhost:9001  
پیش‌فرض: `minioadmin` / `minioadmin123`

## ویزارد مشخصات

وقتی کاربر `/start` می‌زند و پروفایل ناقص باشد:
1. نام نمایشی  
2. استان  
3. شهر  
4. جنسیت  
5. سن  
6. عکس پروفایل (اختیاری → MinIO)

## توسعه محلی بدون Docker

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
# DATABASE_URL و MinIO را در .env روی localhost بگذار
# postgres و minio را با docker compose up -d db minio minio-init اجرا کن
python -m bot.main
```

## دستورهای ربات

| دستور | توضیح |
|--------|--------|
| `/start` | منو یا ویزارد |
| `/group_game` | بازی گروهی |
| `/channel_game` | بازی کانال |
| `/cancel_match` | خروج از صف |
