from __future__ import annotations

import logging
import mimetypes
import uuid
from functools import lru_cache
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from bot.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_PUBLIC_URL,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)
from bot.services.images import compress_profile_image

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if MINIO_SECURE else 'http'}://{MINIO_ENDPOINT}",
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_bucket() -> None:
    client = _client()
    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except ClientError:
        try:
            client.create_bucket(Bucket=MINIO_BUCKET)
            logger.info("Created MinIO bucket %s", MINIO_BUCKET)
        except ClientError as exc:
            logger.warning("Could not create bucket: %s", exc)


def upload_profile_photo(data: bytes, *, user_id: int) -> str:
    """Compress then upload; returns object key."""
    ensure_bucket()
    compressed = compress_profile_image(data)
    key = f"profiles/{user_id}/{uuid.uuid4().hex}.jpg"
    _client().put_object(
        Bucket=MINIO_BUCKET,
        Key=key,
        Body=compressed,
        ContentType="image/jpeg",
    )
    return key


def upload_bytes(
    data: bytes,
    *,
    user_id: int,
    content_type: str = "image/jpeg",
    ext: Optional[str] = None,
) -> str:
    """Legacy wrapper — profile uploads go through compress path."""
    return upload_profile_photo(data, user_id=user_id)


def download_bytes(key: str) -> Optional[bytes]:
    try:
        obj = _client().get_object(Bucket=MINIO_BUCKET, Key=key)
        return obj["Body"].read()
    except ClientError as exc:
        logger.warning("Download failed for %s: %s", key, exc)
        return None


def public_url(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return f"{MINIO_PUBLIC_URL}/{MINIO_BUCKET}/{key}"


def delete_object(key: str) -> None:
    try:
        _client().delete_object(Bucket=MINIO_BUCKET, Key=key)
    except ClientError as exc:
        logger.warning("Delete failed for %s: %s", key, exc)
