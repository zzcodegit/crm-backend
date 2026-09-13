"""WebRTC-сигналинг для аудио/видеозвонков в чате."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, joinedload

from auth import decode_token
from chat_call_hub import WsClient, call_hub
from database import SessionLocal
from deps import get_chat_user
from models import GroupChatDialog, GroupChatMember, PrivateDialog, User
from routers.chat import _require_dialog_access, _require_group_active_member
from chat_service import user_display_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat/calls", tags=["chat-calls"])

def _build_ice_servers() -> list[dict]:
    """STUN по умолчанию; TURN — через CHAT_TURN_URLS (через запятую), CHAT_TURN_USERNAME, CHAT_TURN_CREDENTIAL."""
    servers: list[dict] = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
    ]
    turn_urls_raw = (os.environ.get("CHAT_TURN_URLS") or os.environ.get("TURN_URLS") or "").strip()
    if not turn_urls_raw:
        return servers
    turn_urls = [u.strip() for u in turn_urls_raw.split(",") if u.strip()]
    if not turn_urls:
        return servers
    turn_entry: dict = {"urls": turn_urls}
    username = (os.environ.get("CHAT_TURN_USERNAME") or os.environ.get("TURN_USERNAME") or "").strip()
    credential = (os.environ.get("CHAT_TURN_CREDENTIAL") or os.environ.get("TURN_CREDENTIAL") or "").strip()
    if username:
        turn_entry["username"] = username
    if credential:
        turn_entry["credential"] = credential
    servers.append(turn_entry)
    return servers


ICE_SERVERS = _build_ice_servers()


@router.get("/ice-servers")
def get_ice_servers(_: User = Depends(get_chat_user)):
    return {"iceServers": ICE_SERVERS}


def _load_user(db: Session, username: str) -> User | None:
    return (
        db.query(User)
        .options(joinedload(User.groups))
        .filter(User.username == username, User.is_active == True)
        .first()
    )


def _private_other_user_id(dialog: PrivateDialog, user_id: int) -> int:
    return dialog.user2_id if dialog.user1_id == user_id else dialog.user1_id


def _group_member_ids(db: Session, dialog_id: int) -> list[int]:
    rows = (
        db.query(GroupChatMember.user_id)
        .filter(GroupChatMember.dialog_id == dialog_id, GroupChatMember.is_active == True)
        .all()
    )
    return [int(r[0]) for r in rows]


async def _handle_ws_message(client: WsClient, data: dict) -> None:
    msg_type = (data.get("type") or "").strip()
    db = SessionLocal()
    try:
        if msg_type == "ping":
            await call_hub.send_to_user(client.user_id, {"type": "pong"})
            return

        if msg_type == "call_invite":
            dialog_id = int(data.get("dialog_id") or 0)
            target_user_id = int(data.get("target_user_id") or 0)
            sdp = data.get("sdp")
            if dialog_id <= 0 or target_user_id <= 0:
                return
            user = _load_user(db, client.username)
            if not user:
                return
            dialog = _require_dialog_access(db, user, dialog_id)
            other = _private_other_user_id(dialog, user.id)
            if target_user_id != other:
                await call_hub.send_to_user(client.user_id, {"type": "call_error", "message": "Неверный собеседник"})
                return
            await call_hub.create_private_call(
                caller=client,
                dialog_id=dialog_id,
                target_user_id=target_user_id,
                sdp=str(sdp) if sdp else None,
                video=bool(data.get("video")),
            )
            return

        if msg_type == "call_accept":
            call_id = str(data.get("call_id") or "")
            sdp = data.get("sdp")
            if not call_id or not sdp:
                return
            await call_hub.accept_private_call(callee=client, call_id=call_id, sdp=str(sdp))
            return

        if msg_type == "call_decline":
            call_id = str(data.get("call_id") or "")
            if call_id:
                await call_hub.decline_call(client.user_id, call_id)
            return

        if msg_type == "call_hangup":
            call_id = str(data.get("call_id") or "")
            if call_id:
                await call_hub.hangup(client.user_id, call_id)
            return

        if msg_type == "group_call_start":
            dialog_id = int(data.get("dialog_id") or 0)
            if dialog_id <= 0:
                return
            user = _load_user(db, client.username)
            if not user:
                return
            _require_group_active_member(db, user, dialog_id)
            members = _group_member_ids(db, dialog_id)
            dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
            dialog_name = dialog.name if dialog else "Группа"
            await call_hub.start_group_call(
                starter=client,
                dialog_id=dialog_id,
                member_user_ids=members,
                dialog_name=dialog_name,
                video=bool(data.get("video")),
            )
            return

        if msg_type == "group_call_join":
            call_id = str(data.get("call_id") or "")
            if not call_id:
                return
            await call_hub.join_group_call(joiner=client, call_id=call_id)
            return

        if msg_type == "webrtc_offer":
            call_id = str(data.get("call_id") or "")
            to_user_id = int(data.get("to_user_id") or 0)
            sdp = data.get("sdp")
            if call_id and to_user_id and sdp:
                await call_hub.relay_sdp(
                    from_user_id=client.user_id,
                    call_id=call_id,
                    to_user_id=to_user_id,
                    msg_type="webrtc_offer",
                    sdp=str(sdp),
                )
            return

        if msg_type == "webrtc_answer":
            call_id = str(data.get("call_id") or "")
            to_user_id = int(data.get("to_user_id") or 0)
            sdp = data.get("sdp")
            if call_id and to_user_id and sdp:
                await call_hub.relay_sdp(
                    from_user_id=client.user_id,
                    call_id=call_id,
                    to_user_id=to_user_id,
                    msg_type="webrtc_answer",
                    sdp=str(sdp),
                )
            return

        if msg_type == "webrtc_ice":
            call_id = str(data.get("call_id") or "")
            to_user_id = int(data.get("to_user_id") or 0)
            candidate = data.get("candidate")
            if call_id and to_user_id and isinstance(candidate, dict):
                await call_hub.relay_ice(
                    from_user_id=client.user_id,
                    call_id=call_id,
                    to_user_id=to_user_id,
                    candidate=candidate,
                )
            return
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "Нет доступа"
        await call_hub.send_to_user(client.user_id, {"type": "call_error", "message": detail})
    except Exception as e:
        logger.exception("chat call ws message error: %s", e)
        await call_hub.send_to_user(client.user_id, {"type": "call_error", "message": "Ошибка звонка"})
    finally:
        db.close()


@router.websocket("/ws")
async def calls_websocket(websocket: WebSocket, token: str = Query(...)):
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        user = _load_user(db, str(payload["sub"]))
        if not user:
            await websocket.close(code=4401)
            return
        from deps import is_price_user

        if is_price_user(user):
            await websocket.close(code=4403)
            return
    finally:
        db.close()

    await websocket.accept()
    client = WsClient(
        user_id=user.id,
        username=user.username,
        display_name=user_display_name(user),
        websocket=websocket,
    )
    await call_hub.register(client)
    await call_hub.send_to_user(client.user_id, {"type": "connected", "user_id": client.user_id})

    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, dict):
                await _handle_ws_message(client, data)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("chat call ws: %s", e)
    finally:
        await call_hub.unregister(client)
