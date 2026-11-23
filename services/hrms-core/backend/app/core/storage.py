"""Document files: a local folder on laptops (STORAGE_DIR), S3 in the client's AWS account (S3_BUCKET)."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from ..config import get_settings

settings = get_settings()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[-120:] or "file"


def save(client_id: int, file_name: str, data: bytes, content_type: str | None) -> str:
    key = f"{client_id}/documents/{uuid.uuid4().hex}-{_safe(file_name)}"
    if settings.s3_bucket:
        import boto3

        boto3.client("s3").put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type or "application/octet-stream",
                                      ServerSideEncryption="aws:kms")
    else:
        p = Path(settings.storage_dir) / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return key


def read(key: str) -> bytes:
    if settings.s3_bucket:
        import boto3

        return boto3.client("s3").get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    return (Path(settings.storage_dir) / key).read_bytes()
