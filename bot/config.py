import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")
# Optional: socks5://… or http://… if api.telegram.org is blocked/slow
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "").strip()
TELEGRAM_CONNECT_TIMEOUT = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "20"))
TELEGRAM_READ_TIMEOUT = float(os.getenv("TELEGRAM_READ_TIMEOUT", "30"))
TELEGRAM_WRITE_TIMEOUT = float(os.getenv("TELEGRAM_WRITE_TIMEOUT", "30"))
TELEGRAM_POOL_TIMEOUT = float(os.getenv("TELEGRAM_POOL_TIMEOUT", "10"))

_default_db = (BASE_DIR / "data" / "bot.db").resolve().as_posix()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_default_db}")

DATA_DIR = BASE_DIR / "data"
QUESTIONS_PATH = DATA_DIR / "questions.json"
IDENTITIES_PATH = DATA_DIR / "seed_identities.json"

AGE_FROM_OPTIONS = [16, 18, 20, 22, 25, 28, 30, 35, 40]
AGE_TO_OPTIONS = [18, 20, 22, 25, 28, 30, 35, 40, 45, 50]

HISTORY_LIMIT = 20
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME", "").lstrip("@")
CONTACT_INFO = os.getenv("CONTACT_INFO", "")

# Match queue
MATCH_QUEUE_TTL_MINUTES = int(os.getenv("MATCH_QUEUE_TTL_MINUTES", "45"))
MATCH_JOB_INTERVAL_SECONDS = float(os.getenv("MATCH_JOB_INTERVAL_SECONDS", "3"))
MATCH_BATCH_SIZE = int(os.getenv("MATCH_BATCH_SIZE", "80"))

# MinIO / S3-compatible storage
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", "minioadmin"))
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"))
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "profiles")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("1", "true", "yes")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000").rstrip("/")


def require_token() -> str:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    return BOT_TOKEN


def contact_display() -> str:
    if CONTACT_INFO:
        return CONTACT_INFO
    if CONTACT_USERNAME:
        return f"@{CONTACT_USERNAME}"
    if BOT_USERNAME:
        return f"@{BOT_USERNAME}"
    return "از طریق پشتیبانی ربات پیام بده."
