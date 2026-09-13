from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models import ChatMessage, ChatMessageAttachment, GeneralChatMember, User


CHAT_URL_RE = re.compile(
    r"(https?://[^\s<>\[\]\"']+(?:[^\s<>\[\]\"'.,;:!?)]*)|(?:www\.)[a-zA-Z0-9][-a-zA-Z0-9.]*[^\s<>\[\]\"']*)",
    re.IGNORECASE,
)


EDIT_WINDOW_MINUTES = 15


def user_display_name(user: User) -> str:
    parts = [user.first_name, user.last_name, user.patronymic]
    name = " ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    return name or (user.username or str(user.id))


def ensure_general_chat_member(
    db: Session,
    user: User,
    *,
    desired_is_active: bool,
    only_create: bool,
) -> GeneralChatMember:
    """
    only_create=True:
      - создаём запись, если её нет
      - но не реактивируем, если участник уже есть, но "вышел"
    """
    member = db.query(GeneralChatMember).filter(GeneralChatMember.user_id == user.id).first()
    if not member:
        member = GeneralChatMember(user_id=user.id, is_active=desired_is_active)
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    if not only_create and member.is_active != desired_is_active:
        member.is_active = desired_is_active
        if not desired_is_active:
            member.left_at = datetime.now(timezone.utc)
        else:
            member.left_at = None
        db.commit()
        db.refresh(member)
    return member


CALL_LOG_PREFIX = "📞 "


def private_call_log_text(*, missed: bool, video: bool, duration_sec: int | None = None) -> str:
    media = "видеозвонок" if video else "аудиозвонок"
    if missed:
        return f"{CALL_LOG_PREFIX}Пропущенный {media}"
    if duration_sec is not None and duration_sec > 0:
        m, s = divmod(int(duration_sec), 60)
        dur = f"{m}:{s:02d}" if m else f"0:{s:02d}"
        return f"{CALL_LOG_PREFIX}{media.capitalize()} · {dur}"
    return f"{CALL_LOG_PREFIX}{media.capitalize()}"


def add_private_call_log_message(db: Session, *, dialog_id: int, text: str) -> ChatMessage:
    """Системная запись о звонке в личном чате."""
    msg = ChatMessage(
        private_dialog_id=dialog_id,
        sender_user_id=None,
        text=text,
        is_deleted=False,
    )
    db.add(msg)
    db.flush()
    return msg


def add_general_system_message(db: Session, *, text: str) -> ChatMessage:
    """
    Системное сообщение в общем чате: sender_user_id=None.
    """
    msg = ChatMessage(private_dialog_id=None, sender_user_id=None, text=text, is_deleted=False)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def add_user_joined_general_chat_message(db: Session, *, user: User) -> ChatMessage:
    text = f"Добавился {user_display_name(user)}"
    return add_general_system_message(db, text=text)


def can_edit_message(message: ChatMessage, *, now_utc: datetime | None = None) -> bool:
    if message.is_deleted:
        return False
    if message.created_at is None:
        return False
    if message.created_at.tzinfo is None:
        now_utc = now_utc or datetime.utcnow()
    else:
        now_utc = now_utc or datetime.now(timezone.utc)

    return message.created_at + timedelta(minutes=EDIT_WINDOW_MINUTES) >= now_utc


def extract_chat_urls(text: str | None) -> list[str]:
    if not text or not text.strip():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in CHAT_URL_RE.finditer(text):
        u = m.group(0).rstrip(".,;:!?)\"'")
        key = u.lower()
        if key in seen:
            continue
        seen.add(key)
        if u.lower().startswith("www."):
            u = "https://" + u
        out.append(u)
    return out


def normalize_attachment_media_type(att: ChatMessageAttachment) -> str:
    raw = (att.media_type or "").strip().lower()
    filename = (att.filename or "").strip().lower()
    if filename.startswith("sticker-") and raw in {"image", "sticker"}:
        return "sticker"
    if raw in {"image", "video", "audio", "sticker", "file"}:
        mime = (att.mime_type or "").strip().lower()
        if raw == "video" and filename.startswith("voice-") and filename.endswith(".webm"):
            return "audio"
        if raw == "video" and mime.startswith("audio/"):
            return "audio"
        return raw
    return raw or "video"


def is_voice_attachment(att: ChatMessageAttachment) -> bool:
    mt = normalize_attachment_media_type(att)
    fn = (att.filename or "").strip().lower()
    mime = (att.mime_type or "").strip().lower()
    if mt == "audio":
        return True
    if fn.startswith("voice-"):
        return True
    if mime.startswith("audio/"):
        return True
    return False


def attachment_matches_shared_category(att: ChatMessageAttachment, category: str) -> bool:
    mt = normalize_attachment_media_type(att)
    if mt == "sticker":
        return False
    if category == "photos":
        return mt == "image"
    if category == "videos":
        return mt == "video" and not is_voice_attachment(att)
    if category == "voice":
        return is_voice_attachment(att)
    if category == "files":
        return mt == "file"
    return False

