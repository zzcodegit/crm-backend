"""Группы/каналы чата, куда автоматически добавляется новый пользователь CRM."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from chat_service import user_display_name
from models import ChatMessage, GroupChatDialog, GroupChatMember, User

SETTINGS_FILE = Path(__file__).resolve().parent / "logs" / "new_user_default_chat_groups.json"


def _normalize_dialog_ids(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for v in raw:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv > 0 and iv not in out:
            out.append(iv)
    return out


def load_default_chat_dialog_ids() -> list[int]:
    if not SETTINGS_FILE.exists():
        return []
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return _normalize_dialog_ids(data.get("dialog_ids", []))
    except Exception:
        return []


def save_default_chat_dialog_ids(dialog_ids: list[int]) -> list[int]:
    clean = _normalize_dialog_ids(dialog_ids)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps({"dialog_ids": clean}, ensure_ascii=False), encoding="utf-8")
    return clean


def apply_default_chat_groups_to_user(db: Session, user: User) -> None:
    """Добавляет пользователя в выбранные групповые чаты/каналы (без проверки админа чата)."""
    if not user.is_active:
        return
    dialog_ids = load_default_chat_dialog_ids()
    if not dialog_ids:
        return

    dialogs = db.query(GroupChatDialog).filter(GroupChatDialog.id.in_(dialog_ids)).all()
    by_id = {d.id: d for d in dialogs}

    for dialog_id in dialog_ids:
        dialog = by_id.get(dialog_id)
        if not dialog:
            continue
        member = (
            db.query(GroupChatMember)
            .filter(GroupChatMember.dialog_id == dialog_id, GroupChatMember.user_id == user.id)
            .first()
        )
        is_new_or_reactivated = False
        if not member:
            member = GroupChatMember(dialog_id=dialog_id, user_id=user.id, is_admin=False, is_active=True)
            db.add(member)
            is_new_or_reactivated = True
        elif not member.is_active:
            member.is_active = True
            member.left_at = None
            is_new_or_reactivated = True

        if is_new_or_reactivated:
            join_label = "Подписался на канал" if dialog.is_channel else "Добавился"
            db.add(
                ChatMessage(
                    group_dialog_id=dialog_id,
                    sender_user_id=None,
                    text=f"{join_label} {user_display_name(user)}",
                    is_deleted=False,
                )
            )
