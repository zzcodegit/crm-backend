from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from config import settings

_firebase_app = None


def _ensure_firebase():
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    try:
        import firebase_admin
        from firebase_admin import credentials
    except Exception:
        return None

    cred_path = Path(settings.firebase_credentials_file)
    if not cred_path.exists():
        # Optional: allow passing service account JSON directly via env.
        raw_json = (settings.firebase_credentials_json or "").strip()
        if raw_json:
            try:
                parsed = json.loads(raw_json)
                cred_path.parent.mkdir(parents=True, exist_ok=True)
                cred_path.write_text(json.dumps(parsed), encoding="utf-8")
            except Exception:
                return None
        else:
            return None

    try:
        options = {}
        if settings.firebase_project_id:
            options["projectId"] = settings.firebase_project_id
        _firebase_app = firebase_admin.initialize_app(
            credentials.Certificate(str(cred_path)),
            options=options or None,
        )
        return _firebase_app
    except Exception:
        return None


def send_push_to_tokens(*, tokens: Iterable[str], title: str, body: str, data: dict[str, str] | None = None) -> int:
    app = _ensure_firebase()
    if app is None:
        return 0

    try:
        from firebase_admin import messaging
    except Exception:
        return 0

    valid_tokens = [t for t in {x.strip() for x in tokens if x and x.strip()}]
    if not valid_tokens:
        return 0

    message_data = data or {}
    sent = 0
    for token in valid_tokens:
        msg = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data=message_data,
            android=messaging.AndroidConfig(priority="high"),
        )
        try:
            messaging.send(msg, app=app)
            sent += 1
        except Exception:
            continue
    return sent
