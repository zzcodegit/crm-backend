"""Опросы в чате: создание, ответ API, голосование."""
from __future__ import annotations

from sqlalchemy.orm import Session

from fastapi import HTTPException
from models import ChatMessage, ChatPoll, ChatPollOption, ChatPollVote, User
from schemas import ChatPollOptionResponse, ChatPollResponse

MIN_POLL_OPTIONS = 2
MAX_POLL_OPTIONS = 10
MAX_POLL_QUESTION_LEN = 500
MAX_POLL_OPTION_LEN = 200


def normalize_poll_options(raw: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        t = (item or "").strip()
        if not t:
            continue
        if len(t) > MAX_POLL_OPTION_LEN:
            t = t[:MAX_POLL_OPTION_LEN]
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def create_poll_for_message(
    db: Session,
    *,
    message: ChatMessage,
    question: str,
    option_texts: list[str],
    allows_multiple: bool = False,
) -> ChatPoll:
    q = (question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Введите вопрос опроса")
    if len(q) > MAX_POLL_QUESTION_LEN:
        raise HTTPException(status_code=400, detail="Вопрос слишком длинный")
    opts = normalize_poll_options(option_texts)
    if len(opts) < MIN_POLL_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Добавьте минимум {MIN_POLL_OPTIONS} варианта ответа")
    if len(opts) > MAX_POLL_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Не больше {MAX_POLL_OPTIONS} вариантов")

    poll = ChatPoll(
        message_id=message.id,
        question=q,
        allows_multiple=bool(allows_multiple),
    )
    db.add(poll)
    db.flush()
    for i, text in enumerate(opts):
        db.add(ChatPollOption(poll_id=poll.id, text=text, position=i))
    db.flush()
    return poll


def _polls_for_messages(
    db: Session,
    message_ids: list[int],
    current_user_id: int | None,
) -> dict[int, ChatPollResponse]:
    if not message_ids:
        return {}
    polls = db.query(ChatPoll).filter(ChatPoll.message_id.in_(message_ids)).all()
    if not polls:
        return {}
    poll_ids = [p.id for p in polls]
    options = (
        db.query(ChatPollOption)
        .filter(ChatPollOption.poll_id.in_(poll_ids))
        .order_by(ChatPollOption.poll_id.asc(), ChatPollOption.position.asc())
        .all()
    )
    votes = db.query(ChatPollVote).filter(ChatPollVote.poll_id.in_(poll_ids)).all()

    options_by_poll: dict[int, list[ChatPollOption]] = {}
    for o in options:
        options_by_poll.setdefault(o.poll_id, []).append(o)

    vote_count_by_option: dict[int, int] = {}
    voters_by_poll: dict[int, set[int]] = {}
    my_votes_by_poll: dict[int, list[int]] = {}
    for v in votes:
        vote_count_by_option[v.option_id] = vote_count_by_option.get(v.option_id, 0) + 1
        voters_by_poll.setdefault(v.poll_id, set()).add(v.user_id)
        if current_user_id is not None and v.user_id == current_user_id:
            my_votes_by_poll.setdefault(v.poll_id, []).append(v.option_id)

    out: dict[int, ChatPollResponse] = {}
    for p in polls:
        opts = options_by_poll.get(p.id, [])
        total_voters = len(voters_by_poll.get(p.id, set()))
        out[p.message_id] = ChatPollResponse(
            id=p.id,
            question=p.question,
            allows_multiple=bool(p.allows_multiple),
            total_voters=total_voters,
            my_option_ids=my_votes_by_poll.get(p.id, []),
            options=[
                ChatPollOptionResponse(
                    id=o.id,
                    text=o.text,
                    position=o.position,
                    vote_count=vote_count_by_option.get(o.id, 0),
                )
                for o in opts
            ],
        )
    return out


def poll_response_for_message(
    db: Session,
    message_id: int,
    current_user_id: int | None,
) -> ChatPollResponse | None:
    return _polls_for_messages(db, [message_id], current_user_id).get(message_id)


def create_chat_poll_message(
    db: Session,
    *,
    sender: User,
    question: str,
    option_texts: list[str],
    allows_multiple: bool = False,
    reply_to_message_id: int | None = None,
    private_dialog_id: int | None = None,
    group_dialog_id: int | None = None,
    ack_required: bool = False,
) -> ChatMessage:
    q = (question or "").strip()
    msg = ChatMessage(
        private_dialog_id=private_dialog_id,
        group_dialog_id=group_dialog_id,
        sender_user_id=sender.id,
        text=q,
        is_deleted=False,
        reply_to_message_id=reply_to_message_id,
        ack_required=bool(ack_required),
    )
    db.add(msg)
    db.flush()
    create_poll_for_message(
        db,
        message=msg,
        question=q,
        option_texts=option_texts,
        allows_multiple=allows_multiple,
    )
    return msg


def cast_poll_vote(
    db: Session,
    *,
    poll: ChatPoll,
    user: User,
    option_ids: list[int],
) -> ChatPollResponse:
    msg = db.query(ChatMessage).filter(ChatMessage.id == poll.message_id).first()
    if not msg or msg.is_deleted:
        raise HTTPException(status_code=400, detail="Опрос удалён")

    valid_ids = {o.id for o in poll.options}
    chosen = []
    seen: set[int] = set()
    for oid in option_ids:
        if oid not in valid_ids or oid in seen:
            continue
        seen.add(oid)
        chosen.append(oid)

    if not chosen:
        db.query(ChatPollVote).filter(
            ChatPollVote.poll_id == poll.id,
            ChatPollVote.user_id == user.id,
        ).delete(synchronize_session=False)
        db.commit()
        db.refresh(poll)
        resp = poll_response_for_message(db, poll.message_id, user.id)
        if resp is None:
            raise HTTPException(status_code=500, detail="Ошибка опроса")
        return resp

    if not poll.allows_multiple and len(chosen) > 1:
        raise HTTPException(status_code=400, detail="В этом опросе можно выбрать только один вариант")

    db.query(ChatPollVote).filter(
        ChatPollVote.poll_id == poll.id,
        ChatPollVote.user_id == user.id,
    ).delete(synchronize_session=False)
    for oid in chosen:
        db.add(ChatPollVote(poll_id=poll.id, option_id=oid, user_id=user.id))
    db.commit()
    db.refresh(poll)
    resp = poll_response_for_message(db, poll.message_id, user.id)
    if resp is None:
        raise HTTPException(status_code=500, detail="Ошибка опроса")
    return resp
