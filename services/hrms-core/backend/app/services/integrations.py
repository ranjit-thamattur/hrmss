"""Integrations behind one adapter each, so a failure never blocks HR work (decision 0003).

Biometric: BIOMETRIC_ADAPTER=excel (no device API: HR enrols on the device and uploads punch
files), mock (simulated device for demos/tests), http (vendor REST API, wired once the client
shares the API documents — SCRUM-120).
Messaging: everything goes to the outbox table; a sender is added when the WhatsApp Business
account exists (SCRUM-73).
Storage: local folder, or S3 when S3_BUCKET is set.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings

log = logging.getLogger("hrms.integrations")
settings = get_settings()


class BiometricError(Exception):
    pass


class BiometricAdapter:
    name = "base"
    manual = False  # True: someone must enrol the person on the device by hand

    def provision(self, employee: m.Employee) -> str:
        raise NotImplementedError

    def deprovision(self, employee: m.Employee) -> None:
        raise NotImplementedError

    def fetch_punches(self, since: datetime) -> list[tuple[str, datetime, str]]:
        return []


class ExcelBiometric(BiometricAdapter):
    name, manual = "excel", True

    def provision(self, employee: m.Employee) -> str:
        return employee.code  # device user id = employee code; enrolment done at the device

    def deprovision(self, employee: m.Employee) -> None:
        return None


class MockBiometric(BiometricAdapter):
    name = "mock"
    enrolled: set[str] = set()

    def provision(self, employee: m.Employee) -> str:
        self.enrolled.add(employee.code)
        return employee.code

    def deprovision(self, employee: m.Employee) -> None:
        self.enrolled.discard(employee.code)


class HttpBiometric(BiometricAdapter):
    """Generic REST shape; adjust paths to the vendor's API once the documents arrive."""
    name = "http"

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        import httpx

        if not settings.biometric_api_url:
            raise BiometricError("BIOMETRIC_API_URL is not set")
        try:
            r = httpx.request(method, settings.biometric_api_url.rstrip("/") + path, timeout=15,
                              headers={"Authorization": f"Bearer {settings.biometric_api_key or ''}"}, **kw)
            r.raise_for_status()
            return r.json() if r.content else None
        except httpx.HTTPError as e:
            raise BiometricError(str(e)) from e

    def provision(self, employee: m.Employee) -> str:
        data = self._req("POST", "/users", json={"userId": employee.code, "name": f"{employee.first_name} {employee.last_name}".strip()})
        return str((data or {}).get("userId", employee.code))

    def deprovision(self, employee: m.Employee) -> None:
        self._req("DELETE", f"/users/{employee.biometric_id or employee.code}")

    def fetch_punches(self, since: datetime) -> list[tuple[str, datetime, str]]:
        rows = self._req("GET", "/punches", params={"since": since.isoformat()}) or []
        return [(r["userId"], datetime.fromisoformat(r["time"]), r.get("deviceId", "")) for r in rows]


def get_biometric() -> BiometricAdapter:
    return {"mock": MockBiometric, "http": HttpBiometric}.get(settings.biometric_adapter, ExcelBiometric)()


def queue_message(db: Session, *, to: str | None, template: str, payload: dict[str, Any], employee_id: int | None = None,
                  channel: str = "whatsapp") -> None:
    if not to:
        return
    db.add(m.Outbox(channel=channel, to=to, template=template, payload=payload, employee_id=employee_id))


def save_file(key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
    if settings.s3_bucket:
        import boto3

        boto3.client("s3").put_object(Bucket=settings.s3_bucket, Key=key, Body=content, ContentType=content_type, ServerSideEncryption="aws:kms")
        return f"s3://{settings.s3_bucket}/{key}"
    p = Path(settings.storage_dir) / key
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return str(p)


def read_file(ref: str) -> bytes:
    if ref.startswith("s3://"):
        import boto3

        bucket, key = ref[5:].split("/", 1)
        return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    return Path(ref).read_bytes()
