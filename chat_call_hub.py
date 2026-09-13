"""Сигналинг аудиозвонков (WebRTC) в памяти процесса."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from chat_push_delivery import notify_incoming_group_call_push, notify_incoming_private_call_push
from chat_service import add_private_call_log_message, private_call_log_text
from database import SessionLocal

logger = logging.getLogger(__name__)

RING_TIMEOUT_SEC = 45


@dataclass
class WsClient:
    user_id: int
    username: str
    display_name: str
    websocket: WebSocket


@dataclass
class CallSession:
    call_id: str
    kind: str  # private | group
    dialog_id: int
    caller_id: int
    callee_id: int | None = None
    video: bool = False
    participant_ids: set[int] = field(default_factory=set)
    state: str = "ringing"  # ringing | active | ended
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    answered_at: datetime | None = None
    offer_sdp: str | None = None
    caller_username: str = ""
    caller_display_name: str = ""
    dialog_name: str = ""


class ChatCallHub:
    def __init__(self) -> None:
        self._clients: dict[int, list[WsClient]] = {}
        self._calls: dict[str, CallSession] = {}
        self._user_call: dict[int, str] = {}

    def _peer_payload(self, user_id: int, username: str, display_name: str) -> dict[str, Any]:
        return {"user_id": user_id, "username": username, "display_name": display_name}

    def _push_incoming_private_call(
        self,
        *,
        target_user_id: int,
        caller_user_id: int,
        caller_username: str,
        caller_display_name: str,
        call_id: str,
        dialog_id: int,
        video: bool,
    ) -> None:
        db = SessionLocal()
        try:
            notify_incoming_private_call_push(
                db,
                target_user_id=target_user_id,
                caller_user_id=caller_user_id,
                caller_username=caller_username,
                caller_display_name=caller_display_name,
                call_id=call_id,
                dialog_id=dialog_id,
                video=video,
            )
        except Exception:
            logger.exception("incoming call push failed call_id=%s", call_id)
        finally:
            db.close()

    def _push_incoming_group_call(
        self,
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
        db = SessionLocal()
        try:
            notify_incoming_group_call_push(
                db,
                target_user_ids=target_user_ids,
                starter_user_id=starter_user_id,
                starter_username=starter_username,
                starter_display_name=starter_display_name,
                call_id=call_id,
                dialog_id=dialog_id,
                dialog_name=dialog_name,
                video=video,
            )
        except Exception:
            logger.exception("incoming group call push failed call_id=%s", call_id)
        finally:
            db.close()

    async def _resync_ringing_calls(self, client: WsClient) -> None:
        for call in list(self._calls.values()):
            if call.state != "ringing":
                continue
            if call.kind == "private" and call.callee_id == client.user_id:
                await self.send_to_user(
                    client.user_id,
                    {
                        "type": "incoming_call",
                        "call_id": call.call_id,
                        "kind": "private",
                        "dialog_id": call.dialog_id,
                        "from": self._peer_payload(
                            call.caller_id,
                            call.caller_username,
                            call.caller_display_name,
                        ),
                        "sdp": call.offer_sdp,
                        "video": bool(call.video),
                    },
                )
            elif (
                call.kind == "group"
                and client.user_id not in call.participant_ids
                and call.state != "ended"
            ):
                await self.send_to_user(
                    client.user_id,
                    {
                        "type": "incoming_group_call",
                        "call_id": call.call_id,
                        "dialog_id": call.dialog_id,
                        "dialog_name": call.dialog_name or "Группа",
                        "video": bool(call.video),
                        "from": self._peer_payload(
                            call.caller_id,
                            call.caller_username,
                            call.caller_display_name,
                        ),
                        "participants": [
                            self._peer_payload(
                                call.caller_id,
                                call.caller_username,
                                call.caller_display_name,
                            ),
                        ],
                    },
                )

    async def register(self, client: WsClient) -> None:
        self._clients.setdefault(client.user_id, []).append(client)
        await self._resync_ringing_calls(client)

    async def unregister(self, client: WsClient) -> None:
        lst = self._clients.get(client.user_id, [])
        self._clients[client.user_id] = [c for c in lst if c.websocket is not client.websocket]
        if not self._clients[client.user_id]:
            del self._clients[client.user_id]
        call_id = self._user_call.get(client.user_id)
        if call_id:
            await self._leave_call(client.user_id, call_id, reason="disconnect")

    async def _send_json(self, ws: WebSocket, payload: dict[str, Any]) -> None:
        try:
            await ws.send_json(payload)
        except Exception:
            pass

    async def send_to_user(self, user_id: int, payload: dict[str, Any]) -> None:
        for client in list(self._clients.get(user_id, [])):
            await self._send_json(client.websocket, payload)

    async def broadcast_call(
        self,
        call_id: str,
        payload: dict[str, Any],
        *,
        exclude_user_id: int | None = None,
    ) -> None:
        call = self._calls.get(call_id)
        if not call:
            return
        for uid in list(call.participant_ids):
            if exclude_user_id is not None and uid == exclude_user_id:
                continue
            await self.send_to_user(uid, payload)

    def _set_user_call(self, user_id: int, call_id: str | None) -> None:
        if call_id is None:
            self._user_call.pop(user_id, None)
        else:
            self._user_call[user_id] = call_id

    def user_busy(self, user_id: int) -> bool:
        return user_id in self._user_call

    async def create_private_call(
        self,
        *,
        caller: WsClient,
        dialog_id: int,
        target_user_id: int,
        sdp: str | None,
        video: bool = False,
    ) -> CallSession | None:
        if self.user_busy(caller.user_id) or self.user_busy(target_user_id):
            await self.send_to_user(caller.user_id, {"type": "call_error", "message": "Абонент занят"})
            return None

        call_id = str(uuid.uuid4())
        call = CallSession(
            call_id=call_id,
            kind="private",
            dialog_id=dialog_id,
            caller_id=caller.user_id,
            callee_id=target_user_id,
            video=bool(video),
            participant_ids={caller.user_id},
            state="ringing",
            offer_sdp=sdp,
            caller_username=caller.username,
            caller_display_name=caller.display_name,
        )
        self._calls[call_id] = call
        self._set_user_call(caller.user_id, call_id)
        asyncio.create_task(self._ring_timeout(call_id, RING_TIMEOUT_SEC))

        await self.send_to_user(
            target_user_id,
            {
                "type": "incoming_call",
                "call_id": call_id,
                "kind": "private",
                "dialog_id": dialog_id,
                "from": self._peer_payload(caller.user_id, caller.username, caller.display_name),
                "sdp": sdp,
                "video": bool(video),
            },
        )
        await asyncio.to_thread(
            self._push_incoming_private_call,
            target_user_id=target_user_id,
            caller_user_id=caller.user_id,
            caller_username=caller.username,
            caller_display_name=caller.display_name,
            call_id=call_id,
            dialog_id=dialog_id,
            video=bool(video),
        )
        await self.send_to_user(
            caller.user_id,
            {
                "type": "call_ringing",
                "call_id": call_id,
                "kind": "private",
                "dialog_id": dialog_id,
                "target_user_id": target_user_id,
                "video": bool(video),
            },
        )
        return call

    async def accept_private_call(
        self,
        *,
        callee: WsClient,
        call_id: str,
        sdp: str,
    ) -> None:
        call = self._calls.get(call_id)
        if not call or call.kind != "private" or call.state == "ended":
            await self.send_to_user(callee.user_id, {"type": "call_error", "message": "Звонок не найден"})
            return
        call.state = "active"
        call.answered_at = datetime.now(timezone.utc)
        call.participant_ids.add(callee.user_id)
        self._set_user_call(callee.user_id, call_id)
        await self.send_to_user(
            call.caller_id,
            {
                "type": "call_accepted",
                "call_id": call_id,
                "from": self._peer_payload(callee.user_id, callee.username, callee.display_name),
                "sdp": sdp,
            },
        )
        await self.send_to_user(
            callee.user_id,
            {
                "type": "call_active",
                "call_id": call_id,
                "kind": "private",
                "dialog_id": call.dialog_id,
                "participants": [
                    self._peer_payload(callee.user_id, callee.username, callee.display_name),
                ],
            },
        )

    async def start_group_call(
        self,
        *,
        starter: WsClient,
        dialog_id: int,
        member_user_ids: list[int],
        dialog_name: str = "Группа",
        video: bool = False,
    ) -> CallSession | None:
        if self.user_busy(starter.user_id):
            await self.send_to_user(starter.user_id, {"type": "call_error", "message": "Вы уже в звонке"})
            return None

        call_id = str(uuid.uuid4())
        call = CallSession(
            call_id=call_id,
            kind="group",
            dialog_id=dialog_id,
            caller_id=starter.user_id,
            video=bool(video),
            participant_ids={starter.user_id},
            state="active",
            caller_username=starter.username,
            caller_display_name=starter.display_name,
            dialog_name=dialog_name,
        )
        self._calls[call_id] = call
        self._set_user_call(starter.user_id, call_id)

        starter_peer = self._peer_payload(starter.user_id, starter.username, starter.display_name)
        await self.send_to_user(
            starter.user_id,
            {
                "type": "group_call_started",
                "call_id": call_id,
                "dialog_id": dialog_id,
                "dialog_name": dialog_name,
                "video": bool(video),
                "participants": [starter_peer],
            },
        )

        invitee_ids = [uid for uid in member_user_ids if uid != starter.user_id]
        for uid in invitee_ids:
            await self.send_to_user(
                uid,
                {
                    "type": "incoming_group_call",
                    "call_id": call_id,
                    "dialog_id": dialog_id,
                    "dialog_name": dialog_name,
                    "video": bool(video),
                    "from": starter_peer,
                    "participants": [starter_peer],
                },
            )
        if invitee_ids:
            await asyncio.to_thread(
                self._push_incoming_group_call,
                target_user_ids=invitee_ids,
                starter_user_id=starter.user_id,
                starter_username=starter.username,
                starter_display_name=starter.display_name,
                call_id=call_id,
                dialog_id=dialog_id,
                dialog_name=dialog_name,
                video=bool(video),
            )
        return call

    async def join_group_call(
        self,
        *,
        joiner: WsClient,
        call_id: str,
    ) -> None:
        call = self._calls.get(call_id)
        if not call or call.kind != "group" or call.state == "ended":
            await self.send_to_user(joiner.user_id, {"type": "call_error", "message": "Групповой звонок не найден"})
            return
        if self.user_busy(joiner.user_id) and self._user_call.get(joiner.user_id) != call_id:
            await self.send_to_user(joiner.user_id, {"type": "call_error", "message": "Вы уже в другом звонке"})
            return

        call.participant_ids.add(joiner.user_id)
        self._set_user_call(joiner.user_id, call_id)

        peers: list[dict[str, Any]] = []
        for uid in call.participant_ids:
            if uid == joiner.user_id:
                continue
            for c in self._clients.get(uid, []):
                peers.append(self._peer_payload(c.user_id, c.username, c.display_name))
                break

        joiner_peer = self._peer_payload(joiner.user_id, joiner.username, joiner.display_name)
        await self.send_to_user(
            joiner.user_id,
            {
                "type": "group_call_joined",
                "call_id": call_id,
                "dialog_id": call.dialog_id,
                "participants": peers,
            },
        )
        await self.broadcast_call(
            call_id,
            {"type": "peer_joined", "call_id": call_id, "peer": joiner_peer},
            exclude_user_id=joiner.user_id,
        )

    async def relay_sdp(
        self,
        *,
        from_user_id: int,
        call_id: str,
        to_user_id: int,
        msg_type: str,
        sdp: str,
    ) -> None:
        call = self._calls.get(call_id)
        if not call or call.state == "ended":
            return
        if from_user_id not in call.participant_ids or to_user_id not in call.participant_ids:
            return
        await self.send_to_user(
            to_user_id,
            {
                "type": msg_type,
                "call_id": call_id,
                "from_user_id": from_user_id,
                "sdp": sdp,
            },
        )

    async def relay_ice(
        self,
        *,
        from_user_id: int,
        call_id: str,
        to_user_id: int,
        candidate: dict[str, Any],
    ) -> None:
        call = self._calls.get(call_id)
        if not call or call.state == "ended":
            return
        if from_user_id not in call.participant_ids or to_user_id not in call.participant_ids:
            return
        await self.send_to_user(
            to_user_id,
            {
                "type": "webrtc_ice",
                "call_id": call_id,
                "from_user_id": from_user_id,
                "candidate": candidate,
            },
        )

    async def decline_call(self, user_id: int, call_id: str) -> None:
        call = self._calls.get(call_id)
        if not call:
            return
        await self.send_to_user(call.caller_id, {"type": "call_declined", "call_id": call_id, "from_user_id": user_id})
        if call.kind == "private":
            await self._end_call(call_id, reason="declined")

    async def _leave_call(self, user_id: int, call_id: str, *, reason: str) -> None:
        call = self._calls.get(call_id)
        if not call:
            self._set_user_call(user_id, None)
            return
        if user_id in call.participant_ids:
            call.participant_ids.discard(user_id)
        self._set_user_call(user_id, None)
        await self.broadcast_call(
            call_id,
            {"type": "peer_left", "call_id": call_id, "user_id": user_id, "reason": reason},
            exclude_user_id=user_id,
        )
        if call.kind == "private" or len(call.participant_ids) == 0:
            await self._end_call(call_id, reason=reason)

    async def hangup(self, user_id: int, call_id: str) -> None:
        await self._leave_call(user_id, call_id, reason="hangup")

    async def _ring_timeout(self, call_id: str, seconds: float) -> None:
        await asyncio.sleep(seconds)
        call = self._calls.get(call_id)
        if call and call.state == "ringing":
            await self._end_call(call_id, reason="timeout")

    def _persist_private_call_log(self, call: CallSession, *, was_connected: bool) -> None:
        if call.kind != "private":
            return
        db = SessionLocal()
        try:
            if was_connected:
                duration_sec = None
                if call.answered_at is not None:
                    duration_sec = max(0, int((datetime.now(timezone.utc) - call.answered_at).total_seconds()))
                text = private_call_log_text(missed=False, video=call.video, duration_sec=duration_sec)
            else:
                text = private_call_log_text(missed=True, video=call.video)
            add_private_call_log_message(db, dialog_id=call.dialog_id, text=text)
            db.commit()
        except Exception:
            logger.exception("failed to log call in chat dialog_id=%s", call.dialog_id)
            db.rollback()
        finally:
            db.close()

    async def _end_call(self, call_id: str, *, reason: str) -> None:
        call = self._calls.get(call_id)
        if not call:
            return
        was_connected = call.state == "active" or call.answered_at is not None
        call.state = "ended"
        for uid in list(call.participant_ids):
            self._set_user_call(uid, None)
            await self.send_to_user(
                uid,
                {
                    "type": "call_ended",
                    "call_id": call_id,
                    "reason": reason,
                    "dialog_id": call.dialog_id,
                    "kind": call.kind,
                },
            )
        if call.kind == "private":
            await asyncio.to_thread(self._persist_private_call_log, call, was_connected=was_connected)
        call.participant_ids.clear()
        self._calls.pop(call_id, None)


call_hub = ChatCallHub()
