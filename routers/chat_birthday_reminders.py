"""API настроек напоминаний о дне рождения в чате (только администратор CRM)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from birthday_chat_reminders import ALLOWED_DAYS_BEFORE, format_notify_time, parse_notify_time
from database import get_db
from deps import get_admin_user
from models import ChatBirthdayReminderRecipient, ChatBirthdayReminderRule, User
from schemas import (
    ChatBirthdayReminderRuleInput,
    ChatBirthdayReminderRuleResponse,
    ChatBirthdayReminderSettingsResponse,
    ChatBirthdayReminderSettingsUpdate,
    ChatUserShortResponse,
)
from chat_service import user_display_name

router = APIRouter(prefix="/api/users", tags=["chat-birthday-reminders"])


def _user_short(u: User) -> ChatUserShortResponse:
    return ChatUserShortResponse(
        id=u.id,
        username=u.username,
        display_name=user_display_name(u),
        is_active=bool(u.is_active),
        avatar_url=u.avatar_url,
    )


def _rule_to_response(rule: ChatBirthdayReminderRule) -> ChatBirthdayReminderRuleResponse:
    recipients = []
    for r in rule.recipients:
        if r.recipient_user:
            recipients.append(_user_short(r.recipient_user))
    return ChatBirthdayReminderRuleResponse(
        id=rule.id,
        enabled=bool(rule.enabled),
        days_before=int(rule.days_before),
        notify_time=format_notify_time(rule.notify_hour, rule.notify_minute),
        recipient_users=recipients,
    )


@router.get("/{user_id}/birthday-chat-reminders", response_model=ChatBirthdayReminderSettingsResponse)
def get_birthday_chat_reminders(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    subject = db.query(User).filter(User.id == user_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    rules = (
        db.query(ChatBirthdayReminderRule)
        .options(
            joinedload(ChatBirthdayReminderRule.recipients).joinedload(ChatBirthdayReminderRecipient.recipient_user)
        )
        .filter(ChatBirthdayReminderRule.subject_user_id == user_id)
        .order_by(ChatBirthdayReminderRule.days_before.asc(), ChatBirthdayReminderRule.id.asc())
        .all()
    )
    return ChatBirthdayReminderSettingsResponse(
        subject_user_id=user_id,
        subject_birth_date=subject.birth_date,
        rules=[_rule_to_response(r) for r in rules],
    )


@router.put("/{user_id}/birthday-chat-reminders", response_model=ChatBirthdayReminderSettingsResponse)
def put_birthday_chat_reminders(
    user_id: int,
    body: ChatBirthdayReminderSettingsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    subject = db.query(User).filter(User.id == user_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    existing = (
        db.query(ChatBirthdayReminderRule)
        .filter(ChatBirthdayReminderRule.subject_user_id == user_id)
        .all()
    )
    for old in existing:
        db.delete(old)
    db.flush()

    for item in body.rules:
        _validate_rule_input(db, user_id, item)
        hour, minute = parse_notify_time(item.notify_time)
        rule = ChatBirthdayReminderRule(
            subject_user_id=user_id,
            enabled=bool(item.enabled),
            days_before=int(item.days_before),
            notify_hour=hour,
            notify_minute=minute,
        )
        db.add(rule)
        db.flush()
        for rid in item.recipient_user_ids:
            db.add(ChatBirthdayReminderRecipient(rule_id=rule.id, recipient_user_id=rid))

    db.commit()
    rules = (
        db.query(ChatBirthdayReminderRule)
        .options(
            joinedload(ChatBirthdayReminderRule.recipients).joinedload(ChatBirthdayReminderRecipient.recipient_user)
        )
        .filter(ChatBirthdayReminderRule.subject_user_id == user_id)
        .order_by(ChatBirthdayReminderRule.days_before.asc(), ChatBirthdayReminderRule.id.asc())
        .all()
    )
    return ChatBirthdayReminderSettingsResponse(
        subject_user_id=user_id,
        subject_birth_date=subject.birth_date,
        rules=[_rule_to_response(r) for r in rules],
    )


def _validate_rule_input(db: Session, subject_user_id: int, item: ChatBirthdayReminderRuleInput) -> None:
    if item.days_before not in ALLOWED_DAYS_BEFORE:
        raise HTTPException(
            status_code=400,
            detail=f"days_before должен быть одним из: {sorted(ALLOWED_DAYS_BEFORE)}",
        )
    parse_notify_time(item.notify_time)
    if not item.recipient_user_ids:
        raise HTTPException(status_code=400, detail="Укажите хотя бы одного получателя уведомления")
    ids = list(dict.fromkeys(item.recipient_user_ids))
    users = db.query(User.id).filter(User.id.in_(ids), User.is_active == True).all()
    if len(users) != len(ids):
        raise HTTPException(status_code=400, detail="Некорректный получатель уведомления")
    if subject_user_id in ids:
        raise HTTPException(status_code=400, detail="Сотрудник не может быть получателем своего напоминания")
