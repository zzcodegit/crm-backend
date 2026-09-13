"""Напоминания о днях рождения в личный чат (от служебного пользователя CRM)."""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from auth import get_password_hash
from chat_service import user_display_name
from database import SessionLocal
from models import (
    ChatBirthdayReminderRecipient,
    ChatBirthdayReminderRule,
    ChatBirthdayReminderSentLog,
    ChatMessage,
    PrivateDialog,
    PushDeviceToken,
    User,
    WebPushSubscription,
)
from chat_push_delivery import chat_open_url_from_data
from push_service import send_push_to_tokens
from webpush_service import send_web_push

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")
NOTIFY_BOT_USERNAME = "crm_notify"
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

ALLOWED_DAYS_BEFORE = {0, 1, 3, 7, 14, 30}

_worker_started = False
_worker_lock = threading.Lock()


def parse_notify_time(value: str) -> tuple[int, int]:
    m = _TIME_RE.match((value or "").strip())
    if not m:
        raise ValueError("Время должно быть в формате ЧЧ:ММ (например 09:00)")
    return int(m.group(1)), int(m.group(2))


def format_notify_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def ensure_notify_bot_user(db: Session) -> User:
    bot = db.query(User).filter(User.username == NOTIFY_BOT_USERNAME).first()
    if bot:
        return bot
    bot = User(
        username=NOTIFY_BOT_USERNAME,
        hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        is_active=True,
        first_name="CRM",
        last_name="Уведомления",
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    logger.info("Created chat notify bot user id=%s", bot.id)
    return bot


def ensure_private_dialog(db: Session, user_a_id: int, user_b_id: int) -> PrivateDialog:
    if user_a_id == user_b_id:
        raise ValueError("Cannot create dialog with self")
    dialog = (
        db.query(PrivateDialog)
        .filter(
            or_(
                and_(PrivateDialog.user1_id == user_a_id, PrivateDialog.user2_id == user_b_id),
                and_(PrivateDialog.user1_id == user_b_id, PrivateDialog.user2_id == user_a_id),
            )
        )
        .first()
    )
    if dialog:
        if dialog.user1_id == user_a_id:
            dialog.user1_hidden = False
        else:
            dialog.user2_hidden = False
        db.commit()
        db.refresh(dialog)
        return dialog
    dialog = PrivateDialog(user1_id=user_a_id, user2_id=user_b_id)
    db.add(dialog)
    db.commit()
    db.refresh(dialog)
    return dialog


def _send_chat_push(db: Session, *, user_ids: list[int], title: str, body: str, data: dict[str, str]) -> None:
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
        subscriptions=[{"endpoint": r.endpoint, "p256dh": r.p256dh, "auth": r.auth} for r in web_rows],
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


def _birthday_on_year(birth: date, year: int) -> date:
    try:
        return date(year, birth.month, birth.day)
    except ValueError:
        # 29 февраля → 28 февраля в невисокосный год
        return date(year, 2, 28)


def _reminder_message_text(*, subject: User, days_before: int, birthday_date: date) -> str:
    name = user_display_name(subject)
    login = subject.username or ""
    bday_fmt = birthday_date.strftime("%d.%m")
    if days_before == 0:
        return f"🎂 Сегодня день рождения у {name} (@{login}). Дата: {bday_fmt}."
    if days_before == 1:
        return f"🎂 Завтра ({bday_fmt}) день рождения у {name} (@{login})."
    return f"🎂 Через {days_before} дн. ({bday_fmt}) день рождения у {name} (@{login})."


def send_birthday_reminder_chat(
    db: Session,
    *,
    bot: User,
    subject: User,
    recipient: User,
    days_before: int,
    birthday_date: date,
) -> ChatMessage:
    dialog = ensure_private_dialog(db, bot.id, recipient.id)
    text = _reminder_message_text(subject=subject, days_before=days_before, birthday_date=birthday_date)
    msg = ChatMessage(
        private_dialog_id=dialog.id,
        sender_user_id=bot.id,
        text=text,
        is_deleted=False,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    _send_chat_push(
        db,
        user_ids=[recipient.id],
        title="Напоминание о дне рождения",
        body=text,
        data={"chatType": "private", "dialogId": str(dialog.id), "messageId": str(msg.id)},
    )
    return msg


def _already_sent(db: Session, *, rule_id: int, recipient_id: int, fire_date: date) -> bool:
    return (
        db.query(ChatBirthdayReminderSentLog.id)
        .filter(
            ChatBirthdayReminderSentLog.rule_id == rule_id,
            ChatBirthdayReminderSentLog.recipient_user_id == recipient_id,
            ChatBirthdayReminderSentLog.fire_date == fire_date,
        )
        .first()
        is not None
    )


def _log_sent(db: Session, *, rule_id: int, recipient_id: int, fire_date: date) -> None:
    db.add(
        ChatBirthdayReminderSentLog(
            rule_id=rule_id,
            recipient_user_id=recipient_id,
            fire_date=fire_date,
        )
    )
    db.commit()


def process_due_birthday_reminders(db: Session, *, now_msk: datetime | None = None) -> int:
    """Проверяет правила и отправляет напоминания. Возвращает число отправленных сообщений."""
    now_msk = now_msk or datetime.now(MSK)
    today = now_msk.date()
    hour, minute = now_msk.hour, now_msk.minute

    bot = ensure_notify_bot_user(db)
    rules = (
        db.query(ChatBirthdayReminderRule)
        .options(joinedload(ChatBirthdayReminderRule.recipients))
        .filter(ChatBirthdayReminderRule.enabled == True)
        .all()
    )
    sent_count = 0
    for rule in rules:
        if rule.notify_hour != hour or rule.notify_minute != minute:
            continue
        subject = db.query(User).filter(User.id == rule.subject_user_id, User.is_active == True).first()
        if not subject or not subject.birth_date:
            continue
        if rule.days_before not in ALLOWED_DAYS_BEFORE:
            continue
        birthday = _birthday_on_year(subject.birth_date, today.year)
        reminder_date = birthday - timedelta(days=rule.days_before)
        if reminder_date != today:
            continue
        recipient_ids = [r.recipient_user_id for r in rule.recipients]
        if not recipient_ids:
            continue
        recipients = (
            db.query(User)
            .filter(User.id.in_(recipient_ids), User.is_active == True)
            .all()
        )
        for recipient in recipients:
            if recipient.id == bot.id:
                continue
            if _already_sent(db, rule_id=rule.id, recipient_id=recipient.id, fire_date=today):
                continue
            try:
                send_birthday_reminder_chat(
                    db,
                    bot=bot,
                    subject=subject,
                    recipient=recipient,
                    days_before=rule.days_before,
                    birthday_date=birthday,
                )
                _log_sent(db, rule_id=rule.id, recipient_id=recipient.id, fire_date=today)
                sent_count += 1
            except Exception:
                logger.exception(
                    "birthday reminder failed rule=%s recipient=%s subject=%s",
                    rule.id,
                    recipient.id,
                    subject.id,
                )
    return sent_count


def _worker_loop() -> None:
    while True:
        try:
            db = SessionLocal()
            try:
                n = process_due_birthday_reminders(db)
                if n:
                    logger.info("Birthday chat reminders sent: %s", n)
            finally:
                db.close()
        except Exception:
            logger.exception("Birthday reminder worker tick failed")
        time.sleep(60)


def start_birthday_reminder_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        t = threading.Thread(target=_worker_loop, name="birthday-chat-reminders", daemon=True)
        t.start()
        logger.info("Birthday chat reminder worker started")
