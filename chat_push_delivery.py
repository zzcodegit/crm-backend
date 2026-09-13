"""Доставка push/webpush для чата и звонков."""

from __future__ import annotations

from urllib.parse import urlencode

from sqlalchemy.orm import Session

from models import PushDeviceToken, User, WebPushSubscription
from push_service import send_push_to_tokens
from webpush_service import send_web_push


def chat_open_url_from_data(data: dict[str, str] | None) -> str:
    """Deep-link на главную с openChat=1 — открывает боковую панель чата, не страницу /chat."""
    d = data or {}
    params: dict[str, str] = {"openChat": "1"}
    chat_type = (d.get("chatType") or d.get("chat_type") or "").strip()
    if chat_type:
        params["chatType"] = chat_type
    if d.get("dialogId"):
        params["dialogId"] = str(d["dialogId"])
    if d.get("messageId"):
        params["messageId"] = str(d["messageId"])
    if d.get("threadUserId"):
        params["threadUserId"] = str(d["threadUserId"])
    if d.get("userId"):
        params["userId"] = str(d["userId"])
    if d.get("username"):
        params["username"] = str(d["username"])
    return f"/?{urlencode(params)}"


def send_chat_push_to_users(
    db: Session,
    *,
    user_ids: list[int],
    title: str,
    body: str,
    data: dict[str, str],
) -> None:
    if not user_ids:
        return
    allowed_ids = [
        uid
        for (uid,) in db.query(User.id)
        .filter(User.id.in_(user_ids), User.chat_notifications_enabled.is_(True))
        .all()
    ]
    if not allowed_ids:
        return
    payload = dict(data or {})
    if not payload.get("url"):
        payload["url"] = chat_open_url_from_data(payload)
    tokens = [
        row.token
        for row in db.query(PushDeviceToken)
        .filter(PushDeviceToken.user_id.in_(allowed_ids), PushDeviceToken.is_active == True)
        .all()
    ]
    send_push_to_tokens(tokens=tokens, title=title, body=body, data=payload)
    web_rows = (
        db.query(WebPushSubscription)
        .filter(WebPushSubscription.user_id.in_(allowed_ids), WebPushSubscription.is_active == True)
        .all()
    )
    sent, invalid_endpoints = send_web_push(
        subscriptions=[
            {"endpoint": r.endpoint, "p256dh": r.p256dh, "auth": r.auth}
            for r in web_rows
        ],
        title=title,
        body=body,
        data=payload,
    )
    if sent >= 0 and invalid_endpoints:
        (
            db.query(WebPushSubscription)
            .filter(WebPushSubscription.endpoint.in_(invalid_endpoints))
            .update({WebPushSubscription.is_active: False}, synchronize_session=False)
        )
        db.commit()


def notify_incoming_private_call_push(
    db: Session,
    *,
    target_user_id: int,
    caller_user_id: int,
    caller_username: str,
    caller_display_name: str,
    call_id: str,
    dialog_id: int,
    video: bool,
) -> None:
    who = (caller_display_name or caller_username or "Пользователь").strip()
    media = "Видеозвонок" if video else "Звонок"
    send_chat_push_to_users(
        db,
        user_ids=[target_user_id],
        title="Входящий звонок",
        body=f"{media}: {who}",
        data={
            "type": "incoming_call",
            "call_id": call_id,
            "dialog_id": str(dialog_id),
            "from_user_id": str(caller_user_id),
            "from_username": caller_username or "",
            "from_display_name": caller_display_name or "",
            "video": "1" if video else "0",
            "url": "/",
        },
    )


def notify_incoming_group_call_push(
    db: Session,
    *,
    target_user_ids: list[int],
    starter_user_id: int,
    starter_username: str,
    starter_display_name: str,
    call_id: str,
    dialog_id: int,
    dialog_name: str,
    video: bool,
) -> None:
    who = (starter_display_name or starter_username or "Участник").strip()
    media = "Групповой видеозвонок" if video else "Групповой звонок"
    title = dialog_name.strip() or "Групповой звонок"
    for uid in target_user_ids:
        if uid == starter_user_id:
            continue
        send_chat_push_to_users(
            db,
            user_ids=[uid],
            title=title,
            body=f"{media}: {who}",
            data={
                "type": "incoming_group_call",
                "call_id": call_id,
                "dialog_id": str(dialog_id),
                "dialog_name": title,
                "from_user_id": str(starter_user_id),
                "from_username": starter_username or "",
                "from_display_name": starter_display_name or "",
                "video": "1" if video else "0",
                "url": "/",
            },
        )
