"""Реакции на сообщения чата."""
from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import ChatMessage, ChatMessageReaction, User
from schemas import ChatReactionSummary

MAX_EMOJI_LEN = 32

QUICK_REACTION_EMOJIS = ("👍", "❤️", "😂", "😮", "😢", "🙏", "🔥")


def normalize_reaction_emoji(raw: str) -> str:
    emoji = (raw or "").strip()
    if not emoji:
        raise HTTPException(status_code=400, detail="Укажите эмодзи")
    if len(emoji) > MAX_EMOJI_LEN:
        raise HTTPException(status_code=400, detail="Слишком длинная реакция")
    return emoji


def _summaries_for_rows(
    rows: list[ChatMessageReaction],
    *,
    current_user_id: int | None,
) -> list[ChatReactionSummary]:
    by_emoji: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        by_emoji[row.emoji].append(int(row.user_id))
    out: list[ChatReactionSummary] = []
    for emoji in sorted(by_emoji.keys()):
        user_ids = by_emoji[emoji]
        out.append(
            ChatReactionSummary(
                emoji=emoji,
                count=len(user_ids),
                reacted_by_me=current_user_id is not None and current_user_id in user_ids,
            )
        )
    return out


def reactions_for_messages(
    db: Session,
    message_ids: list[int],
    current_user_id: int | None,
) -> dict[int, list[ChatReactionSummary]]:
    if not message_ids:
        return {}
    rows = (
        db.query(ChatMessageReaction)
        .filter(ChatMessageReaction.message_id.in_(message_ids))
        .order_by(ChatMessageReaction.id.asc())
        .all()
    )
    grouped: dict[int, list[ChatMessageReaction]] = defaultdict(list)
    for row in rows:
        grouped[int(row.message_id)].append(row)
    return {
        mid: _summaries_for_rows(grouped[mid], current_user_id=current_user_id)
        for mid in message_ids
        if mid in grouped
    }


def toggle_message_reaction(
    db: Session,
    *,
    msg: ChatMessage,
    user: User,
    emoji: str,
) -> list[ChatReactionSummary]:
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Сообщение удалено")
    normalized = normalize_reaction_emoji(emoji)
    existing = (
        db.query(ChatMessageReaction)
        .filter(
            ChatMessageReaction.message_id == msg.id,
            ChatMessageReaction.user_id == user.id,
        )
        .first()
    )
    if existing is not None:
        if existing.emoji == normalized:
            db.delete(existing)
        else:
            existing.emoji = normalized
    else:
        db.add(
            ChatMessageReaction(
                message_id=msg.id,
                user_id=user.id,
                emoji=normalized,
            )
        )
    db.commit()
    rows = (
        db.query(ChatMessageReaction)
        .filter(ChatMessageReaction.message_id == msg.id)
        .order_by(ChatMessageReaction.id.asc())
        .all()
    )
    return _summaries_for_rows(rows, current_user_id=int(user.id))
