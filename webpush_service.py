from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Iterable

from config import settings

_VAPID_DIR = Path("/home/crm-backend")
_VAPID_PRIVATE_FILE = _VAPID_DIR / "webpush-vapid-private.pem"
_VAPID_PUBLIC_FILE = _VAPID_DIR / "webpush-vapid-public.txt"

def _ensure_vapid_keys() -> tuple[str, str] | None:
    """
    Returns (public_key_base64url, private_key_pem_or_path).
    If settings are not provided, auto-generates and stores local key files.
    """
    cfg_public = (settings.webpush_vapid_public_key or "").strip()
    cfg_private = (settings.webpush_vapid_private_key or "").strip()
    if cfg_public and cfg_private:
        return cfg_public, cfg_private
    if _VAPID_PRIVATE_FILE.exists() and _VAPID_PUBLIC_FILE.exists():
        pub = _VAPID_PUBLIC_FILE.read_text(encoding="utf-8").strip()
        if pub:
            return pub, str(_VAPID_PRIVATE_FILE)
    try:
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid
    except Exception:
        return None
    vapid = Vapid()
    vapid.generate_keys()
    private_pem = vapid.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64url = base64.urlsafe_b64encode(public_bytes).decode("utf-8").rstrip("=")
    _VAPID_PRIVATE_FILE.write_bytes(private_pem)
    _VAPID_PUBLIC_FILE.write_text(public_b64url, encoding="utf-8")
    return public_b64url, str(_VAPID_PRIVATE_FILE)


def get_webpush_public_key() -> str | None:
    ensured = _ensure_vapid_keys()
    if not ensured:
        return None
    return ensured[0]


def send_web_push(
    *,
    subscriptions: Iterable[dict],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> tuple[int, list[str]]:
    """
    Send Web Push notifications.
    Returns: (sent_count, invalid_endpoints)
    """
    ensured = _ensure_vapid_keys()
    if not ensured:
        return 0, []
    _, private_key = ensured
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        return 0, []

    payload = json.dumps(
        {
            "title": title,
            "body": body,
            "data": data or {},
        },
        ensure_ascii=False,
    )
    sent = 0
    invalid: list[str] = []
    for sub in subscriptions:
        endpoint = str(sub.get("endpoint") or "").strip()
        p256dh = str(sub.get("p256dh") or "").strip()
        auth = str(sub.get("auth") or "").strip()
        if not endpoint or not p256dh or not auth:
            continue
        try:
            webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys": {"p256dh": p256dh, "auth": auth},
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": settings.webpush_vapid_subject},
                ttl=120,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                invalid.append(endpoint)
            continue
        except Exception:
            continue
    return sent, invalid
