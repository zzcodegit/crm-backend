from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from chat_service import (
    EDIT_WINDOW_MINUTES,
    can_edit_message,
    ensure_general_chat_member,
    user_display_name,
)
from database import get_db
from deps import get_current_user, is_admin
from models import (
    ChatMessage,
    ChatMessageAttachment,
    ChatMessageRead,
    GeneralChatMember,
    PrivateDialog,
    GroupChatDialog,
    GroupChatMember,
    PushDeviceToken,
    User,
)
from push_service import send_push_to_tokens
from schemas import (
    ChatAttachmentResponse,
    ChatEditMessageRequest,
    ChatMessageResponse,
    ChatMessageSenderResponse,
    ChatUserShortResponse,
    PrivateDialogResponse,
    GroupChatDialogResponse,
    GroupChatDialogCreateRequest,
    GroupChatMemberResponse,
    ChatNotificationSummaryResponse,
    PushTokenRegisterRequest,
)


router = APIRouter(prefix="/api/chat", tags=["chat"])

UPLOAD_DIR = Path("/home/crm-backend/uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Разрешаем вложения только нужного типа
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm"}

# Лимиты по размеру (примерные, можно подстроить)
MAX_IMAGE_SIZE = 15 * 1024 * 1024  # 15MB
MAX_VIDEO_SIZE = 80 * 1024 * 1024  # 80MB


def _allowed_media(ext: str) -> tuple[str, bool]:
    ext = ext.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image", True
    if ext in VIDEO_EXTENSIONS:
        return "video", True
    return "", False


def _user_sender_to_response(u: User) -> ChatMessageSenderResponse:
    return ChatMessageSenderResponse(
        id=u.id,
        username=u.username,
        display_name=user_display_name(u),
    )


def _to_message_response(
    msg: ChatMessage,
    *,
    attachments: list[ChatMessageAttachment],
    include_sender: bool,
    current_user_id: int | None = None,
    db: Session | None = None,
) -> ChatMessageResponse:
    sender = _user_sender_to_response(msg.sender) if include_sender and msg.sender else None
    display_text = "Сообщение было удалено" if msg.is_deleted else msg.text
    attachments_out = [] if msg.is_deleted else attachments

    # Calculate is_read: message is read if the OTHER party has marked it as read
    is_read = False
    if current_user_id and db and msg.sender_user_id == current_user_id:
        # Only show read status for messages sent BY current user
        from models import ChatMessageRead
        # Check if anyone other than the sender has read this message
        read_count = db.query(ChatMessageRead).filter(
            ChatMessageRead.message_id == msg.id,
            ChatMessageRead.user_id != current_user_id
        ).count()
        is_read = read_count > 0

    return ChatMessageResponse(
        id=msg.id,
        private_dialog_id=msg.private_dialog_id,
        group_dialog_id=msg.group_dialog_id,
        sender=sender,
        display_text=display_text,
        is_deleted=msg.is_deleted,
        created_at=msg.created_at,
        edited_at=msg.edited_at,
        attachments=[
            ChatAttachmentResponse(
                id=a.id,
                url=a.url,
                media_type=a.media_type,
                filename=a.filename,
                mime_type=a.mime_type,
                created_at=a.created_at,
            )
            for a in attachments_out
        ],
        reply_to_message_id=msg.reply_to_message_id,
        reply_to_text=(
            "Сообщение было удалено"
            if msg.reply_to_message and msg.reply_to_message.is_deleted
            else (msg.reply_to_message.text if msg.reply_to_message else None)
        ),
        reply_to_sender_name=(
            user_display_name(msg.reply_to_message.sender)
            if msg.reply_to_message and msg.reply_to_message.sender
            else ("Система" if msg.reply_to_message and msg.reply_to_message.sender_user_id is None else None)
        ),
        reply_to_is_deleted=bool(msg.reply_to_message.is_deleted) if msg.reply_to_message else False,
        is_read=is_read,
    )


def _require_general_active_member(db: Session, user: User) -> GeneralChatMember:
    member = db.query(GeneralChatMember).filter(GeneralChatMember.user_id == user.id).first()
    if not member or not member.is_active:
        raise HTTPException(status_code=403, detail="Вы вышли из общего чата")
    return member


def _require_dialog_access(db: Session, user: User, dialog_id: int) -> PrivateDialog:
    dialog = db.query(PrivateDialog).filter(PrivateDialog.id == dialog_id).first()
    if not dialog:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    if dialog.user1_id != user.id and dialog.user2_id != user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к диалогу")
    return dialog


def _require_group_active_member(db: Session, user: User, dialog_id: int) -> GroupChatMember:
    member = db.query(GroupChatMember).filter(GroupChatMember.dialog_id == dialog_id, GroupChatMember.user_id == user.id).first()
    if not member or not member.is_active:
        raise HTTPException(status_code=403, detail="Нет доступа к группе")
    return member


def _require_group_admin(db: Session, user: User, dialog_id: int) -> GroupChatMember:
    member = _require_group_active_member(db, user, dialog_id)
    if not member.is_admin:
        raise HTTPException(status_code=403, detail="Только администратор группы может менять состав")
    return member


@router.get("/users", response_model=list[ChatUserShortResponse])
def list_users_for_chat(
    search: str | None = Query(None, description="Поиск по логину/именам"),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(User).filter(User.is_active == True).order_by(User.username)
    if search and search.strip():
        s = search.strip()
        q = q.filter(
            or_(
                User.username.ilike(f"%{s}%"),
                User.first_name.ilike(f"%{s}%"),
                User.last_name.ilike(f"%{s}%"),
                User.patronymic.ilike(f"%{s}%"),
            )
        )
    users = [u for u in q.limit(limit).all() if u.id != current_user.id]
    return [
        ChatUserShortResponse(
            id=u.id,
            username=u.username,
            display_name=user_display_name(u),
            is_active=bool(u.is_active),
        )
        for u in users
    ]


def _register_or_update_push_token(db: Session, *, user_id: int, token: str, platform: str) -> None:
    token = (token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Токен обязателен")
    platform = (platform or "android").strip().lower()

    existing_by_token = db.query(PushDeviceToken).filter(PushDeviceToken.token == token).first()
    if existing_by_token:
        existing_by_token.user_id = user_id
        existing_by_token.platform = platform
        existing_by_token.is_active = True
    else:
        db.add(PushDeviceToken(user_id=user_id, token=token, platform=platform, is_active=True))
    db.commit()


def _send_chat_push_to_users(db: Session, *, user_ids: list[int], title: str, body: str, data: dict[str, str]) -> None:
    if not user_ids:
        return
    tokens = [
        row.token
        for row in db.query(PushDeviceToken)
        .filter(PushDeviceToken.user_id.in_(user_ids), PushDeviceToken.is_active == True)
        .all()
    ]
    send_push_to_tokens(tokens=tokens, title=title, body=body, data=data)


@router.post("/push/register", status_code=204)
def register_push_token(
    payload: PushTokenRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _register_or_update_push_token(
        db,
        user_id=current_user.id,
        token=payload.token,
        platform=payload.platform,
    )
    return None


# --- General chat ---


@router.post("/general/join", status_code=204)
def general_join(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Разрешаем возвращаться в общий чат (обычно это нужно именно админам после "выйти").
    ensure_general_chat_member(db, current_user, desired_is_active=True, only_create=False)
    return None


@router.post("/general/leave", status_code=204)
def general_leave(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Только администратор может выходить из общего чата")

    ensure_general_chat_member(db, current_user, desired_is_active=False, only_create=False)
    return None


@router.get("/general/messages", response_model=list[ChatMessageResponse])
def general_messages(
    after_id: int | None = Query(None, description="Загрузить сообщения после id"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_general_active_member(db, current_user)

    q = db.query(ChatMessage).filter(
        ChatMessage.private_dialog_id.is_(None),
        ChatMessage.group_dialog_id.is_(None),
    )
    if after_id is not None:
        q = q.filter(ChatMessage.id > after_id)
    q = q.order_by(ChatMessage.id.desc()).limit(limit)
    msgs = list(reversed(q.all()))

    # подгружаем sender/attachments "вручную", так как у нас немного простая схема
    out: list[ChatMessageResponse] = []
    for m in msgs:
        # FastAPI/SQLAlchemy загрузит relationship лениво, но это ок для небольших лимитов
        atts = list(m.attachments or [])
        out.append(_to_message_response(
            m, 
            attachments=atts, 
            include_sender=m.sender_user_id is not None,
            current_user_id=current_user.id,
            db=db
        ))
    return out


@router.post("/general/messages", response_model=ChatMessageResponse, status_code=201)
async def general_send(
    text: str | None = Form(None),
    reply_to_message_id: int | None = Form(None),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_general_active_member(db, current_user)

    text_val = (text or "").strip() or None
    if not text_val and not files:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    if reply_to_message_id is not None:
        reply_to = db.query(ChatMessage).filter(ChatMessage.id == reply_to_message_id).first()
        if not reply_to:
            raise HTTPException(status_code=404, detail="Сообщение для ответа не найдено")
        if reply_to.private_dialog_id is not None or reply_to.group_dialog_id is not None:
            raise HTTPException(status_code=400, detail="Нельзя отвечать на сообщение из другого чата")

    msg = ChatMessage(
        private_dialog_id=None,
        sender_user_id=current_user.id,
        text=text_val,
        is_deleted=False,
        reply_to_message_id=reply_to_message_id,
    )
    db.add(msg)
    db.flush()

    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        media_type, ok = _allowed_media(ext)
        if not ok:
            raise HTTPException(status_code=400, detail="Недопустимый тип файла")

        # Сохраняем в uploads
        content = await f.read()
        if media_type == "image" and len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="Файл изображения слишком большой")
        if media_type == "video" and len(content) > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=400, detail="Файл видео слишком большой")

        unique_filename = f"{uuid.uuid4()}{ext}"
        file_path = UPLOAD_DIR / unique_filename
        try:
            with open(file_path, "wb") as fp:
                fp.write(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e!s}")

        url = f"/uploads/{unique_filename}"
        att = ChatMessageAttachment(
            message_id=msg.id,
            url=url,
            media_type=media_type,
            filename=unique_filename,
            mime_type=f.content_type,
        )
        db.add(att)

    db.commit()
    db.refresh(msg)
    recipients = [
        m.user_id
        for m in db.query(GeneralChatMember)
        .filter(GeneralChatMember.is_active == True, GeneralChatMember.user_id != current_user.id)
        .all()
    ]
    _send_chat_push_to_users(
        db,
        user_ids=recipients,
        title="Новое сообщение (Общий чат)",
        body=(text_val or "Вложение"),
        data={"chatType": "general", "messageId": str(msg.id)},
    )
    return _to_message_response(
        msg, 
        attachments=list(msg.attachments), 
        include_sender=True,
        current_user_id=current_user.id,
        db=db
    )


# --- Private dialogs ---


@router.get("/private/dialogs", response_model=list[PrivateDialogResponse])
def private_dialogs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dialogs = (
        db.query(PrivateDialog)
        .filter(or_(PrivateDialog.user1_id == current_user.id, PrivateDialog.user2_id == current_user.id))
        .order_by(PrivateDialog.created_at.desc())
        .all()
    )

    # Последнее сообщение для сортировки/витрины
    items: list[PrivateDialogResponse] = []
    for d in dialogs:
        other = d.user2 if d.user1_id == current_user.id else d.user1
        last = (
            db.query(ChatMessage)
            .filter(ChatMessage.private_dialog_id == d.id)
            .order_by(ChatMessage.id.desc())
            .first()
        )
        items.append(
            PrivateDialogResponse(
                id=d.id,
                other_user=ChatUserShortResponse(
                    id=other.id,
                    username=other.username,
                    display_name=user_display_name(other),
                    is_active=bool(other.is_active),
                ),
                last_message_text="Сообщение было удалено" if last and last.is_deleted else (last.text if last else None),
                last_message_at=last.created_at if last else None,
            )
        )

    def _sort_key(x: PrivateDialogResponse) -> float:
        dt = x.last_message_at
        if dt is None:
            return 0.0
        if dt.tzinfo is None:
            # считаем, что серверное время в UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    items.sort(key=_sort_key, reverse=True)
    return items


@router.post("/private/dialogs/{user_id}", response_model=dict)
def private_ensure_dialog(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя создать диалог с самим собой")

    other = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not other:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    dialog = (
        db.query(PrivateDialog)
        .filter(
            or_(
                (PrivateDialog.user1_id == current_user.id) & (PrivateDialog.user2_id == user_id),
                (PrivateDialog.user1_id == user_id) & (PrivateDialog.user2_id == current_user.id),
            )
        )
        .first()
    )
    if not dialog:
        dialog = PrivateDialog(user1_id=current_user.id, user2_id=user_id)
        db.add(dialog)
        db.commit()
        db.refresh(dialog)

    return {"id": dialog.id}


@router.get("/private/dialogs/{dialog_id}/messages", response_model=list[ChatMessageResponse])
def private_messages(
    dialog_id: int,
    after_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_dialog_access(db, current_user, dialog_id)

    q = db.query(ChatMessage).filter(ChatMessage.private_dialog_id == dialog_id)
    if after_id is not None:
        q = q.filter(ChatMessage.id > after_id)
    q = q.order_by(ChatMessage.id.desc()).limit(limit)
    msgs = list(reversed(q.all()))

    out: list[ChatMessageResponse] = []
    for m in msgs:
        out.append(_to_message_response(
            m, 
            attachments=list(m.attachments), 
            include_sender=m.sender_user_id is not None,
            current_user_id=current_user.id,
            db=db
        ))
    return out


@router.post("/private/dialogs/{dialog_id}/messages", response_model=ChatMessageResponse, status_code=201)
async def private_send(
    dialog_id: int,
    text: str | None = Form(None),
    reply_to_message_id: int | None = Form(None),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_dialog_access(db, current_user, dialog_id)

    text_val = (text or "").strip() or None
    if not text_val and not files:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    if reply_to_message_id is not None:
        reply_to = db.query(ChatMessage).filter(ChatMessage.id == reply_to_message_id).first()
        if not reply_to:
            raise HTTPException(status_code=404, detail="Сообщение для ответа не найдено")
        if reply_to.private_dialog_id != dialog_id:
            raise HTTPException(status_code=400, detail="Нельзя отвечать на сообщение из другого диалога")

    msg = ChatMessage(
        private_dialog_id=dialog_id,
        sender_user_id=current_user.id,
        text=text_val,
        is_deleted=False,
        reply_to_message_id=reply_to_message_id,
    )
    db.add(msg)
    db.flush()

    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        media_type, ok = _allowed_media(ext)
        if not ok:
            raise HTTPException(status_code=400, detail="Недопустимый тип файла")

        content = await f.read()
        if media_type == "image" and len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="Файл изображения слишком большой")
        if media_type == "video" and len(content) > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=400, detail="Файл видео слишком большой")

        unique_filename = f"{uuid.uuid4()}{ext}"
        file_path = UPLOAD_DIR / unique_filename
        try:
            with open(file_path, "wb") as fp:
                fp.write(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e!s}")

        url = f"/uploads/{unique_filename}"
        att = ChatMessageAttachment(
            message_id=msg.id,
            url=url,
            media_type=media_type,
            filename=unique_filename,
            mime_type=f.content_type,
        )
        db.add(att)

    db.commit()
    db.refresh(msg)
    dialog = _require_dialog_access(db, current_user, dialog_id)
    other_user_id = dialog.user2_id if dialog.user1_id == current_user.id else dialog.user1_id
    _send_chat_push_to_users(
        db,
        user_ids=[other_user_id],
        title=f"Новое сообщение ({user_display_name(current_user)})",
        body=(text_val or "Вложение"),
        data={"chatType": "private", "dialogId": str(dialog_id), "messageId": str(msg.id)},
    )
    return _to_message_response(
        msg, 
        attachments=list(msg.attachments), 
        include_sender=True,
        current_user_id=current_user.id,
        db=db
    )


# --- Group chats ---


@router.get("/group/dialogs", response_model=list[GroupChatDialogResponse])
def group_dialogs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dialogs = (
        db.query(GroupChatDialog)
        .join(GroupChatMember, GroupChatMember.dialog_id == GroupChatDialog.id)
        .filter(GroupChatMember.user_id == current_user.id, GroupChatMember.is_active == True)
        .all()
    )

    items: list[GroupChatDialogResponse] = []
    for d in dialogs:
        last = (
            db.query(ChatMessage)
            .filter(ChatMessage.group_dialog_id == d.id)
            .order_by(ChatMessage.id.desc())
            .first()
        )

        last_text: str | None = None
        if last:
            if last.is_deleted:
                last_text = "Сообщение было удалено"
            else:
                last_text = last.text

        items.append(
            GroupChatDialogResponse(
                id=d.id,
                name=d.name,
                last_message_text=last_text,
                last_message_at=last.created_at if last else None,
            )
        )

    def _sort_key(x: GroupChatDialogResponse):
        if x.last_message_at is None:
            return 0.0
        if x.last_message_at.tzinfo is None:
            return x.last_message_at.replace(tzinfo=timezone.utc).timestamp()
        return x.last_message_at.timestamp()

    items.sort(key=_sort_key, reverse=True)
    return items


@router.get("/group/dialogs/{dialog_id}/members", response_model=list[GroupChatMemberResponse])
def group_dialog_members(
    dialog_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only active members of the group can view membership list.
    _require_group_active_member(db, current_user, dialog_id)

    members = (
        db.query(GroupChatMember)
        .filter(GroupChatMember.dialog_id == dialog_id)
        .order_by(GroupChatMember.is_admin.desc(), GroupChatMember.joined_at.asc())
        .all()
    )

    out: list[GroupChatMemberResponse] = []
    for m in members:
        out.append(
            GroupChatMemberResponse(
                user=ChatUserShortResponse(
                    id=m.user.id,
                    username=m.user.username,
                    display_name=user_display_name(m.user),
                    is_active=bool(m.user.is_active),
                ),
                is_admin=bool(m.is_admin),
                is_active=bool(m.is_active),
                joined_at=m.joined_at,
                left_at=m.left_at,
            )
        )
    return out


@router.post("/group/dialogs", response_model=GroupChatDialogResponse, status_code=201)
def group_create_dialog(
    data: GroupChatDialogCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название группы")

    dialog = GroupChatDialog(name=name)
    db.add(dialog)
    db.flush()

    # Создатель - админ
    db.add(GroupChatMember(dialog_id=dialog.id, user_id=current_user.id, is_admin=True, is_active=True))

    member_ids = [int(x) for x in (data.member_ids or []) if x is not None]
    member_ids = [x for x in member_ids if x != current_user.id]
    if member_ids:
        # Только активные пользователи
        users = db.query(User).filter(User.id.in_(member_ids), User.is_active == True).all()
        valid_ids = {u.id for u in users}
        for uid in member_ids:
            if uid not in valid_ids:
                continue
            db.add(GroupChatMember(dialog_id=dialog.id, user_id=uid, is_admin=False, is_active=True))

        # System message for each added member
        for u in users:
            msg = ChatMessage(
                group_dialog_id=dialog.id,
                sender_user_id=None,
                text=f"Добавился {user_display_name(u)}",
                is_deleted=False,
            )
            db.add(msg)

    db.commit()
    db.refresh(dialog)

    last = (
        db.query(ChatMessage)
        .filter(ChatMessage.group_dialog_id == dialog.id)
        .order_by(ChatMessage.id.desc())
        .first()
    )
    return GroupChatDialogResponse(
        id=dialog.id,
        name=dialog.name,
        last_message_text=last.text if last and not last.is_deleted else ("Сообщение было удалено" if last and last.is_deleted else None),
        last_message_at=last.created_at if last else None,
    )


@router.post("/group/dialogs/{dialog_id}/members/{user_id}", status_code=204)
def group_add_member(
    dialog_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_group_admin(db, current_user, dialog_id)

    other = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not other:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    member = db.query(GroupChatMember).filter(GroupChatMember.dialog_id == dialog_id, GroupChatMember.user_id == user_id).first()
    is_new_or_reactivated = False
    if not member:
        member = GroupChatMember(dialog_id=dialog_id, user_id=user_id, is_admin=False, is_active=True)
        db.add(member)
        is_new_or_reactivated = True
    elif not member.is_active:
        member.is_active = True
        member.left_at = None
        is_new_or_reactivated = True

    if is_new_or_reactivated:
        db.add(
            ChatMessage(
                group_dialog_id=dialog_id,
                sender_user_id=None,
                text=f"Добавился {user_display_name(other)}",
                is_deleted=False,
            )
        )

    db.commit()
    return None


@router.delete("/group/dialogs/{dialog_id}/members/{user_id}", status_code=204)
def group_remove_member(
    dialog_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member_target = db.query(GroupChatMember).filter(
        GroupChatMember.dialog_id == dialog_id,
        GroupChatMember.user_id == user_id,
    ).first()
    if not member_target or not member_target.is_active:
        raise HTTPException(status_code=404, detail="Участник не найден")

    # Если уходит не сам пользователь — нужен админ
    if user_id != current_user.id:
        _require_group_admin(db, current_user, dialog_id)

    other = db.query(User).filter(User.id == user_id).first()
    member_target.is_active = False
    member_target.left_at = datetime.now(timezone.utc)

    if other:
        db.add(
            ChatMessage(
                group_dialog_id=dialog_id,
                sender_user_id=None,
                text=f"Покинул {user_display_name(other)}",
                is_deleted=False,
            )
        )

    db.commit()
    return None


@router.get("/group/dialogs/{dialog_id}/messages", response_model=list[ChatMessageResponse])
def group_messages(
    dialog_id: int,
    after_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_group_active_member(db, current_user, dialog_id)

    q = db.query(ChatMessage).filter(ChatMessage.group_dialog_id == dialog_id)
    if after_id is not None:
        q = q.filter(ChatMessage.id > after_id)
    q = q.order_by(ChatMessage.id.desc()).limit(limit)
    msgs = list(reversed(q.all()))

    out: list[ChatMessageResponse] = []
    for m in msgs:
        out.append(_to_message_response(
            m, 
            attachments=list(m.attachments), 
            include_sender=m.sender_user_id is not None,
            current_user_id=current_user.id,
            db=db
        ))
    return out


@router.post("/group/dialogs/{dialog_id}/messages", response_model=ChatMessageResponse, status_code=201)
async def group_send(
    dialog_id: int,
    text: str | None = Form(None),
    reply_to_message_id: int | None = Form(None),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_group_active_member(db, current_user, dialog_id)

    text_val = (text or "").strip() or None
    if not text_val and not files:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    if reply_to_message_id is not None:
        reply_to = db.query(ChatMessage).filter(ChatMessage.id == reply_to_message_id).first()
        if not reply_to:
            raise HTTPException(status_code=404, detail="Сообщение для ответа не найдено")
        if reply_to.group_dialog_id != dialog_id:
            raise HTTPException(status_code=400, detail="Нельзя отвечать на сообщение из другой группы")

    msg = ChatMessage(
        group_dialog_id=dialog_id,
        sender_user_id=current_user.id,
        text=text_val,
        is_deleted=False,
        reply_to_message_id=reply_to_message_id,
    )
    db.add(msg)
    db.flush()

    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        media_type, ok = _allowed_media(ext)
        if not ok:
            raise HTTPException(status_code=400, detail="Недопустимый тип файла")

        content = await f.read()
        if media_type == "image" and len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="Файл изображения слишком большой")
        if media_type == "video" and len(content) > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=400, detail="Файл видео слишком большой")

        unique_filename = f"{uuid.uuid4()}{ext}"
        file_path = UPLOAD_DIR / unique_filename
        try:
            with open(file_path, "wb") as fp:
                fp.write(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e!s}")

        url = f"/uploads/{unique_filename}"
        att = ChatMessageAttachment(
            message_id=msg.id,
            url=url,
            media_type=media_type,
            filename=unique_filename,
            mime_type=f.content_type,
        )
        db.add(att)

    db.commit()
    db.refresh(msg)
    recipients = [
        m.user_id
        for m in db.query(GroupChatMember)
        .filter(
            GroupChatMember.dialog_id == dialog_id,
            GroupChatMember.is_active == True,
            GroupChatMember.user_id != current_user.id,
        )
        .all()
    ]
    _send_chat_push_to_users(
        db,
        user_ids=recipients,
        title="Новое сообщение (Группа)",
        body=(text_val or "Вложение"),
        data={"chatType": "group", "dialogId": str(dialog_id), "messageId": str(msg.id)},
    )
    return _to_message_response(
        msg, 
        attachments=list(msg.attachments), 
        include_sender=True,
        current_user_id=current_user.id,
        db=db
    )


# --- Message edit/delete (shared) ---


@router.patch("/messages/{message_id}", response_model=ChatMessageResponse)
async def edit_message(
    message_id: int,
    data: ChatEditMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Редактирование: только автор и только в течение 15 минут.
    В фронте редактирование делаем JSON, но чтобы не усложнять multipart —
    разрешаем текст через FormData тоже.
    """
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    # Доступ
    if msg.private_dialog_id is None and msg.group_dialog_id is None:
        _require_general_active_member(db, current_user)
    elif msg.private_dialog_id is not None:
        _require_dialog_access(db, current_user, msg.private_dialog_id)
    else:
        _require_group_active_member(db, current_user, msg.group_dialog_id)

    # Права
    if msg.sender_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Редактировать можно только свои сообщения")
    if not can_edit_message(msg):
        raise HTTPException(status_code=403, detail=f"Редактирование доступно только в течение {EDIT_WINDOW_MINUTES} минут")
    if msg.is_deleted:
        raise HTTPException(status_code=403, detail="Сообщение удалено")

    new_text = (data.text or "").strip()
    msg.text = new_text or None
    msg.edited_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(msg)

    return _to_message_response(
        msg, 
        attachments=list(msg.attachments), 
        include_sender=True,
        current_user_id=current_user.id,
        db=db
    )


@router.delete("/messages/{message_id}", status_code=204)
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    # Доступ
    if msg.private_dialog_id is None and msg.group_dialog_id is None:
        _require_general_active_member(db, current_user)
    elif msg.private_dialog_id is not None:
        _require_dialog_access(db, current_user, msg.private_dialog_id)
    else:
        _require_group_active_member(db, current_user, msg.group_dialog_id)

    if msg.sender_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Удалять можно только свои сообщения")

    msg.is_deleted = True
    db.commit()
    return None


@router.post("/messages/mark-read", status_code=204)
def mark_messages_read(
    message_ids: list[int],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Отметить сообщения как прочитанные текущим пользователем.
    """
    for msg_id in message_ids:
        # Check if already marked as read
        existing = db.query(ChatMessageRead).filter(
            ChatMessageRead.message_id == msg_id,
            ChatMessageRead.user_id == current_user.id
        ).first()
        
        if not existing:
            read_record = ChatMessageRead(
                message_id=msg_id,
                user_id=current_user.id
            )
            db.add(read_record)
    
    db.commit()
    return None


@router.get("/notifications/summary", response_model=ChatNotificationSummaryResponse)
def chat_notifications_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Сводка для мобильных уведомлений:
    - количество непрочитанных сообщений;
    - текст и отправитель последнего непрочитанного.
    """
    general_member = db.query(GeneralChatMember).filter(
        GeneralChatMember.user_id == current_user.id,
        GeneralChatMember.is_active == True,
    ).first()
    can_access_general = general_member is not None

    private_dialog_ids = {
        d.id
        for d in db.query(PrivateDialog).filter(
            or_(PrivateDialog.user1_id == current_user.id, PrivateDialog.user2_id == current_user.id)
        ).all()
    }

    group_dialog_ids = {
        m.dialog_id
        for m in db.query(GroupChatMember).filter(
            GroupChatMember.user_id == current_user.id,
            GroupChatMember.is_active == True,
        ).all()
    }

    recent_messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.sender_user_id.isnot(None),
            ChatMessage.sender_user_id != current_user.id,
            ChatMessage.is_deleted == False,
        )
        .order_by(ChatMessage.id.desc())
        .limit(500)
        .all()
    )
    if not recent_messages:
        return ChatNotificationSummaryResponse(unread_count=0)

    message_ids = [m.id for m in recent_messages]
    read_ids = {
        row.message_id
        for row in db.query(ChatMessageRead.message_id).filter(
            ChatMessageRead.user_id == current_user.id,
            ChatMessageRead.message_id.in_(message_ids),
        ).all()
    }

    unread_count = 0
    last_unread: ChatMessage | None = None
    last_unread_chat: str | None = None

    for msg in recent_messages:
        if msg.id in read_ids:
            continue

        in_general = msg.private_dialog_id is None and msg.group_dialog_id is None
        in_private = msg.private_dialog_id is not None and msg.private_dialog_id in private_dialog_ids
        in_group = msg.group_dialog_id is not None and msg.group_dialog_id in group_dialog_ids

        if in_general and not can_access_general:
            continue
        if not (in_general or in_private or in_group):
            continue

        unread_count += 1
        if last_unread is None:
            last_unread = msg
            if in_general:
                last_unread_chat = "Общий чат"
            elif in_private:
                last_unread_chat = "Личный чат"
            elif in_group:
                last_unread_chat = "Групповой чат"

    if last_unread is None:
        return ChatNotificationSummaryResponse(unread_count=0)

    sender_name = user_display_name(last_unread.sender) if last_unread.sender else None
    return ChatNotificationSummaryResponse(
        unread_count=unread_count,
        last_message_text=last_unread.text,
        last_message_sender=sender_name,
        last_message_chat=last_unread_chat,
    )

