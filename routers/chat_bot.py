"""Чат-бот поддержки: пользователь видит свой тред, администратор — все."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from database import get_db
from deps import get_chat_user
from models import ChatBotThreadMeta, ChatMessage, ChatMessageAttachment, ChatMessageRead, User
from routers.chat import (
    MAX_AUDIO_SIZE,
    MAX_IMAGE_SIZE,
    MAX_STICKER_SIZE,
    MAX_VIDEO_SIZE,
    UPLOAD_DIR,
    _allowed_media_for_upload,
    _chat_admin_user_ids,
    _is_chat_admin,
    _messages_to_responses,
    _send_chat_push_to_users,
    _stored_upload_filename,
    _to_message_response,
)
from chat_service import user_display_name
from schemas import ChatBotThreadItem, ChatMessageResponse, ChatUserShortResponse

router = APIRouter(prefix="/api/chat/bot", tags=["chat-bot"])


def _resolve_thread_user_id(current_user: User, thread_user_id: int | None) -> int:
    if _is_chat_admin(current_user):
        if thread_user_id is None or thread_user_id <= 0:
            raise HTTPException(status_code=400, detail="Укажите thread_user_id")
        return int(thread_user_id)
    return int(current_user.id)


def _require_thread_user(db: Session, thread_user_id: int) -> User:
    u = db.query(User).filter(User.id == thread_user_id, User.is_active == True).first()
    if not u:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return u


def _bot_messages_query(db: Session, thread_user_id: int):
    return (
        db.query(ChatMessage)
        .options(selectinload(ChatMessage.attachments), selectinload(ChatMessage.sender))
        .filter(
            ChatMessage.bot_thread_user_id == thread_user_id,
            ChatMessage.private_dialog_id.is_(None),
            ChatMessage.group_dialog_id.is_(None),
            ChatMessage.gigachat_thread_user_id.is_(None),
        )
    )


def _reopen_bot_thread(db: Session, thread_user_id: int) -> None:
    meta = db.query(ChatBotThreadMeta).filter(ChatBotThreadMeta.user_id == thread_user_id).first()
    if not meta or meta.closed_at is None:
        return
    meta.closed_at = None
    meta.closed_by_user_id = None


def _bot_unread_count(db: Session, *, thread_user_id: int, reader_user_id: int) -> int:
    admin_ids = _chat_admin_user_ids(db)
    is_admin_reader = reader_user_id in admin_ids

    if is_admin_reader:
        if not admin_ids:
            return 0
        unread_filter = ~db.query(ChatMessageRead.id).filter(
            ChatMessageRead.user_id.in_(admin_ids),
            ChatMessageRead.message_id == ChatMessage.id,
        ).exists()
        return int(
            db.query(func.count(ChatMessage.id))
            .filter(
                ChatMessage.bot_thread_user_id == thread_user_id,
                ChatMessage.sender_user_id.isnot(None),
                ChatMessage.sender_user_id.notin_(admin_ids),
                ChatMessage.is_deleted == False,
                unread_filter,
            )
            .scalar()
            or 0
        )

    unread_filter = ~db.query(ChatMessageRead.id).filter(
        ChatMessageRead.user_id == reader_user_id,
        ChatMessageRead.message_id == ChatMessage.id,
    ).exists()
    return int(
        db.query(func.count(ChatMessage.id))
        .filter(
            ChatMessage.bot_thread_user_id == thread_user_id,
            ChatMessage.sender_user_id.isnot(None),
            ChatMessage.sender_user_id != reader_user_id,
            ChatMessage.is_deleted == False,
            unread_filter,
        )
        .scalar()
        or 0
    )


@router.get("/threads", response_model=list[ChatBotThreadItem])
def list_bot_threads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    if not _is_chat_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ только для администраторов")

    thread_ids = [
        int(r[0])
        for r in db.query(ChatMessage.bot_thread_user_id)
        .filter(ChatMessage.bot_thread_user_id.isnot(None))
        .distinct()
        .all()
        if r[0] is not None
    ]
    if not thread_ids:
        return []

    users = {u.id: u for u in db.query(User).filter(User.id.in_(thread_ids)).all()}
    metas = {
        int(m.user_id): m
        for m in db.query(ChatBotThreadMeta).filter(ChatBotThreadMeta.user_id.in_(thread_ids)).all()
    }
    out: list[ChatBotThreadItem] = []
    for tid in thread_ids:
        u = users.get(tid)
        if not u:
            continue
        meta = metas.get(tid)
        is_closed = meta is not None and meta.closed_at is not None
        last = (
            _bot_messages_query(db, tid)
            .order_by(ChatMessage.id.desc())
            .first()
        )
        out.append(
            ChatBotThreadItem(
                user=ChatUserShortResponse(
                    id=u.id,
                    username=u.username,
                    display_name=user_display_name(u),
                    is_active=bool(u.is_active),
                    avatar_url=u.avatar_url,
                ),
                last_message_text=last.text if last and not last.is_deleted else None,
                last_message_at=last.created_at if last else None,
                unread_count=_bot_unread_count(db, thread_user_id=tid, reader_user_id=current_user.id),
                is_closed=is_closed,
                closed_at=meta.closed_at if is_closed and meta else None,
            )
        )

    def _sort_key(x: ChatBotThreadItem) -> tuple:
        ts = 0.0
        if x.last_message_at is not None:
            dt = x.last_message_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = dt.timestamp()
        return (1 if x.is_closed else 0, -ts)

    out.sort(key=_sort_key)
    return out


@router.post("/threads/{thread_user_id}/close", status_code=204)
def close_bot_thread(
    thread_user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    if not _is_chat_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ только для администраторов")
    tid = int(thread_user_id)
    _require_thread_user(db, tid)
    has_messages = (
        db.query(ChatMessage.id)
        .filter(ChatMessage.bot_thread_user_id == tid)
        .limit(1)
        .first()
    )
    if not has_messages:
        raise HTTPException(status_code=404, detail="Обращение не найдено")

    meta = db.query(ChatBotThreadMeta).filter(ChatBotThreadMeta.user_id == tid).first()
    if meta is None:
        meta = ChatBotThreadMeta(user_id=tid)
        db.add(meta)
    meta.closed_at = datetime.now(timezone.utc)
    meta.closed_by_user_id = current_user.id
    db.commit()
    return None


@router.get("/messages", response_model=list[ChatMessageResponse])
def bot_messages(
    thread_user_id: int | None = Query(None),
    after_id: int | None = Query(None),
    before_id: int | None = Query(None),
    around_id: int | None = Query(None),
    limit: int = Query(80, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    tid = _resolve_thread_user_id(current_user, thread_user_id)
    _require_thread_user(db, tid)

    q = _bot_messages_query(db, tid)
    if around_id is not None:
        half = max(limit // 2, 20)
        before_msgs = list(
            reversed(
                q.filter(ChatMessage.id < around_id).order_by(ChatMessage.id.desc()).limit(half).all()
            )
        )
        center = q.filter(ChatMessage.id == around_id).first()
        after_msgs = list(q.filter(ChatMessage.id > around_id).order_by(ChatMessage.id.asc()).limit(half).all())
        msgs = before_msgs + ([center] if center else []) + after_msgs
    else:
        if after_id is not None:
            q = q.filter(ChatMessage.id > after_id)
        if before_id is not None:
            q = q.filter(ChatMessage.id < before_id)
        msgs = list(reversed(q.order_by(ChatMessage.id.desc()).limit(limit).all()))

    return _messages_to_responses(db, msgs, current_user)


@router.post("/messages", response_model=ChatMessageResponse, status_code=201)
async def bot_send(
    text: str | None = Form(None),
    thread_user_id: int | None = Form(None),
    reply_to_message_id: int | None = Form(None),
    is_voice_note: bool = Form(False),
    is_video_note: bool = Form(False),
    is_sticker: bool = Form(False),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    tid = _resolve_thread_user_id(current_user, thread_user_id)
    _require_thread_user(db, tid)

    text_val = (text or "").strip() or None
    if not text_val and not files:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    if reply_to_message_id is not None:
        reply_to = db.query(ChatMessage).filter(ChatMessage.id == reply_to_message_id).first()
        if not reply_to or reply_to.bot_thread_user_id != tid:
            raise HTTPException(status_code=400, detail="Нельзя отвечать на сообщение из другого обращения")

    msg = ChatMessage(
        private_dialog_id=None,
        group_dialog_id=None,
        bot_thread_user_id=tid,
        sender_user_id=current_user.id,
        text=text_val,
        is_deleted=False,
        reply_to_message_id=reply_to_message_id,
    )
    db.add(msg)
    db.flush()

    if int(current_user.id) == tid:
        _reopen_bot_thread(db, tid)

    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        media_type, ok = _allowed_media_for_upload(
            f.filename, f.content_type, is_voice_note=is_voice_note, is_video_note=is_video_note, is_sticker=is_sticker
        )
        if not ok:
            raise HTTPException(status_code=400, detail="Недопустимый тип файла")

        content = await f.read()
        if media_type == "image" and len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="Файл изображения слишком большой")
        if media_type == "video" and len(content) > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=400, detail="Файл видео слишком большой")
        if media_type == "audio" and len(content) > MAX_AUDIO_SIZE:
            raise HTTPException(status_code=400, detail="Аудиофайл слишком большой")
        if media_type == "sticker" and len(content) > MAX_STICKER_SIZE:
            raise HTTPException(status_code=400, detail="Стикер слишком большой")

        unique_filename, voice_mime = _stored_upload_filename(
            f.filename, ext, media_type, is_voice_note=is_voice_note, is_video_note=is_video_note
        )
        file_path = UPLOAD_DIR / unique_filename
        try:
            with open(file_path, "wb") as fp:
                fp.write(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e!s}")

        att = ChatMessageAttachment(
            message_id=msg.id,
            url=f"/uploads/{unique_filename}",
            media_type=media_type,
            filename=unique_filename,
            mime_type=voice_mime or f.content_type,
        )
        db.add(att)

    db.commit()
    db.refresh(msg)

    if int(current_user.id) == tid:
        push_ids = [uid for uid in _chat_admin_user_ids(db) if uid != current_user.id]
        push_title = "Новое обращение в поддержку"
    else:
        push_ids = [tid] if tid != current_user.id else []
        push_title = "Ответ поддержки"

    if push_ids:
        sender_name = user_display_name(current_user)
        _send_chat_push_to_users(
            db,
            user_ids=push_ids,
            title=push_title,
            body=text_val or f"{sender_name}: вложение",
            data={"chatType": "bot", "threadUserId": str(tid), "messageId": str(msg.id)},
        )

    return _to_message_response(
        msg,
        attachments=list(msg.attachments),
        include_sender=True,
        current_user_id=current_user.id,
        db=db,
    )


@router.post("/mark-read", status_code=204)
def bot_mark_read(
    thread_user_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    tid = _resolve_thread_user_id(current_user, thread_user_id)
    _require_thread_user(db, tid)

    admin_ids = _chat_admin_user_ids(db)
    if _is_chat_admin(current_user):
        if not admin_ids:
            return None
        unread_filter = ~db.query(ChatMessageRead.id).filter(
            ChatMessageRead.user_id.in_(admin_ids),
            ChatMessageRead.message_id == ChatMessage.id,
        ).exists()
        unread_ids = [
            int(row_id)
            for (row_id,) in db.query(ChatMessage.id)
            .filter(
                ChatMessage.bot_thread_user_id == tid,
                ChatMessage.sender_user_id.isnot(None),
                ChatMessage.sender_user_id.notin_(admin_ids),
                ChatMessage.is_deleted == False,
                unread_filter,
            )
            .all()
        ]
        if unread_ids:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            rows = [
                {"message_id": mid, "user_id": aid}
                for mid in unread_ids
                for aid in admin_ids
            ]
            stmt = pg_insert(ChatMessageRead.__table__).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["message_id", "user_id"])
            db.execute(stmt)
            db.commit()
        return None

    unread_filter = ~db.query(ChatMessageRead.id).filter(
        ChatMessageRead.user_id == current_user.id,
        ChatMessageRead.message_id == ChatMessage.id,
    ).exists()
    unread_ids = [
        int(row_id)
        for (row_id,) in db.query(ChatMessage.id)
        .filter(
            ChatMessage.bot_thread_user_id == tid,
            ChatMessage.sender_user_id.isnot(None),
            ChatMessage.sender_user_id != current_user.id,
            ChatMessage.is_deleted == False,
            unread_filter,
        )
        .all()
    ]
    if unread_ids:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        rows = [{"message_id": mid, "user_id": current_user.id} for mid in unread_ids]
        stmt = pg_insert(ChatMessageRead.__table__).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["message_id", "user_id"])
        db.execute(stmt)
        db.commit()
    return None
