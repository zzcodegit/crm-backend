from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, Header
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload, selectinload

from chat_poll import (
    create_chat_poll_message,
    cast_poll_vote,
    poll_response_for_message,
    _polls_for_messages,
)
from chat_reactions import reactions_for_messages, toggle_message_reaction, normalize_reaction_emoji
from chat_service import (
    EDIT_WINDOW_MINUTES,
    attachment_matches_shared_category,
    can_edit_message,
    ensure_general_chat_member,
    extract_chat_urls,
    normalize_attachment_media_type,
    user_display_name,
)
from database import get_db
from deps import get_chat_user, is_admin, is_consultant
from models import (
    ChatMessage,
    ChatMessageReaction,
    ChatPoll,
    ChatWallpaper,
    ChatMessageAttachment,
    ChatMessageRead,
    ChatMessageAcknowledgment,
    GeneralChatMember,
    PrivateDialog,
    GroupChatDialog,
    GroupChatMember,
    Group,
    PushDeviceToken,
    WebPushSubscription,
    User,
)
from deps import ADMIN_GROUP_NAME
from chat_push_delivery import send_chat_push_to_users as _send_chat_push_to_users
from webpush_service import get_webpush_public_key as get_webpush_public_key_value
from schemas import (
    ChatAttachmentResponse,
    ChatEditMessageRequest,
    ChatForwardMessageRequest,
    ChatMessageResponse,
    ChatMessageSenderResponse,
    ChatPollCreateRequest,
    ChatPollVoteRequest,
    ChatPollResponse,
    ChatMessageReactionRequest,
    ChatReactionSummary,
    ChatUserShortResponse,
    ChatUserProfileResponse,
    PrivateDialogResponse,
    GeneralChatStatusResponse,
    GroupChatDialogResponse,
    GroupChatDialogCreateRequest,
    GroupChatDialogUpdateRequest,
    GroupChatMemberResponse,
    ChatNotificationSummaryResponse,
    ChatSearchMessageHit,
    ChatSearchResponse,
    ChatNotificationsSettingsBody,
    ChatNotificationsSettingsResponse,
    GroupChatNotificationsSettingsBody,
    ChatWallpaperItemResponse,
    ChatWallpaperSettingsBody,
    ChatWallpaperSettingsResponse,
    ChatMessageReadUserItem,
    ChatMessageReadsResponse,
    ChatSharedMediaItem,
    ChatSharedMediaResponse,
    PushTokenRegisterRequest,
    WebPushSubscribeRequest,
)


router = APIRouter(prefix="/api/chat", tags=["chat"])

UPLOAD_DIR = Path("/home/crm-backend/uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Разрешаем вложения только нужного типа
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".webm"}

# Лимиты по размеру (примерные, можно подстроить)
MAX_IMAGE_SIZE = 15 * 1024 * 1024  # 15MB
MAX_VIDEO_SIZE = 80 * 1024 * 1024  # 80MB
MAX_AUDIO_SIZE = 20 * 1024 * 1024  # 20MB
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB — документы и прочие вложения
STICKER_EXTENSIONS = {".webp", ".png", ".gif", ".svg"}
MAX_STICKER_SIZE = 512 * 1024  # 512KB


def _safe_attachment_display_name(filename: str | None) -> str:
    orig = (filename or "file").replace('"', "").strip() or "file"
    if len(orig) > 240:
        orig = orig[:237] + "..."
    return orig


def _allowed_media(ext: str) -> tuple[str, bool]:
    ext = ext.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image", True
    if ext in VIDEO_EXTENSIONS:
        return "video", True
    if ext in AUDIO_EXTENSIONS:
        return "audio", True
    if ext:
        return "file", True
    return "", False


def _allowed_media_for_upload(
    filename: str | None,
    mime_type: str | None,
    is_voice_note: bool = False,
    is_video_note: bool = False,
    is_sticker: bool = False,
) -> tuple[str, bool]:
    """
    Determine chat attachment type for upload.
    Prefer MIME type (important for .webm voice notes), fallback to extension.
    """
    name = (filename or "").strip().lower()
    ext = Path(name).suffix.lower()
    if is_sticker or name.startswith("sticker-"):
        if ext in STICKER_EXTENSIONS:
            return "sticker", True
        return "", False
    # Voice recorder on some browsers may report webm as video/*.
    # For our chat, files created as "voice-*" must be treated as audio.
    if (is_voice_note or name.startswith("voice-")) and ext in AUDIO_EXTENSIONS:
        return "audio", True
    if (is_video_note or name.startswith("video-note-")) and ext in VIDEO_EXTENSIONS:
        return "video", True

    mt = (mime_type or "").strip().lower()
    if mt.startswith("audio/"):
        return "audio", True
    if mt.startswith("video/"):
        return "video", True
    if mt.startswith("image/"):
        return "image", True
    if mt == "image/svg+xml" and name.startswith("sticker-"):
        return "sticker", True
    if mt.startswith("application/") or mt.startswith("text/"):
        return "file", True
    known, ok = _allowed_media(ext)
    if ok:
        return known, True
    if mt:
        return "file", True
    return "", False


def _stored_upload_filename(
    original_filename: str | None,
    ext: str,
    media_type: str,
    *,
    is_voice_note: bool = False,
    is_video_note: bool = False,
) -> tuple[str, str | None]:
    """Имя файла на диске и mime_type для вложения."""
    name = (original_filename or "").strip().lower()
    mime: str | None = None
    if is_voice_note or (media_type == "audio" and name.startswith("voice-")):
        stored = f"voice-{uuid.uuid4()}{ext}"
        if ext == ".webm":
            mime = "audio/webm"
        elif ext in {".ogg", ".mp3", ".wav", ".m4a"}:
            mime = f"audio/{ext.lstrip('.')}"
        return stored, mime
    if is_video_note or name.startswith("video-note-"):
        return f"video-note-{uuid.uuid4()}{ext}", None
    if media_type == "file":
        return f"{uuid.uuid4()}{ext}", None
    return f"{uuid.uuid4()}{ext}", None


async def _save_message_attachment(
    db: Session,
    msg_id: int,
    f: UploadFile,
    *,
    is_voice_note: bool = False,
    is_video_note: bool = False,
    is_sticker: bool = False,
) -> None:
    ext = Path(f.filename or "").suffix.lower()
    media_type, ok = _allowed_media_for_upload(
        f.filename,
        f.content_type,
        is_voice_note=is_voice_note,
        is_video_note=is_video_note,
        is_sticker=is_sticker,
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
    if media_type == "file" and len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимум 100 МБ")

    unique_filename, voice_mime = _stored_upload_filename(
        f.filename, ext, media_type, is_voice_note=is_voice_note, is_video_note=is_video_note
    )
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as fp:
            fp.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e!s}")

    display_name = _safe_attachment_display_name(f.filename) if media_type == "file" else unique_filename
    db.add(
        ChatMessageAttachment(
            message_id=msg_id,
            url=f"/uploads/{unique_filename}",
            media_type=media_type,
            filename=display_name,
            mime_type=voice_mime or f.content_type,
        )
    )


def _normalize_attachment_media_type(att: ChatMessageAttachment) -> str:
    return normalize_attachment_media_type(att)


def _general_chat_message_filter():
    """Сообщения общего чата (не бот, не личка, не группа)."""
    return and_(
        ChatMessage.private_dialog_id.is_(None),
        ChatMessage.group_dialog_id.is_(None),
        ChatMessage.bot_thread_user_id.is_(None),
        getattr(ChatMessage, "gigachat_thread_user_id").is_(None),
    )


def _is_chat_admin(user: User) -> bool:
    return is_admin(user)


def _chat_admin_user_ids(db: Session) -> list[int]:
    ids: set[int] = set()
    admin_group = (
        db.query(Group)
        .options(joinedload(Group.users))
        .filter(Group.name == ADMIN_GROUP_NAME)
        .first()
    )
    if admin_group:
        for u in admin_group.users:
            if u.is_active:
                ids.add(int(u.id))
    return list(ids)


def _group_viewer_sees_all_messages(user: User, member: GroupChatMember) -> bool:
    if is_admin(user):
        return True
    if member.is_admin:
        return True
    return False


def _group_own_messages_filter(user_id: int):
    return or_(
        ChatMessage.sender_user_id == user_id,
        ChatMessage.sender_user_id.is_(None),
    )


def _group_restrict_sender_user_id(
    db: Session,
    user: User,
    dialog: GroupChatDialog,
    member: GroupChatMember,
) -> int | None:
    if not bool(getattr(dialog, "members_see_own_only", False)):
        return None
    if _group_viewer_sees_all_messages(user, member):
        return None
    return int(user.id)


def _require_group_message_visible(
    db: Session,
    user: User,
    dialog: GroupChatDialog,
    member: GroupChatMember,
    msg: ChatMessage,
) -> None:
    if msg.group_dialog_id != dialog.id:
        raise HTTPException(status_code=403, detail="Нет доступа к сообщению")
    restrict = _group_restrict_sender_user_id(db, user, dialog, member)
    if restrict is None:
        return
    if msg.sender_user_id is None:
        return
    if int(msg.sender_user_id) != restrict:
        raise HTTPException(status_code=403, detail="Нет доступа к этому сообщению")


def _group_message_visibility_conditions(db: Session, user: User) -> list:
    """Сообщения группы: с момента joined_at; при members_see_own_only — только свои (+ системные)."""
    members = (
        db.query(GroupChatMember)
        .options(joinedload(GroupChatMember.dialog))
        .filter(GroupChatMember.user_id == user.id, GroupChatMember.is_active == True)
        .all()
    )
    out: list = []
    for m in members:
        dialog = m.dialog
        if not dialog:
            continue
        cond = and_(ChatMessage.group_dialog_id == m.dialog_id, ChatMessage.created_at >= m.joined_at)
        restrict = _group_restrict_sender_user_id(db, user, dialog, m)
        if restrict is not None:
            cond = and_(cond, _group_own_messages_filter(restrict))
        out.append(cond)
    return out


def _group_notification_visibility_conditions(db: Session, user: User) -> list:
    """Группы с выключенными уведомлениями; учёт members_see_own_only (чужие не в бейдже)."""
    members = (
        db.query(GroupChatMember)
        .options(joinedload(GroupChatMember.dialog))
        .filter(
            GroupChatMember.user_id == user.id,
            GroupChatMember.is_active == True,
            GroupChatMember.notifications_enabled == True,
        )
        .all()
    )
    out: list = []
    for m in members:
        dialog = m.dialog
        if not dialog:
            continue
        cond = and_(ChatMessage.group_dialog_id == m.dialog_id, ChatMessage.created_at >= m.joined_at)
        restrict = _group_restrict_sender_user_id(db, user, dialog, m)
        if restrict is not None:
            continue
        out.append(cond)
    return out


def _group_push_recipient_ids(db: Session, *, dialog_id: int, exclude_user_id: int) -> list[int]:
    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    members = (
        db.query(GroupChatMember)
        .filter(
            GroupChatMember.dialog_id == dialog_id,
            GroupChatMember.is_active == True,
            GroupChatMember.user_id != exclude_user_id,
            GroupChatMember.notifications_enabled == True,
        )
        .all()
    )
    if not dialog or not bool(getattr(dialog, "members_see_own_only", False)):
        return [int(m.user_id) for m in members]
    out: list[int] = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        if not u:
            continue
        if _group_viewer_sees_all_messages(u, m):
            out.append(int(m.user_id))
    return out


def _messages_for_chat(
    db: Session,
    *,
    general: bool = False,
    private_dialog_id: int | None = None,
    group_dialog_id: int | None = None,
    group_visible_since: datetime | None = None,
    group_restrict_sender_user_id: int | None = None,
    after_id: int | None = None,
    before_id: int | None = None,
    around_id: int | None = None,
    limit: int = 50,
) -> list[ChatMessage]:
    q = db.query(ChatMessage)
    if general:
        q = q.filter(_general_chat_message_filter())
    elif private_dialog_id is not None:
        q = q.filter(ChatMessage.private_dialog_id == private_dialog_id)
    elif group_dialog_id is not None:
        q = q.filter(ChatMessage.group_dialog_id == group_dialog_id)
        if group_visible_since is not None:
            q = q.filter(ChatMessage.created_at >= group_visible_since)
        if group_restrict_sender_user_id is not None:
            q = q.filter(_group_own_messages_filter(group_restrict_sender_user_id))

    if around_id is not None:
        half = max(limit // 2, 20)
        before_q = (
            q.filter(ChatMessage.id < around_id)
            .order_by(ChatMessage.id.desc())
            .limit(half)
        )
        before_msgs = list(reversed(before_q.all()))
        center = q.filter(ChatMessage.id == around_id).first()
        after_q = (
            q.filter(ChatMessage.id > around_id)
            .order_by(ChatMessage.id.asc())
            .limit(half)
        )
        after_msgs = list(after_q.all())
        out = before_msgs
        if center is not None:
            out.append(center)
        out.extend(after_msgs)
        return out

    if after_id is not None:
        q = q.filter(ChatMessage.id > after_id)
    if before_id is not None:
        q = q.filter(ChatMessage.id < before_id)
    q = q.order_by(ChatMessage.id.desc()).limit(limit)
    return list(reversed(q.all()))


def _messages_to_responses(db: Session, msgs: list[ChatMessage], current_user: User) -> list[ChatMessageResponse]:
    message_ids = [m.id for m in msgs]
    polls_map = _polls_for_messages(db, message_ids, current_user.id)
    reactions_map = reactions_for_messages(db, message_ids, current_user.id)
    out: list[ChatMessageResponse] = []
    for m in msgs:
        atts = list(m.attachments or [])
        out.append(
            _to_message_response(
                m,
                attachments=atts,
                include_sender=m.sender_user_id is not None,
                current_user_id=current_user.id,
                db=db,
                poll=polls_map.get(m.id),
                reactions=reactions_map.get(m.id, []),
            )
        )
    return out


_SHARED_MEDIA_CATEGORIES = frozenset({"photos", "videos", "voice", "files", "links"})


def _shared_media_for_chat(
    db: Session,
    *,
    category: str,
    offset: int,
    limit: int,
    general: bool = False,
    private_dialog_id: int | None = None,
    group_dialog_id: int | None = None,
    group_visible_since: datetime | None = None,
    group_restrict_sender_user_id: int | None = None,
) -> ChatSharedMediaResponse:
    if category not in _SHARED_MEDIA_CATEGORIES:
        raise HTTPException(status_code=400, detail="Неизвестная категория")

    if category == "links":
        mq = db.query(ChatMessage).filter(ChatMessage.is_deleted.is_(False), ChatMessage.text.isnot(None))
        if general:
            mq = mq.filter(_general_chat_message_filter())
        elif private_dialog_id is not None:
            mq = mq.filter(ChatMessage.private_dialog_id == private_dialog_id)
        else:
            mq = mq.filter(ChatMessage.group_dialog_id == group_dialog_id)
            if group_visible_since is not None:
                mq = mq.filter(ChatMessage.created_at >= group_visible_since)
            if group_restrict_sender_user_id is not None:
                mq = mq.filter(_group_own_messages_filter(group_restrict_sender_user_id))
        mq = mq.filter(or_(ChatMessage.text.ilike("%http%"), ChatMessage.text.ilike("%www.%")))
        rows = mq.order_by(ChatMessage.id.desc()).all()
        flat: list[ChatSharedMediaItem] = []
        for m in rows:
            urls = extract_chat_urls(m.text)
            if not urls:
                continue
            sender_name = user_display_name(m.sender) if m.sender else None
            preview = (m.text or "").strip()
            if len(preview) > 120:
                preview = preview[:117] + "…"
            for url in urls:
                flat.append(
                    ChatSharedMediaItem(
                        message_id=m.id,
                        link_url=url,
                        preview_text=preview or None,
                        created_at=m.created_at,
                        sender_name=sender_name,
                    )
                )
        total = len(flat)
        page = flat[offset : offset + limit]
        return ChatSharedMediaResponse(items=page, total=total)

    aq = (
        db.query(ChatMessageAttachment, ChatMessage)
        .join(ChatMessage, ChatMessage.id == ChatMessageAttachment.message_id)
        .filter(ChatMessage.is_deleted.is_(False))
    )
    if general:
        aq = aq.filter(_general_chat_message_filter())
    elif private_dialog_id is not None:
        aq = aq.filter(ChatMessage.private_dialog_id == private_dialog_id)
    else:
        aq = aq.filter(ChatMessage.group_dialog_id == group_dialog_id)
        if group_visible_since is not None:
            aq = aq.filter(ChatMessage.created_at >= group_visible_since)
        if group_restrict_sender_user_id is not None:
            aq = aq.filter(_group_own_messages_filter(group_restrict_sender_user_id))

    rows = aq.order_by(ChatMessageAttachment.id.desc()).all()
    filtered: list[tuple[ChatMessageAttachment, ChatMessage]] = []
    for att, msg in rows:
        if attachment_matches_shared_category(att, category):
            filtered.append((att, msg))

    total = len(filtered)
    page_rows = filtered[offset : offset + limit]
    items: list[ChatSharedMediaItem] = []
    for att, msg in page_rows:
        mt = _normalize_attachment_media_type(att)
        sender_name = user_display_name(msg.sender) if msg.sender else None
        items.append(
            ChatSharedMediaItem(
                message_id=msg.id,
                attachment_id=att.id,
                url=att.url,
                media_type=mt,
                filename=att.filename,
                mime_type=att.mime_type,
                created_at=att.created_at or msg.created_at,
                sender_name=sender_name,
            )
        )
    return ChatSharedMediaResponse(items=items, total=total)


def _user_sender_to_response(u: User) -> ChatMessageSenderResponse:
    return ChatMessageSenderResponse(
        id=u.id,
        username=u.username,
        display_name=user_display_name(u),
        avatar_url=u.avatar_url,
    )


def _to_message_response(
    msg: ChatMessage,
    *,
    attachments: list[ChatMessageAttachment],
    include_sender: bool,
    current_user_id: int | None = None,
    db: Session | None = None,
    poll: ChatPollResponse | None = None,
    reactions: list[ChatReactionSummary] | None = None,
) -> ChatMessageResponse:
    sender = _user_sender_to_response(msg.sender) if include_sender and msg.sender else None
    display_text = "Сообщение было удалено" if msg.is_deleted else msg.text
    attachments_out = [] if msg.is_deleted else attachments

    read_count = 0
    recipient_count = 0
    is_read = False
    ack_required = bool(getattr(msg, "ack_required", False))
    ack_count = 0
    ack_recipient_count = 0
    user_acknowledged = False
    recipient_ids: list[int] = []
    if current_user_id and db:
        recipient_ids = _message_read_recipient_user_ids(db, msg)
        if msg.sender_user_id == current_user_id:
            recipient_count = len(recipient_ids)
            if recipient_ids:
                read_count = (
                    db.query(ChatMessageRead)
                    .filter(
                        ChatMessageRead.message_id == msg.id,
                        ChatMessageRead.user_id.in_(recipient_ids),
                    )
                    .count()
                )
                is_read = read_count >= recipient_count
        if ack_required:
            ack_recipient_count = len(recipient_ids)
            if recipient_ids:
                ack_count = (
                    db.query(ChatMessageAcknowledgment)
                    .filter(
                        ChatMessageAcknowledgment.message_id == msg.id,
                        ChatMessageAcknowledgment.user_id.in_(recipient_ids),
                    )
                    .count()
                )
            if current_user_id in recipient_ids:
                user_acknowledged = (
                    db.query(ChatMessageAcknowledgment.id)
                    .filter(
                        ChatMessageAcknowledgment.message_id == msg.id,
                        ChatMessageAcknowledgment.user_id == current_user_id,
                    )
                    .first()
                    is not None
                )

    reactions_out: list[ChatReactionSummary] = []
    if not msg.is_deleted:
        if reactions is not None:
            reactions_out = reactions
        elif db is not None and current_user_id is not None:
            reactions_out = reactions_for_messages(db, [msg.id], current_user_id).get(msg.id, [])

    return ChatMessageResponse(
        id=msg.id,
        private_dialog_id=msg.private_dialog_id,
        group_dialog_id=msg.group_dialog_id,
        bot_thread_user_id=msg.bot_thread_user_id,
        gigachat_thread_user_id=getattr(msg, "gigachat_thread_user_id", None),
        sender=sender,
        display_text=display_text,
        is_deleted=msg.is_deleted,
        created_at=msg.created_at,
        edited_at=msg.edited_at,
        attachments=[
            ChatAttachmentResponse(
                id=a.id,
                url=a.url,
                media_type=_normalize_attachment_media_type(a),
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
        read_count=read_count,
        recipient_count=recipient_count,
        ack_required=ack_required,
        ack_count=ack_count,
        ack_recipient_count=ack_recipient_count,
        user_acknowledged=user_acknowledged,
        poll=poll if not msg.is_deleted else None,
        reactions=reactions_out,
    )


def _poll_message_response(
    db: Session,
    msg: ChatMessage,
    current_user: User,
) -> ChatMessageResponse:
    poll = poll_response_for_message(db, msg.id, current_user.id)
    return _to_message_response(
        msg,
        attachments=list(msg.attachments or []),
        include_sender=True,
        current_user_id=current_user.id,
        db=db,
        poll=poll,
    )


def _validate_poll_reply(
    db: Session,
    *,
    reply_to_message_id: int | None,
    private_dialog_id: int | None,
    group_dialog_id: int | None,
) -> None:
    if reply_to_message_id is None:
        return
    reply_to = db.query(ChatMessage).filter(ChatMessage.id == reply_to_message_id).first()
    if not reply_to:
        raise HTTPException(status_code=404, detail="Сообщение для ответа не найдено")
    if private_dialog_id is None and group_dialog_id is None:
        if reply_to.private_dialog_id is not None or reply_to.group_dialog_id is not None:
            raise HTTPException(status_code=400, detail="Нельзя отвечать на сообщение из другого чата")
    elif private_dialog_id is not None:
        if reply_to.private_dialog_id != private_dialog_id:
            raise HTTPException(status_code=400, detail="Нельзя отвечать на сообщение из другого чата")
    elif reply_to.group_dialog_id != group_dialog_id:
        raise HTTPException(status_code=400, detail="Нельзя отвечать на сообщение из другого чата")


def _require_message_access(db: Session, user: User, msg: ChatMessage) -> None:
    if msg.bot_thread_user_id is not None:
        thread_uid = int(msg.bot_thread_user_id)
        if _is_chat_admin(user) or int(user.id) == thread_uid:
            return
        raise HTTPException(status_code=403, detail="Нет доступа к этому обращению")
    if msg.private_dialog_id is None and msg.group_dialog_id is None:
        _require_general_active_member(db, user)
    elif msg.private_dialog_id is not None:
        _require_dialog_access(db, user, msg.private_dialog_id)
    else:
        member = _require_group_active_member(db, user, msg.group_dialog_id)
        dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == msg.group_dialog_id).first()
        if dialog:
            _require_group_message_visible(db, user, dialog, member, msg)


def _message_read_recipient_user_ids(db: Session, msg: ChatMessage) -> list[int]:
    """Пользователи, от которых ожидается прочтение (все участники чата, кроме автора)."""
    if msg.sender_user_id is None:
        return []
    sender_id = int(msg.sender_user_id)
    if msg.bot_thread_user_id is not None:
        thread_uid = int(msg.bot_thread_user_id)
        if sender_id == thread_uid:
            return [uid for uid in _chat_admin_user_ids(db) if uid != sender_id]
        return [thread_uid] if thread_uid != sender_id else []
    if msg.private_dialog_id is not None:
        dialog = db.query(PrivateDialog).filter(PrivateDialog.id == msg.private_dialog_id).first()
        if not dialog:
            return []
        ids = [int(dialog.user1_id), int(dialog.user2_id)]
        return [uid for uid in ids if uid != sender_id]
    if msg.group_dialog_id is not None:
        rows = (
            db.query(GroupChatMember.user_id)
            .filter(
                GroupChatMember.dialog_id == msg.group_dialog_id,
                GroupChatMember.is_active == True,
                GroupChatMember.user_id != sender_id,
            )
            .all()
        )
        return [int(r[0]) for r in rows]
    rows = (
        db.query(GeneralChatMember.user_id)
        .filter(GeneralChatMember.is_active == True, GeneralChatMember.user_id != sender_id)
        .all()
    )
    return [int(r[0]) for r in rows]


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


def _accessible_message_conditions(db: Session, user: User) -> list:
    """Условия OR для сообщений, доступных пользователю."""
    general_member = db.query(GeneralChatMember).filter(
        GeneralChatMember.user_id == user.id,
        GeneralChatMember.is_active == True,
    ).first()
    conditions: list = []
    if general_member is not None:
        conditions.append(_general_chat_message_filter())
    private_dialog_ids = _visible_private_dialog_ids_for_user(db, user)
    if private_dialog_ids:
        conditions.append(ChatMessage.private_dialog_id.in_(private_dialog_ids))
    group_conditions = _group_message_visibility_conditions(db, user)
    if group_conditions:
        conditions.append(or_(*group_conditions))
    if _is_chat_admin(user):
        conditions.append(ChatMessage.bot_thread_user_id.isnot(None))
    else:
        conditions.append(ChatMessage.bot_thread_user_id == user.id)
    return conditions


def _message_chat_title(db: Session, msg: ChatMessage, current_user: User) -> str:
    if msg.bot_thread_user_id is not None:
        u = db.query(User).filter(User.id == msg.bot_thread_user_id).first()
        return f"Поддержка · {user_display_name(u) if u else 'Пользователь'}"
    if msg.group_dialog_id is not None:
        g = db.query(GroupChatDialog).filter(GroupChatDialog.id == msg.group_dialog_id).first()
        return g.name if g else "Группа"
    if msg.private_dialog_id is not None:
        dialog = db.query(PrivateDialog).filter(PrivateDialog.id == msg.private_dialog_id).first()
        if not dialog:
            return "Личный чат"
        other_id = dialog.user2_id if int(dialog.user1_id) == int(current_user.id) else dialog.user1_id
        other = db.query(User).filter(User.id == other_id).first()
        return user_display_name(other) if other else "Личный чат"
    return "Общий чат"


def _visible_private_dialog_ids_for_user(db: Session, user: User) -> set[int]:
    rows = (
        db.query(PrivateDialog.id)
        .filter(
            or_(
                and_(PrivateDialog.user1_id == user.id, PrivateDialog.user1_hidden == False),
                and_(PrivateDialog.user2_id == user.id, PrivateDialog.user2_hidden == False),
            )
        )
        .all()
    )
    return {int(r[0]) for r in rows}


def _require_group_active_member(db: Session, user: User, dialog_id: int) -> GroupChatMember:
    member = db.query(GroupChatMember).filter(GroupChatMember.dialog_id == dialog_id, GroupChatMember.user_id == user.id).first()
    if not member or not member.is_active:
        raise HTTPException(status_code=403, detail="Нет доступа к группе")
    return member


def _check_group_self_leave_allowed(
    db: Session,
    dialog: GroupChatDialog,
    user: User,
    member: GroupChatMember,
) -> None:
    """Консультанты не могут покинуть группу, если включён запрет выхода (админы группы и CRM-админы — могут)."""
    if not dialog.forbid_exit:
        return
    if member.is_admin or is_admin(user):
        return
    if is_consultant(user):
        raise HTTPException(
            status_code=403,
            detail="Выход из этой группы запрещён. Обратитесь к администратору группы.",
        )


def _require_message_ack_stats_access(db: Session, user: User, msg: ChatMessage) -> None:
    if not msg.ack_required:
        raise HTTPException(status_code=400, detail="У сообщения нет кнопки ознакомления")
    if msg.sender_user_id == user.id:
        return
    if msg.group_dialog_id is not None:
        _require_group_admin(db, user, msg.group_dialog_id)
        return
    raise HTTPException(status_code=403, detail="Статистика ознакомления доступна автору или администратору канала")


def _require_group_post_permission(db: Session, user: User, dialog_id: int) -> None:
    """В информационном канале публиковать могут только администраторы канала."""
    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    if not dialog:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    if dialog.is_channel:
        _require_group_admin(db, user, dialog_id)


def _require_group_admin(db: Session, user: User, dialog_id: int) -> GroupChatMember | None:
    member = db.query(GroupChatMember).filter(GroupChatMember.dialog_id == dialog_id, GroupChatMember.user_id == user.id).first()
    if member and member.is_active and member.is_admin:
        return member
    # Системный администратор может управлять любой группой даже без роли админа внутри группы.
    if is_admin(user):
        return member
    raise HTTPException(status_code=403, detail="Только администратор группы может менять состав")


def _unlink_group_dialog_upload_files(db: Session, dialog_id: int) -> None:
    """Удаляет файлы вложений с диска перед каскадным удалением сообщений."""
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.group_dialog_id == dialog_id)
        .options(selectinload(ChatMessage.attachments))
        .all()
    )
    for m in msgs:
        for a in m.attachments:
            name = Path(str(a.url).replace("\\", "/")).name
            if not name:
                continue
            try:
                (UPLOAD_DIR / name).unlink(missing_ok=True)
            except OSError:
                pass


def _require_chat_profile_access(db: Session, current_user: User, target_user_id: int) -> User:
    """Профиль доступен при личном диалоге или общем членстве в группе/канале."""
    if target_user_id == current_user.id:
        target = db.query(User).filter(User.id == current_user.id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return target

    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    private_exists = (
        db.query(PrivateDialog.id)
        .filter(
            or_(
                and_(PrivateDialog.user1_id == current_user.id, PrivateDialog.user2_id == target_user_id),
                and_(PrivateDialog.user1_id == target_user_id, PrivateDialog.user2_id == current_user.id),
            )
        )
        .first()
    )
    if private_exists:
        return target

    my_dialog_ids = [
        row[0]
        for row in db.query(GroupChatMember.dialog_id)
        .filter(GroupChatMember.user_id == current_user.id, GroupChatMember.is_active == True)
        .all()
    ]
    if my_dialog_ids:
        common = (
            db.query(GroupChatMember.id)
            .filter(
                GroupChatMember.user_id == target_user_id,
                GroupChatMember.is_active == True,
                GroupChatMember.dialog_id.in_(my_dialog_ids),
            )
            .first()
        )
        if common:
            return target

    raise HTTPException(status_code=403, detail="Нет доступа к профилю этого пользователя")


@router.get("/users/{user_id}/profile", response_model=ChatUserProfileResponse)
def chat_user_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    u = _require_chat_profile_access(db, current_user, user_id)
    return ChatUserProfileResponse(
        id=u.id,
        username=u.username,
        display_name=user_display_name(u),
        avatar_url=u.avatar_url,
        phone=(u.phone or "").strip() or None,
        birth_date=u.birth_date,
    )


@router.get("/search", response_model=ChatSearchResponse)
def chat_global_search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Поиск пользователей и сообщений по доступным чатам."""
    needle = (q or "").strip()
    if len(needle) < 1:
        return ChatSearchResponse()

    users_out: list[ChatUserShortResponse] = []
    if len(needle) >= 2:
        uq = db.query(User).filter(User.is_active == True, User.id != current_user.id).order_by(User.username)
        uq = uq.filter(
            or_(
                User.username.ilike(f"%{needle}%"),
                User.first_name.ilike(f"%{needle}%"),
                User.last_name.ilike(f"%{needle}%"),
                User.patronymic.ilike(f"%{needle}%"),
            )
        )
        users_out = [
            ChatUserShortResponse(
                id=u.id,
                username=u.username,
                display_name=user_display_name(u),
                is_active=bool(u.is_active),
                avatar_url=u.avatar_url,
            )
            for u in uq.limit(min(limit, 30)).all()
        ]

    messages_out: list[ChatSearchMessageHit] = []
    access_conditions = _accessible_message_conditions(db, current_user)
    if access_conditions and len(needle) >= 2:
        rows = (
            db.query(ChatMessage)
            .options(selectinload(ChatMessage.sender))
            .filter(
                ChatMessage.is_deleted.is_(False),
                ChatMessage.text.isnot(None),
                ChatMessage.text.ilike(f"%{needle}%"),
                or_(*access_conditions),
            )
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
        for msg in rows:
            preview = (msg.text or "").strip()
            if len(preview) > 160:
                preview = preview[:157] + "…"
            if msg.bot_thread_user_id is not None:
                chat_type = "bot"
            elif msg.group_dialog_id is not None:
                chat_type = "group"
            elif msg.private_dialog_id is not None:
                chat_type = "private"
            else:
                chat_type = "general"
            messages_out.append(
                ChatSearchMessageHit(
                    message_id=msg.id,
                    chat_type=chat_type,
                    private_dialog_id=msg.private_dialog_id,
                    group_dialog_id=msg.group_dialog_id,
                    bot_thread_user_id=msg.bot_thread_user_id,
                    chat_title=_message_chat_title(db, msg, current_user),
                    preview_text=preview or None,
                    sender_name=user_display_name(msg.sender) if msg.sender else None,
                    created_at=msg.created_at,
                )
            )

    return ChatSearchResponse(users=users_out, messages=messages_out)


@router.get("/users", response_model=list[ChatUserShortResponse])
def list_users_for_chat(
    search: str | None = Query(None, description="Поиск по логину/именам"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    # Исключаем текущего пользователя в запросе, а не после LIMIT — иначе при лимите 30
    # в выдаче оказывалось 29 «чужих» пользователей.
    q = db.query(User).filter(User.is_active == True, User.id != current_user.id).order_by(User.username)
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
    users = q.limit(limit).all()
    return [
        ChatUserShortResponse(
            id=u.id,
            username=u.username,
            display_name=user_display_name(u),
            is_active=bool(u.is_active),
            avatar_url=u.avatar_url,
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


@router.post("/push/register", status_code=204)
def register_push_token(
    payload: PushTokenRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _register_or_update_push_token(
        db,
        user_id=current_user.id,
        token=payload.token,
        platform=payload.platform,
    )
    return None


@router.get("/webpush/public-key")
def get_webpush_public_key(
    _: User = Depends(get_chat_user),
):
    key = (get_webpush_public_key_value() or "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="Web push не настроен на сервере")
    return {"public_key": key}


@router.post("/webpush/subscribe", status_code=204)
def subscribe_webpush(
    payload: WebPushSubscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
    user_agent: str | None = Header(None),
):
    endpoint = (payload.endpoint or "").strip()
    p256dh = (payload.p256dh or "").strip()
    auth = (payload.auth or "").strip()
    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Некорректная web push подписка")
    row = db.query(WebPushSubscription).filter(WebPushSubscription.endpoint == endpoint).first()
    if row:
        row.user_id = current_user.id
        row.p256dh = p256dh
        row.auth = auth
        row.platform = (payload.platform or "web").strip().lower()
        row.user_agent = user_agent
        row.is_active = True
    else:
        db.add(
            WebPushSubscription(
                user_id=current_user.id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                platform=(payload.platform or "web").strip().lower(),
                user_agent=user_agent,
                is_active=True,
            )
        )
    db.commit()
    return None


@router.delete("/webpush/subscribe", status_code=204)
def unsubscribe_webpush(
    endpoint: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    endpoint_val = (endpoint or "").strip()
    if not endpoint_val:
        raise HTTPException(status_code=400, detail="endpoint обязателен")
    row = (
        db.query(WebPushSubscription)
        .filter(WebPushSubscription.endpoint == endpoint_val, WebPushSubscription.user_id == current_user.id)
        .first()
    )
    if row:
        row.is_active = False
        db.commit()
    return None


# --- General chat ---


@router.get("/general/status", response_model=GeneralChatStatusResponse)
def general_chat_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Статус общего чата для списка диалогов: участник ли, есть ли непрочитанные, последнее сообщение."""
    member = (
        db.query(GeneralChatMember)
        .filter(GeneralChatMember.user_id == current_user.id, GeneralChatMember.is_active == True)
        .first()
    )
    last = (
        db.query(ChatMessage)
        .filter(_general_chat_message_filter())
        .order_by(ChatMessage.id.desc())
        .first()
    )
    last_text: str | None = None
    last_at = None
    if last is not None:
        last_at = last.created_at
        last_text = "Сообщение было удалено" if last.is_deleted else last.text

    has_unread = False
    if member is not None:
        personal_unread = _personal_unread_exists_filter(current_user.id)
        has_unread = (
            db.query(ChatMessage.id)
            .filter(
                _general_chat_message_filter(),
                ChatMessage.sender_user_id.isnot(None),
                ChatMessage.sender_user_id != current_user.id,
                ChatMessage.is_deleted == False,
                personal_unread,
            )
            .first()
            is not None
        )

    return GeneralChatStatusResponse(
        is_member=member is not None,
        has_unread=has_unread,
        last_message_text=last_text,
        last_message_at=last_at,
    )


@router.post("/general/join", status_code=204)
def general_join(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    # Разрешаем возвращаться в общий чат (обычно это нужно именно админам после "выйти").
    ensure_general_chat_member(db, current_user, desired_is_active=True, only_create=False)
    return None


@router.post("/general/leave", status_code=204)
def general_leave(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Только администратор может выходить из общего чата")

    ensure_general_chat_member(db, current_user, desired_is_active=False, only_create=False)
    return None


@router.get("/general/messages", response_model=list[ChatMessageResponse])
def general_messages(
    after_id: int | None = Query(None, description="Загрузить сообщения после id"),
    before_id: int | None = Query(None, description="Загрузить сообщения до id"),
    around_id: int | None = Query(None, description="Загрузить сообщения вокруг id"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_general_active_member(db, current_user)
    msgs = _messages_for_chat(
        db,
        general=True,
        after_id=after_id,
        before_id=before_id,
        around_id=around_id,
        limit=limit,
    )
    return _messages_to_responses(db, msgs, current_user)


@router.get("/general/shared-media", response_model=ChatSharedMediaResponse)
def general_shared_media(
    category: str = Query(..., description="photos|videos|voice|files|links"),
    offset: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_general_active_member(db, current_user)
    return _shared_media_for_chat(db, category=category, offset=offset, limit=limit, general=True)


@router.post("/general/messages", response_model=ChatMessageResponse, status_code=201)
async def general_send(
    text: str | None = Form(None),
    reply_to_message_id: int | None = Form(None),
    is_voice_note: bool = Form(False),
    is_video_note: bool = Form(False),
    is_sticker: bool = Form(False),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_general_active_member(db, current_user)

    text_val = (text or "").strip() or None
    if not text_val and not files:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    if reply_to_message_id is not None:
        reply_to = db.query(ChatMessage).filter(ChatMessage.id == reply_to_message_id).first()
        if not reply_to:
            raise HTTPException(status_code=404, detail="Сообщение для ответа не найдено")
        if (
            reply_to.private_dialog_id is not None
            or reply_to.group_dialog_id is not None
            or reply_to.bot_thread_user_id is not None
            or getattr(reply_to, "gigachat_thread_user_id", None) is not None
        ):
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
        await _save_message_attachment(
            db,
            msg.id,
            f,
            is_voice_note=is_voice_note,
            is_video_note=is_video_note,
            is_sticker=is_sticker,
        )

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
        db=db,
    )


@router.post("/general/polls", response_model=ChatMessageResponse, status_code=201)
def general_create_poll(
    body: ChatPollCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_general_active_member(db, current_user)
    _validate_poll_reply(
        db,
        reply_to_message_id=body.reply_to_message_id,
        private_dialog_id=None,
        group_dialog_id=None,
    )
    msg = create_chat_poll_message(
        db,
        sender=current_user,
        question=body.question,
        option_texts=body.options,
        allows_multiple=body.allows_multiple,
        reply_to_message_id=body.reply_to_message_id,
    )
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
        title="Новый опрос (Общий чат)",
        body=body.question.strip(),
        data={"chatType": "general", "messageId": str(msg.id)},
    )
    return _poll_message_response(db, msg, current_user)


# --- Private dialogs ---


@router.get("/private/dialogs", response_model=list[PrivateDialogResponse])
def private_dialogs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    dialogs = (
        db.query(PrivateDialog)
        .filter(
            or_(
                and_(PrivateDialog.user1_id == current_user.id, PrivateDialog.user1_hidden == False),
                and_(PrivateDialog.user2_id == current_user.id, PrivateDialog.user2_hidden == False),
            )
        )
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
                    avatar_url=other.avatar_url,
                ),
                last_message_text="Сообщение было удалено" if last and last.is_deleted else (last.text if last else None),
                last_message_at=last.created_at if last else None,
                has_unread=(
                    db.query(ChatMessage.id)
                    .filter(
                        ChatMessage.private_dialog_id == d.id,
                        ChatMessage.sender_user_id.isnot(None),
                        ChatMessage.sender_user_id != current_user.id,
                        ChatMessage.is_deleted == False,
                        ~db.query(ChatMessageRead.id).filter(
                            ChatMessageRead.user_id == current_user.id,
                            ChatMessageRead.message_id == ChatMessage.id,
                        ).exists(),
                    )
                    .first()
                    is not None
                ),
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
    current_user: User = Depends(get_chat_user),
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
    else:
        # Снова открыли диалог из поиска — показываем в списке.
        if dialog.user1_id == current_user.id:
            dialog.user1_hidden = False
        else:
            dialog.user2_hidden = False
        db.commit()
        db.refresh(dialog)

    return {"id": dialog.id}


@router.delete("/private/dialogs/{dialog_id}", status_code=204)
def private_hide_dialog_for_user(
    dialog_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Убрать личный чат из списка у текущего пользователя (у собеседника остаётся)."""
    dialog = _require_dialog_access(db, current_user, dialog_id)
    if dialog.user1_id == current_user.id:
        dialog.user1_hidden = True
    else:
        dialog.user2_hidden = True
    db.commit()
    return None


@router.get("/private/dialogs/{dialog_id}/messages", response_model=list[ChatMessageResponse])
def private_messages(
    dialog_id: int,
    after_id: int | None = Query(None),
    before_id: int | None = Query(None),
    around_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_dialog_access(db, current_user, dialog_id)
    msgs = _messages_for_chat(
        db,
        private_dialog_id=dialog_id,
        after_id=after_id,
        before_id=before_id,
        around_id=around_id,
        limit=limit,
    )
    return _messages_to_responses(db, msgs, current_user)


@router.get("/private/dialogs/{dialog_id}/shared-media", response_model=ChatSharedMediaResponse)
def private_shared_media(
    dialog_id: int,
    category: str = Query(..., description="photos|videos|voice|files|links"),
    offset: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_dialog_access(db, current_user, dialog_id)
    return _shared_media_for_chat(
        db, category=category, offset=offset, limit=limit, private_dialog_id=dialog_id
    )


@router.post("/private/dialogs/{dialog_id}/messages", response_model=ChatMessageResponse, status_code=201)
async def private_send(
    dialog_id: int,
    text: str | None = Form(None),
    reply_to_message_id: int | None = Form(None),
    is_voice_note: bool = Form(False),
    is_video_note: bool = Form(False),
    is_sticker: bool = Form(False),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
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
        await _save_message_attachment(
            db,
            msg.id,
            f,
            is_voice_note=is_voice_note,
            is_video_note=is_video_note,
            is_sticker=is_sticker,
        )

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


@router.post("/private/dialogs/{dialog_id}/polls", response_model=ChatMessageResponse, status_code=201)
def private_create_poll(
    dialog_id: int,
    body: ChatPollCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_dialog_access(db, current_user, dialog_id)
    _validate_poll_reply(
        db,
        reply_to_message_id=body.reply_to_message_id,
        private_dialog_id=dialog_id,
        group_dialog_id=None,
    )
    msg = create_chat_poll_message(
        db,
        sender=current_user,
        question=body.question,
        option_texts=body.options,
        allows_multiple=body.allows_multiple,
        reply_to_message_id=body.reply_to_message_id,
        private_dialog_id=dialog_id,
    )
    db.commit()
    db.refresh(msg)
    dialog = db.query(PrivateDialog).filter(PrivateDialog.id == dialog_id).first()
    if dialog:
        other_user_id = dialog.user2_id if dialog.user1_id == current_user.id else dialog.user1_id
        _send_chat_push_to_users(
            db,
            user_ids=[other_user_id],
            title=f"Новый опрос ({user_display_name(current_user)})",
            body=body.question.strip(),
            data={"chatType": "private", "dialogId": str(dialog_id), "messageId": str(msg.id)},
        )
    return _poll_message_response(db, msg, current_user)


# --- Group chats ---


@router.get("/group/dialogs", response_model=list[GroupChatDialogResponse])
def group_dialogs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    dialogs = (
        db.query(GroupChatDialog)
        .join(GroupChatMember, GroupChatMember.dialog_id == GroupChatDialog.id)
        .filter(GroupChatMember.user_id == current_user.id, GroupChatMember.is_active == True)
        .all()
    )

    memberships = {
        m.dialog_id: m
        for m in db.query(GroupChatMember).filter(
            GroupChatMember.user_id == current_user.id,
            GroupChatMember.is_active == True,
        ).all()
    }

    items: list[GroupChatDialogResponse] = []
    for d in dialogs:
        member = memberships.get(d.id)
        joined_at = member.joined_at if member else None
        last_q = db.query(ChatMessage).filter(ChatMessage.group_dialog_id == d.id)
        if joined_at is not None:
            last_q = last_q.filter(ChatMessage.created_at >= joined_at)
        restrict_uid: int | None = None
        if member:
            restrict_uid = _group_restrict_sender_user_id(db, current_user, d, member)
        if restrict_uid is not None:
            last_q = last_q.filter(_group_own_messages_filter(restrict_uid))
        last = last_q.order_by(ChatMessage.id.desc()).first()

        last_text: str | None = None
        if last:
            if last.is_deleted:
                last_text = "Сообщение было удалено"
            else:
                last_text = last.text

        has_unread = False
        if restrict_uid is None:
            has_unread = (
                db.query(ChatMessage.id)
                .filter(
                    ChatMessage.group_dialog_id == d.id,
                    ChatMessage.sender_user_id.isnot(None),
                    ChatMessage.sender_user_id != current_user.id,
                    ChatMessage.is_deleted == False,
                    *(
                        [ChatMessage.created_at >= joined_at]
                        if joined_at is not None
                        else []
                    ),
                    ~db.query(ChatMessageRead.id).filter(
                        ChatMessageRead.user_id == current_user.id,
                        ChatMessageRead.message_id == ChatMessage.id,
                    ).exists(),
                )
                .first()
                is not None
            )

        items.append(
            GroupChatDialogResponse(
                id=d.id,
                name=d.name,
                image_url=d.image_url,
                forbid_exit=bool(d.forbid_exit),
                is_channel=bool(d.is_channel),
                members_see_own_only=bool(getattr(d, "members_see_own_only", False)),
                notifications_enabled=bool(member.notifications_enabled) if member else True,
                last_message_text=last_text,
                last_message_at=last.created_at if last else None,
                has_unread=has_unread,
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


@router.patch("/group/dialogs/{dialog_id}/notifications", response_model=GroupChatDialogResponse)
def patch_group_chat_notifications(
    dialog_id: int,
    data: GroupChatNotificationsSettingsBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    member = _require_group_active_member(db, current_user, dialog_id)
    member.notifications_enabled = bool(data.enabled)
    db.commit()
    rows = group_dialogs(db=db, current_user=current_user)
    for row in rows:
        if row.id == dialog_id:
            return row
    raise HTTPException(status_code=404, detail="Группа не найдена")


@router.get("/group/dialogs/{dialog_id}/members", response_model=list[GroupChatMemberResponse])
def group_dialog_members(
    dialog_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    # Only active members of the group can view membership list.
    _require_group_active_member(db, current_user, dialog_id)

    members = (
        db.query(GroupChatMember)
        .filter(GroupChatMember.dialog_id == dialog_id, GroupChatMember.is_active == True)
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
                    avatar_url=m.user.avatar_url,
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
    current_user: User = Depends(get_chat_user),
):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название группы")

    dialog = GroupChatDialog(
        name=name,
        image_url=((data.image_url or "").strip() or None),
        forbid_exit=bool(data.forbid_exit),
        is_channel=bool(data.is_channel),
        members_see_own_only=bool(data.members_see_own_only) and not bool(data.is_channel),
    )
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
            join_label = "Подписался на канал" if dialog.is_channel else "Добавился"
            msg = ChatMessage(
                group_dialog_id=dialog.id,
                sender_user_id=None,
                text=f"{join_label} {user_display_name(u)}",
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
        image_url=dialog.image_url,
        forbid_exit=bool(dialog.forbid_exit),
        is_channel=bool(dialog.is_channel),
        members_see_own_only=bool(getattr(dialog, "members_see_own_only", False)),
        last_message_text=last.text if last and not last.is_deleted else ("Сообщение было удалено" if last and last.is_deleted else None),
        last_message_at=last.created_at if last else None,
    )


@router.patch("/group/dialogs/{dialog_id}", response_model=GroupChatDialogResponse)
def group_update_dialog(
    dialog_id: int,
    data: GroupChatDialogUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_group_admin(db, current_user, dialog_id)
    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    if not dialog:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    if data.name is not None:
        name = (data.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Укажите название группы")
        dialog.name = name
    if data.image_url is not None:
        dialog.image_url = (data.image_url or "").strip() or None
    if data.forbid_exit is not None:
        dialog.forbid_exit = bool(data.forbid_exit)
    if data.is_channel is not None:
        dialog.is_channel = bool(data.is_channel)
    if data.members_see_own_only is not None:
        dialog.members_see_own_only = bool(data.members_see_own_only) and not bool(dialog.is_channel)

    db.commit()

    last = (
        db.query(ChatMessage)
        .filter(ChatMessage.group_dialog_id == dialog.id)
        .order_by(ChatMessage.id.desc())
        .first()
    )
    return GroupChatDialogResponse(
        id=dialog.id,
        name=dialog.name,
        image_url=dialog.image_url,
        forbid_exit=bool(dialog.forbid_exit),
        is_channel=bool(dialog.is_channel),
        members_see_own_only=bool(getattr(dialog, "members_see_own_only", False)),
        last_message_text=last.text if last and not last.is_deleted else ("Сообщение было удалено" if last and last.is_deleted else None),
        last_message_at=last.created_at if last else None,
    )


@router.delete("/group/dialogs/{dialog_id}", status_code=204)
def group_delete_dialog(
    dialog_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Полное удаление группы: только администратор. История и участники удаляются безвозвратно."""
    _require_group_admin(db, current_user, dialog_id)
    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    if not dialog:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    _unlink_group_dialog_upload_files(db, dialog_id)
    db.delete(dialog)
    db.commit()
    return None


@router.post("/group/dialogs/{dialog_id}/members/{user_id}", status_code=204)
def group_add_member(
    dialog_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
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
        member.joined_at = datetime.now(timezone.utc)
        is_new_or_reactivated = True

    if is_new_or_reactivated:
        dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
        join_label = "Подписался на канал" if dialog and dialog.is_channel else "Добавился"
        db.add(
            ChatMessage(
                group_dialog_id=dialog_id,
                sender_user_id=None,
                text=f"{join_label} {user_display_name(other)}",
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
    current_user: User = Depends(get_chat_user),
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
    else:
        dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
        if not dialog:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        _check_group_self_leave_allowed(db, dialog, current_user, member_target)

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
    before_id: int | None = Query(None),
    around_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    member = _require_group_active_member(db, current_user, dialog_id)
    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    restrict_uid = (
        _group_restrict_sender_user_id(db, current_user, dialog, member) if dialog else None
    )
    msgs = _messages_for_chat(
        db,
        group_dialog_id=dialog_id,
        group_visible_since=member.joined_at,
        group_restrict_sender_user_id=restrict_uid,
        after_id=after_id,
        before_id=before_id,
        around_id=around_id,
        limit=limit,
    )
    return _messages_to_responses(db, msgs, current_user)


@router.get("/group/dialogs/{dialog_id}/shared-media", response_model=ChatSharedMediaResponse)
def group_shared_media(
    dialog_id: int,
    category: str = Query(..., description="photos|videos|voice|files|links"),
    offset: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    member = _require_group_active_member(db, current_user, dialog_id)
    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    restrict_uid = (
        _group_restrict_sender_user_id(db, current_user, dialog, member) if dialog else None
    )
    return _shared_media_for_chat(
        db,
        category=category,
        offset=offset,
        limit=limit,
        group_dialog_id=dialog_id,
        group_visible_since=member.joined_at,
        group_restrict_sender_user_id=restrict_uid,
    )


@router.post("/group/dialogs/{dialog_id}/messages", response_model=ChatMessageResponse, status_code=201)
async def group_send(
    dialog_id: int,
    text: str | None = Form(None),
    reply_to_message_id: int | None = Form(None),
    is_voice_note: bool = Form(False),
    is_video_note: bool = Form(False),
    is_sticker: bool = Form(False),
    ack_required: bool = Form(False),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    member = _require_group_active_member(db, current_user, dialog_id)
    _require_group_post_permission(db, current_user, dialog_id)

    text_val = (text or "").strip() or None
    if not text_val and not files:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    if not dialog:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    if reply_to_message_id is not None:
        reply_to = db.query(ChatMessage).filter(ChatMessage.id == reply_to_message_id).first()
        if not reply_to:
            raise HTTPException(status_code=404, detail="Сообщение для ответа не найдено")
        if reply_to.group_dialog_id != dialog_id:
            raise HTTPException(status_code=400, detail="Нельзя отвечать на сообщение из другой группы")
        _require_group_message_visible(db, current_user, dialog, member, reply_to)
    if dialog and dialog.is_channel and reply_to_message_id is not None:
        raise HTTPException(status_code=400, detail="В канале нельзя отвечать на сообщения")
    if ack_required and (not dialog or not dialog.is_channel):
        raise HTTPException(status_code=400, detail="Кнопка «Ознакомиться» доступна только в каналах")

    msg = ChatMessage(
        group_dialog_id=dialog_id,
        sender_user_id=current_user.id,
        text=text_val,
        is_deleted=False,
        ack_required=bool(ack_required),
        reply_to_message_id=reply_to_message_id,
    )
    db.add(msg)
    db.flush()

    for f in files:
        await _save_message_attachment(
            db,
            msg.id,
            f,
            is_voice_note=is_voice_note,
            is_video_note=is_video_note,
        )

    db.commit()
    db.refresh(msg)
    recipients = _group_push_recipient_ids(db, dialog_id=dialog_id, exclude_user_id=current_user.id)
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


@router.post("/group/dialogs/{dialog_id}/polls", response_model=ChatMessageResponse, status_code=201)
def group_create_poll(
    dialog_id: int,
    body: ChatPollCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    member = _require_group_active_member(db, current_user, dialog_id)
    _require_group_post_permission(db, current_user, dialog_id)
    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    if not dialog:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    _validate_poll_reply(
        db,
        reply_to_message_id=body.reply_to_message_id,
        private_dialog_id=None,
        group_dialog_id=dialog_id,
    )
    if body.reply_to_message_id is not None:
        reply_to = db.query(ChatMessage).filter(ChatMessage.id == body.reply_to_message_id).first()
        if reply_to:
            _require_group_message_visible(db, current_user, dialog, member, reply_to)
    msg = create_chat_poll_message(
        db,
        sender=current_user,
        question=body.question,
        option_texts=body.options,
        allows_multiple=body.allows_multiple,
        reply_to_message_id=body.reply_to_message_id,
        group_dialog_id=dialog_id,
    )
    db.commit()
    db.refresh(msg)
    recipients = _group_push_recipient_ids(db, dialog_id=dialog_id, exclude_user_id=current_user.id)
    _send_chat_push_to_users(
        db,
        user_ids=recipients,
        title="Новый опрос (Группа)",
        body=body.question.strip(),
        data={"chatType": "group", "dialogId": str(dialog_id), "messageId": str(msg.id)},
    )
    return _poll_message_response(db, msg, current_user)


# --- Message edit/delete (shared) ---


@router.patch("/messages/{message_id}", response_model=ChatMessageResponse)
async def edit_message(
    message_id: int,
    data: ChatEditMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
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
    current_user: User = Depends(get_chat_user),
):
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    is_chat_admin = _is_chat_admin(current_user)

    # Доступ к чату
    if not is_chat_admin:
        if msg.private_dialog_id is None and msg.group_dialog_id is None:
            _require_general_active_member(db, current_user)
        elif msg.private_dialog_id is not None:
            _require_dialog_access(db, current_user, msg.private_dialog_id)
        else:
            _require_group_active_member(db, current_user, msg.group_dialog_id)
    else:
        if msg.private_dialog_id is not None:
            dialog = db.query(PrivateDialog).filter(PrivateDialog.id == msg.private_dialog_id).first()
            if not dialog:
                raise HTTPException(status_code=404, detail="Диалог не найден")
        elif msg.group_dialog_id is not None:
            dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == msg.group_dialog_id).first()
            if not dialog:
                raise HTTPException(status_code=404, detail="Группа не найдена")

    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Сообщение уже удалено")

    if msg.sender_user_id != current_user.id and not is_chat_admin:
        raise HTTPException(status_code=403, detail="Удалять можно только свои сообщения")

    msg.is_deleted = True
    db.commit()
    return None


@router.post("/messages/{message_id}/forward", response_model=ChatMessageResponse, status_code=201)
def forward_message(
    message_id: int,
    data: ChatForwardMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    src = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    if src.is_deleted:
        raise HTTPException(status_code=400, detail="Нельзя переслать удалённое сообщение")

    # Access to source message
    if src.private_dialog_id is None and src.group_dialog_id is None:
        _require_general_active_member(db, current_user)
    elif src.private_dialog_id is not None:
        _require_dialog_access(db, current_user, src.private_dialog_id)
    else:
        _require_group_active_member(db, current_user, src.group_dialog_id)

    target_type = (data.target_chat_type or "").strip().lower()
    target_dialog_id = data.target_dialog_id

    if target_type not in {"general", "private", "group"}:
        raise HTTPException(status_code=400, detail="Некорректный тип целевого чата")
    if target_type == "general":
        _require_general_active_member(db, current_user)
        private_dialog_id = None
        group_dialog_id = None
    elif target_type == "private":
        if target_dialog_id is None:
            raise HTTPException(status_code=400, detail="Для личного чата нужен target_dialog_id")
        _require_dialog_access(db, current_user, int(target_dialog_id))
        private_dialog_id = int(target_dialog_id)
        group_dialog_id = None
    else:
        if target_dialog_id is None:
            raise HTTPException(status_code=400, detail="Для группового чата нужен target_dialog_id")
        _require_group_active_member(db, current_user, int(target_dialog_id))
        private_dialog_id = None
        group_dialog_id = int(target_dialog_id)

    forwarded = ChatMessage(
        private_dialog_id=private_dialog_id,
        group_dialog_id=group_dialog_id,
        sender_user_id=current_user.id,
        text=src.text,
        is_deleted=False,
    )
    db.add(forwarded)
    db.flush()

    for a in list(src.attachments or []):
        db.add(
            ChatMessageAttachment(
                message_id=forwarded.id,
                url=a.url,
                media_type=a.media_type,
                filename=a.filename,
                mime_type=a.mime_type,
            )
        )

    db.commit()
    db.refresh(forwarded)

    if target_type == "general":
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
            body=(forwarded.text or "Пересланное вложение"),
            data={"chatType": "general", "messageId": str(forwarded.id)},
        )
    elif target_type == "private":
        dialog = _require_dialog_access(db, current_user, int(target_dialog_id))
        other_user_id = dialog.user2_id if dialog.user1_id == current_user.id else dialog.user1_id
        _send_chat_push_to_users(
            db,
            user_ids=[other_user_id],
            title=f"Новое сообщение ({user_display_name(current_user)})",
            body=(forwarded.text or "Пересланное вложение"),
            data={"chatType": "private", "dialogId": str(target_dialog_id), "messageId": str(forwarded.id)},
        )
    else:
        recipients = _group_push_recipient_ids(
            db, dialog_id=int(target_dialog_id), exclude_user_id=current_user.id
        )
        _send_chat_push_to_users(
            db,
            user_ids=recipients,
            title="Новое сообщение (Группа)",
            body=(forwarded.text or "Пересланное вложение"),
            data={"chatType": "group", "dialogId": str(target_dialog_id), "messageId": str(forwarded.id)},
        )

    return _to_message_response(
        forwarded,
        attachments=list(forwarded.attachments),
        include_sender=True,
        current_user_id=current_user.id,
        db=db,
    )


@router.put("/messages/{message_id}/reactions", response_model=ChatMessageResponse)
def message_set_reaction(
    message_id: int,
    body: ChatMessageReactionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _require_message_access(db, current_user, msg)
    updated_reactions = toggle_message_reaction(db, msg=msg, user=current_user, emoji=body.emoji)
    return _to_message_response(
        msg,
        attachments=list(msg.attachments or []),
        include_sender=msg.sender_user_id is not None,
        current_user_id=current_user.id,
        db=db,
        poll=poll_response_for_message(db, msg.id, current_user.id) if not msg.is_deleted else None,
        reactions=updated_reactions,
    )


@router.get("/messages/{message_id}/reactions/users", response_model=list[ChatUserShortResponse])
def message_reaction_users(
    message_id: int,
    emoji: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _require_message_access(db, current_user, msg)

    normalized = normalize_reaction_emoji(emoji)
    user_ids = [
        int(x[0])
        for x in db.query(ChatMessageReaction.user_id)
        .filter(ChatMessageReaction.message_id == message_id, ChatMessageReaction.emoji == normalized)
        .order_by(ChatMessageReaction.id.asc())
        .all()
    ]
    if not user_ids:
        return []
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    by_id = {int(u.id): u for u in users}
    out: list[ChatUserShortResponse] = []
    for uid in user_ids:
        u = by_id.get(uid)
        if not u:
            continue
        out.append(
            ChatUserShortResponse(
                id=u.id,
                username=u.username,
                display_name=user_display_name(u),
                is_active=bool(getattr(u, "is_active", True)),
                avatar_url=getattr(u, "avatar_url", None),
            )
        )
    return out


@router.post("/messages/{message_id}/poll/vote", response_model=ChatPollResponse)
def message_poll_vote(
    message_id: int,
    body: ChatPollVoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _require_message_access(db, current_user, msg)
    poll = (
        db.query(ChatPoll)
        .options(selectinload(ChatPoll.options))
        .filter(ChatPoll.message_id == message_id)
        .first()
    )
    if not poll:
        raise HTTPException(status_code=404, detail="Опрос не найден")
    return cast_poll_vote(db, poll=poll, user=current_user, option_ids=body.option_ids)


@router.post("/messages/{message_id}/acknowledge", status_code=204)
def message_acknowledge(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Сообщение удалено")
    if not msg.ack_required:
        raise HTTPException(status_code=400, detail="Для этого сообщения не требуется ознакомление")
    if msg.sender_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Автор публикации не нажимает «Ознакомиться»")

    _require_message_access(db, current_user, msg)
    recipient_ids = _message_read_recipient_user_ids(db, msg)
    if int(current_user.id) not in recipient_ids:
        raise HTTPException(status_code=403, detail="Ознакомление недоступно для этого сообщения")

    stmt = pg_insert(ChatMessageAcknowledgment.__table__).values(
        {"message_id": message_id, "user_id": current_user.id}
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["message_id", "user_id"])
    db.execute(stmt)
    db.commit()
    return None


@router.get("/messages/{message_id}/acknowledgments", response_model=ChatMessageReadsResponse)
def message_acknowledgments(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Сообщение удалено")

    _require_message_access(db, current_user, msg)
    _require_message_ack_stats_access(db, current_user, msg)

    recipient_ids = _message_read_recipient_user_ids(db, msg)
    if not recipient_ids:
        return ChatMessageReadsResponse(message_id=msg.id, read=[], unread=[], recipient_count=0)

    acks = (
        db.query(ChatMessageAcknowledgment)
        .filter(
            ChatMessageAcknowledgment.message_id == message_id,
            ChatMessageAcknowledgment.user_id.in_(recipient_ids),
        )
        .all()
    )
    ack_at_by_user = {int(a.user_id): a.acknowledged_at for a in acks}

    users = db.query(User).filter(User.id.in_(recipient_ids)).all()
    read_items: list[ChatMessageReadUserItem] = []
    unread_items: list[ChatMessageReadUserItem] = []
    for u in users:
        item = ChatMessageReadUserItem(
            user=ChatUserShortResponse(
                id=u.id,
                username=u.username,
                display_name=user_display_name(u),
                is_active=bool(u.is_active),
                avatar_url=u.avatar_url,
            ),
            read_at=ack_at_by_user.get(int(u.id)),
        )
        if item.read_at is not None:
            read_items.append(item)
        else:
            unread_items.append(item)

    read_items.sort(key=lambda x: x.read_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    unread_items.sort(key=lambda x: (x.user.display_name or x.user.username).lower())

    return ChatMessageReadsResponse(
        message_id=msg.id,
        read=read_items,
        unread=unread_items,
        recipient_count=len(recipient_ids),
    )


@router.get("/messages/{message_id}/reads", response_model=ChatMessageReadsResponse)
def message_reads(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Кто прочитал сообщение и кто ещё нет (для автора сообщения)."""
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Сообщение удалено")
    if msg.sender_user_id is None:
        raise HTTPException(status_code=400, detail="Для системных сообщений просмотр прочтений недоступен")

    _require_message_access(db, current_user, msg)
    if int(msg.sender_user_id) != int(current_user.id):
        raise HTTPException(status_code=403, detail="Просмотр прочтений доступен только для своих сообщений")

    recipient_ids = _message_read_recipient_user_ids(db, msg)
    if not recipient_ids:
        return ChatMessageReadsResponse(message_id=msg.id, read=[], unread=[], recipient_count=0)

    reads = (
        db.query(ChatMessageRead)
        .filter(
            ChatMessageRead.message_id == message_id,
            ChatMessageRead.user_id.in_(recipient_ids),
        )
        .all()
    )
    read_at_by_user = {int(r.user_id): r.read_at for r in reads}

    users = db.query(User).filter(User.id.in_(recipient_ids)).all()
    read_items: list[ChatMessageReadUserItem] = []
    unread_items: list[ChatMessageReadUserItem] = []
    for u in users:
        item = ChatMessageReadUserItem(
            user=ChatUserShortResponse(
                id=u.id,
                username=u.username,
                display_name=user_display_name(u),
                is_active=bool(u.is_active),
                avatar_url=u.avatar_url,
            ),
            read_at=read_at_by_user.get(int(u.id)),
        )
        if item.read_at is not None:
            read_items.append(item)
        else:
            unread_items.append(item)

    read_items.sort(key=lambda x: x.read_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    unread_items.sort(key=lambda x: (x.user.display_name or x.user.username).lower())

    return ChatMessageReadsResponse(
        message_id=msg.id,
        read=read_items,
        unread=unread_items,
        recipient_count=len(recipient_ids),
    )


def _insert_message_reads(db: Session, *, user_ids: list[int], message_ids: list[int]) -> None:
    unique_ids = list({int(x) for x in message_ids if int(x) > 0})
    unique_users = list({int(x) for x in user_ids if int(x) > 0})
    if not unique_ids or not unique_users:
        return
    rows = [{"message_id": msg_id, "user_id": uid} for msg_id in unique_ids for uid in unique_users]
    stmt = pg_insert(ChatMessageRead.__table__).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["message_id", "user_id"])
    db.execute(stmt)


def _personal_unread_exists_filter(user_id: int):
    return ~(
        select(1)
        .select_from(ChatMessageRead)
        .where(
            ChatMessageRead.user_id == user_id,
            ChatMessageRead.message_id == ChatMessage.id,
        )
        .exists()
    )


def _notification_non_bot_access_conditions(db: Session, user: User) -> list:
    # Общий чат скрыт из списка диалогов — в бейдж/push непрочитанных не включаем.
    conditions: list = []
    private_dialog_ids = _visible_private_dialog_ids_for_user(db, user)
    if private_dialog_ids:
        conditions.append(ChatMessage.private_dialog_id.in_(private_dialog_ids))
    group_conditions = _group_notification_visibility_conditions(db, user)
    if group_conditions:
        conditions.append(or_(*group_conditions))
    return conditions


def _notification_unread_summary(db: Session, user: User) -> tuple[int, ChatMessage | None]:
    non_bot_conditions = _notification_non_bot_access_conditions(db, user)
    personal_unread = _personal_unread_exists_filter(user.id)

    last_unread: ChatMessage | None = None
    unread_count = 0

    if non_bot_conditions:
        non_bot_query = db.query(ChatMessage).filter(
            ChatMessage.sender_user_id.isnot(None),
            ChatMessage.sender_user_id != user.id,
            ChatMessage.is_deleted == False,
            ChatMessage.bot_thread_user_id.is_(None),
            or_(*non_bot_conditions),
            personal_unread,
        )
        unread_count += int(non_bot_query.with_entities(func.count(ChatMessage.id)).scalar() or 0)
        last_non_bot = non_bot_query.order_by(ChatMessage.id.desc()).first()
        if last_non_bot is not None:
            last_unread = last_non_bot

    admin_ids = _chat_admin_user_ids(db)
    if _is_chat_admin(user):
        if admin_ids:
            admin_unread = ~(
                select(1)
                .select_from(ChatMessageRead)
                .where(
                    ChatMessageRead.user_id.in_(admin_ids),
                    ChatMessageRead.message_id == ChatMessage.id,
                )
                .exists()
            )
            bot_query = db.query(ChatMessage).filter(
                ChatMessage.bot_thread_user_id.isnot(None),
                ChatMessage.sender_user_id.isnot(None),
                ChatMessage.sender_user_id.notin_(admin_ids),
                ChatMessage.is_deleted == False,
                admin_unread,
            )
            bot_count = int(bot_query.with_entities(func.count(ChatMessage.id)).scalar() or 0)
            unread_count += bot_count
            last_bot = bot_query.order_by(ChatMessage.id.desc()).first()
            if last_bot is not None and (last_unread is None or last_bot.id > last_unread.id):
                last_unread = last_bot
    else:
        bot_query = db.query(ChatMessage).filter(
            ChatMessage.bot_thread_user_id == user.id,
            ChatMessage.sender_user_id.isnot(None),
            ChatMessage.sender_user_id != user.id,
            ChatMessage.is_deleted == False,
            personal_unread,
        )
        bot_count = int(bot_query.with_entities(func.count(ChatMessage.id)).scalar() or 0)
        unread_count += bot_count
        last_bot = bot_query.order_by(ChatMessage.id.desc()).first()
        if last_bot is not None and (last_unread is None or last_bot.id > last_unread.id):
            last_unread = last_bot

    return unread_count, last_unread


@router.post("/messages/mark-read", status_code=204)
def mark_messages_read(
    message_ids: list[int],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """
    Отметить сообщения как прочитанные текущим пользователем.
    """
    unique_ids = list({int(x) for x in (message_ids or []) if isinstance(x, int) and x > 0})
    if not unique_ids:
        return None
    _insert_message_reads(db, user_ids=[current_user.id], message_ids=unique_ids)
    db.commit()
    return None


@router.post("/messages/mark-read-all", status_code=204)
def mark_all_messages_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """
    Отметить как прочитанные все доступные текущему пользователю входящие сообщения.
    """
    general_member = db.query(GeneralChatMember).filter(
        GeneralChatMember.user_id == current_user.id,
        GeneralChatMember.is_active == True,
    ).first()
    can_access_general = general_member is not None

    private_dialog_ids = _visible_private_dialog_ids_for_user(db, current_user)

    access_conditions = []
    if can_access_general:
        access_conditions.append(_general_chat_message_filter())
    if private_dialog_ids:
        access_conditions.append(ChatMessage.private_dialog_id.in_(private_dialog_ids))
    group_conditions = _group_message_visibility_conditions(db, current_user)
    if group_conditions:
        access_conditions.append(or_(*group_conditions))
    if _is_chat_admin(current_user):
        access_conditions.append(ChatMessage.bot_thread_user_id.isnot(None))
    else:
        access_conditions.append(ChatMessage.bot_thread_user_id == current_user.id)
    if not access_conditions:
        return None

    unread_filter = ~db.query(ChatMessageRead.id).filter(
        ChatMessageRead.user_id == current_user.id,
        ChatMessageRead.message_id == ChatMessage.id,
    ).exists()
    unread_ids = [
        row_id
        for (row_id,) in db.query(ChatMessage.id).filter(
            ChatMessage.sender_user_id.isnot(None),
            ChatMessage.sender_user_id != current_user.id,
            ChatMessage.is_deleted == False,
            or_(*access_conditions),
            unread_filter,
        ).all()
    ]
    if unread_ids:
        _insert_message_reads(db, user_ids=[current_user.id], message_ids=unread_ids)
    db.commit()
    return None


@router.post("/general/mark-read", status_code=204)
def mark_general_chat_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Отметить прочитанными все входящие сообщения общего чата."""
    member = db.query(GeneralChatMember).filter(
        GeneralChatMember.user_id == current_user.id,
        GeneralChatMember.is_active == True,
    ).first()
    if not member:
        return None
    personal_unread = _personal_unread_exists_filter(current_user.id)
    unread_ids = [
        int(row_id)
        for (row_id,) in db.query(ChatMessage.id).filter(
            _general_chat_message_filter(),
            ChatMessage.sender_user_id.isnot(None),
            ChatMessage.sender_user_id != current_user.id,
            ChatMessage.is_deleted == False,
            personal_unread,
        ).all()
    ]
    if unread_ids:
        _insert_message_reads(db, user_ids=[current_user.id], message_ids=unread_ids)
        db.commit()
    return None


@router.post("/group/dialogs/{dialog_id}/mark-read", status_code=204)
def mark_group_dialog_read(
    dialog_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Отметить прочитанными все входящие сообщения группы (включая не загруженную историю)."""
    member = _require_group_active_member(db, current_user, dialog_id)
    dialog = db.query(GroupChatDialog).filter(GroupChatDialog.id == dialog_id).first()
    if not dialog:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    personal_unread = _personal_unread_exists_filter(current_user.id)
    q = db.query(ChatMessage.id).filter(
        ChatMessage.group_dialog_id == dialog_id,
        ChatMessage.sender_user_id.isnot(None),
        ChatMessage.sender_user_id != current_user.id,
        ChatMessage.is_deleted == False,
        ChatMessage.created_at >= member.joined_at,
        personal_unread,
    )
    restrict_uid = _group_restrict_sender_user_id(db, current_user, dialog, member)
    if restrict_uid is not None:
        q = q.filter(_group_own_messages_filter(restrict_uid))
    unread_ids = [int(row_id) for (row_id,) in q.all()]
    if unread_ids:
        _insert_message_reads(db, user_ids=[current_user.id], message_ids=unread_ids)
        db.commit()
    return None


@router.post("/private/dialogs/{dialog_id}/mark-read", status_code=204)
def mark_private_dialog_read(
    dialog_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Отметить прочитанными все входящие сообщения личного диалога."""
    visible_ids = _visible_private_dialog_ids_for_user(db, current_user)
    if dialog_id not in visible_ids:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    personal_unread = _personal_unread_exists_filter(current_user.id)
    unread_ids = [
        int(row_id)
        for (row_id,) in db.query(ChatMessage.id).filter(
            ChatMessage.private_dialog_id == dialog_id,
            ChatMessage.sender_user_id.isnot(None),
            ChatMessage.sender_user_id != current_user.id,
            ChatMessage.is_deleted == False,
            personal_unread,
        ).all()
    ]
    if unread_ids:
        _insert_message_reads(db, user_ids=[current_user.id], message_ids=unread_ids)
        db.commit()
    return None


def _resolve_user_wallpaper_url(user: User, db: Session) -> str | None:
    if user.chat_wallpaper_url and str(user.chat_wallpaper_url).strip():
        return str(user.chat_wallpaper_url).strip()
    if user.chat_wallpaper_id:
        wp = (
            db.query(ChatWallpaper)
            .filter(ChatWallpaper.id == user.chat_wallpaper_id, ChatWallpaper.is_active.is_(True))
            .first()
        )
        if wp and wp.url:
            return str(wp.url).strip()
    return None


@router.get("/wallpapers", response_model=list[ChatWallpaperItemResponse])
def list_chat_wallpapers(
    db: Session = Depends(get_db),
    _: User = Depends(get_chat_user),
):
    """Библиотека обоев для фона чата."""
    rows = (
        db.query(ChatWallpaper)
        .filter(ChatWallpaper.is_active.is_(True))
        .order_by(ChatWallpaper.sort_order.asc(), ChatWallpaper.id.asc())
        .all()
    )
    return rows


@router.get("/wallpaper/settings", response_model=ChatWallpaperSettingsResponse)
def get_chat_wallpaper_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    return ChatWallpaperSettingsResponse(
        wallpaper_id=current_user.chat_wallpaper_id,
        wallpaper_url=current_user.chat_wallpaper_url,
        resolved_url=_resolve_user_wallpaper_url(current_user, db),
    )


@router.patch("/wallpaper/settings", response_model=ChatWallpaperSettingsResponse)
def patch_chat_wallpaper_settings(
    data: ChatWallpaperSettingsBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Выбор обоев из библиотеки, своего изображения или сброс."""
    if data.reset:
        current_user.chat_wallpaper_id = None
        current_user.chat_wallpaper_url = None
    elif data.wallpaper_id is not None:
        wp = (
            db.query(ChatWallpaper)
            .filter(ChatWallpaper.id == data.wallpaper_id, ChatWallpaper.is_active.is_(True))
            .first()
        )
        if not wp:
            raise HTTPException(status_code=404, detail="Обои не найдены")
        current_user.chat_wallpaper_id = wp.id
        current_user.chat_wallpaper_url = None
    elif data.wallpaper_url is not None:
        url = str(data.wallpaper_url).strip()
        if url and not (url.startswith("/uploads/") or url.startswith("/chat-wallpapers/") or url.startswith("http")):
            raise HTTPException(status_code=400, detail="Недопустимый URL обоев")
        current_user.chat_wallpaper_url = url or None
        current_user.chat_wallpaper_id = None
    db.commit()
    db.refresh(current_user)
    return ChatWallpaperSettingsResponse(
        wallpaper_id=current_user.chat_wallpaper_id,
        wallpaper_url=current_user.chat_wallpaper_url,
        resolved_url=_resolve_user_wallpaper_url(current_user, db),
    )


@router.post("/wallpapers", response_model=ChatWallpaperItemResponse)
async def create_chat_wallpaper_library_item(
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Добавить обои в библиотеку (только администратор)."""
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Только для администраторов")
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Разрешены изображения: jpg, png, webp, gif, svg")
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 15 МБ)")
    unique_filename = f"chat-wallpaper-{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")
    url = f"/uploads/{unique_filename}"
    max_sort = db.query(func.max(ChatWallpaper.sort_order)).scalar() or 0
    row = ChatWallpaper(
        title=(title or "Обои").strip()[:128] or "Обои",
        url=url,
        thumb_url=url,
        sort_order=int(max_sort) + 10,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/notifications/settings", response_model=ChatNotificationsSettingsResponse)
def patch_chat_notifications_settings(
    data: ChatNotificationsSettingsBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """Включить или отключить push-уведомления о новых сообщениях и счётчик на сайте."""
    current_user.chat_notifications_enabled = bool(data.enabled)
    db.commit()
    db.refresh(current_user)
    return ChatNotificationsSettingsResponse(chat_notifications_enabled=bool(current_user.chat_notifications_enabled))


@router.get("/notifications/summary", response_model=ChatNotificationSummaryResponse)
def chat_notifications_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    """
    Сводка для мобильных уведомлений:
    - количество непрочитанных сообщений;
    - текст и отправитель последнего непрочитанного.
    """
    if not getattr(current_user, "chat_notifications_enabled", True):
        return ChatNotificationSummaryResponse(unread_count=0)

    unread_count, last_unread = _notification_unread_summary(db, current_user)
    if unread_count <= 0 or last_unread is None:
        return ChatNotificationSummaryResponse(unread_count=0)

    if last_unread.bot_thread_user_id is not None:
        last_unread_chat = "Поддержка"
    elif last_unread.private_dialog_id is None and last_unread.group_dialog_id is None:
        last_unread_chat = "Общий чат"
    elif last_unread.private_dialog_id is not None:
        last_unread_chat = "Личный чат"
    else:
        last_unread_chat = "Групповой чат"

    sender_name = user_display_name(last_unread.sender) if last_unread.sender else None
    if last_unread.bot_thread_user_id is not None:
        chat_type = "bot"
        dialog_id = None
        thread_user_id = int(last_unread.bot_thread_user_id)
    elif last_unread.group_dialog_id is not None:
        chat_type = "group"
        dialog_id = int(last_unread.group_dialog_id)
        thread_user_id = None
    elif last_unread.private_dialog_id is not None:
        chat_type = "private"
        dialog_id = int(last_unread.private_dialog_id)
        thread_user_id = None
    else:
        chat_type = "general"
        dialog_id = None
        thread_user_id = None

    return ChatNotificationSummaryResponse(
        unread_count=unread_count,
        last_message_text=last_unread.text,
        last_message_sender=sender_name,
        last_message_chat=last_unread_chat,
        last_message_id=int(last_unread.id),
        last_message_chat_type=chat_type,
        last_message_dialog_id=dialog_id,
        last_message_thread_user_id=thread_user_id,
    )

