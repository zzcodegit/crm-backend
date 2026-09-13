"""GigaChat: диалог с нейросетью (персональный тред на пользователя)."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
import re

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from config import settings
from database import get_db
from deps import get_chat_user
from models import ChatMessage, ChatMessageRead, TrainingArticle, User
from routers.chat import _messages_to_responses, _send_chat_push_to_users, user_display_name
from schemas import ChatMessageResponse


router = APIRouter(prefix="/api/chat/gigachat", tags=["chat-gigachat"])


class GigaChatSendBody(BaseModel):
    text: str = Field(..., min_length=1)
    mode: str | None = None  # legacy (frontend no longer sends it)
    context_text: str | None = None  # legacy
    context_url: str | None = None  # legacy


def _gigachat_api_url() -> str:
    return (settings.gigachat_api_url or "").strip() or "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


def _gigachat_model() -> str:
    return (settings.gigachat_model or "").strip() or "GigaChat"


def _gigachat_bearer_token() -> str | None:
    v = (settings.gigachat_bearer_token or "").strip()
    return v or None


_oauth_cache: dict[str, object] = {"token": None, "expires_at": 0.0}


def _requests_verify() -> bool | str:
    if settings.gigachat_ca_bundle and settings.gigachat_ca_bundle.strip():
        return settings.gigachat_ca_bundle.strip()
    return bool(settings.gigachat_verify_ssl)


def _get_access_token() -> str:
    """Returns Bearer token for calling GigaChat API."""
    direct = _gigachat_bearer_token()
    if direct:
        return direct

    auth_key = (getattr(settings, "gigachat_auth_key", None) or "").strip()
    if not auth_key:
        raise HTTPException(status_code=503, detail="GigaChat не настроен: отсутствует GIGACHAT_AUTH_KEY")

    now = time.time()
    cached = _oauth_cache.get("token")
    exp = float(_oauth_cache.get("expires_at") or 0.0)
    if isinstance(cached, str) and cached and exp - now > 30:
        return cached

    oauth_url = (getattr(settings, "gigachat_oauth_url", None) or "").strip() or "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    try:
        r = requests.post(
            oauth_url,
            headers={
                "Authorization": f"Basic {auth_key}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
            },
            data={"scope": "GIGACHAT_API_PERS"},
            timeout=25,
            verify=_requests_verify(),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Не удалось получить токен GigaChat: {e!s}")

    if r.status_code >= 400:
        txt = (r.text or "").strip()
        if len(txt) > 800:
            txt = txt[:800] + "…"
        raise HTTPException(status_code=502, detail=f"GigaChat OAuth {r.status_code}: {txt}")

    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="GigaChat OAuth вернул не-JSON ответ")

    token = (data.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=502, detail="GigaChat OAuth: access_token отсутствует в ответе")

    expires_at = 0.0
    raw_exp = data.get("expires_at") or data.get("expiresAt") or 0
    try:
        expires_at = float(raw_exp)
        if expires_at > 10_000_000_000:  # ms
            expires_at = expires_at / 1000.0
    except Exception:
        expires_at = now + 25 * 60

    _oauth_cache["token"] = token
    _oauth_cache["expires_at"] = expires_at
    return token


def _build_system_prompt(mode: str, context_text: str | None, context_url: str | None) -> str:
    ctx = []
    if context_url and context_url.strip():
        ctx.append(f"Ссылка на материал: {context_url.strip()}")
    if context_text and context_text.strip():
        ctx.append(f"Текст/контекст:\n{context_text.strip()}")
    ctx_block = ("\n\n".join(ctx)).strip()

    if mode == "edit":
        base = (
            "Ты редактор русского текста. Исправь ошибки, сделай текст более грамотным и понятным. "
            "У тебя НЕТ доступа к вебу и ты НЕ открываешь ссылки: работай ТОЛЬКО с текстом из поля «Текст/контекст». "
            "НЕ пиши фразы вроде «не могу открыть ссылку» или «пришлите текст» — текст уже дан. "
            "Верни только итоговый исправленный текст, без объяснений и без Markdown."
        )
        return f"{base}\n\n{ctx_block}".strip() if ctx_block else base

    base = "Ты полезный ассистент. Отвечай кратко и по делу, на русском языке."
    return f"{base}\n\n{ctx_block}".strip() if ctx_block else base


_dialog_state: dict[int, dict[str, object]] = {}


def _looks_like_url(text: str) -> bool:
    t = (text or "").strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def _is_edit_article_intent(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    # very simple RU intent heuristic
    return ("отредакт" in t or "исправ" in t) and ("стать" in t or "текст" in t)


def _extract_first_url(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"https?://[^\s)]+", text.strip())
    return m.group(0).strip() if m else None


def _parse_training_article_id_from_url(url: str) -> int | None:
    """Parse /training/<id>/edit from a URL."""
    if not url:
        return None
    m = re.search(r"/training/(\d+)/edit\b", url)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _html_to_text(html: str) -> str:
    """Very small HTML->text helper for prompts (no deps)."""
    if not html:
        return ""
    s = html
    s = re.sub(r"(?is)<\s*br\s*/?\s*>", "\n", s)
    s = re.sub(r"(?is)</\s*p\s*>", "\n\n", s)
    s = re.sub(r"(?is)<\s*li\s*>", "- ", s)
    s = re.sub(r"(?is)</\s*li\s*>", "\n", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = (
        s.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _load_training_article_text(db: Session, url: str) -> str | None:
    aid = _parse_training_article_id_from_url(url)
    if not aid:
        return None
    item = db.query(TrainingArticle).filter(TrainingArticle.id == aid).first()
    if not item:
        return None
    return _html_to_text(item.content_html or "")


def _is_article_text_enough(text: str) -> bool:
    t = (text or "").strip()
    # Very short texts usually mean the article body is empty / not saved yet.
    return len(t) >= 80


def _call_gigachat(
    *,
    user_text: str,
    mode: str,
    context_text: str | None,
    context_url: str | None,
    history: list[dict[str, str]] | None = None,
) -> str:
    token = _get_access_token()

    history_msgs = [
        m
        for m in (history or [])
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    payload = {
        "model": _gigachat_model(),
        "messages": [
            {"role": "system", "content": _build_system_prompt(mode, context_text, context_url)},
            *history_msgs,
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.2 if mode == "edit" else 0.7,
    }
    try:
        resp = requests.post(
            _gigachat_api_url(),
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=40,
            verify=_requests_verify(),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Не удалось обратиться к GigaChat: {e!s}")

    if resp.status_code >= 400:
        detail = resp.text.strip()
        if len(detail) > 800:
            detail = detail[:800] + "…"
        raise HTTPException(status_code=502, detail=f"GigaChat вернул ошибку {resp.status_code}: {detail}")

    try:
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="GigaChat вернул не-JSON ответ")

    # OpenAI-like schema: choices[0].message.content
    try:
        choices = data.get("choices") or []
        msg = choices[0].get("message") if choices else None
        content = (msg or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception:
        pass

    # Fallback
    raise HTTPException(status_code=502, detail="GigaChat вернул неожиданный формат ответа")


def _gigachat_query(db: Session, thread_user_id: int):
    return (
        db.query(ChatMessage)
        .options(selectinload(ChatMessage.attachments), selectinload(ChatMessage.sender))
        .filter(
            ChatMessage.gigachat_thread_user_id == thread_user_id,
            ChatMessage.private_dialog_id.is_(None),
            ChatMessage.group_dialog_id.is_(None),
        )
    )


def _load_thread_history(db: Session, thread_user_id: int, *, limit: int) -> list[dict[str, str]]:
    rows = (
        _gigachat_query(db, thread_user_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    out: list[dict[str, str]] = []
    for m in rows:
        txt = (m.text or "").strip()
        if not txt or m.is_deleted:
            continue
        role = "user" if m.sender_user_id is not None else "assistant"
        out.append({"role": role, "content": txt})
    return out


@router.get("/messages", response_model=list[ChatMessageResponse])
def gigachat_messages(
    after_id: int | None = Query(None),
    before_id: int | None = Query(None),
    around_id: int | None = Query(None),
    limit: int = Query(80, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    q = _gigachat_query(db, int(current_user.id))
    if around_id is not None:
        half = max(limit // 2, 20)
        before_msgs = list(reversed(q.filter(ChatMessage.id < around_id).order_by(ChatMessage.id.desc()).limit(half).all()))
        center = q.filter(ChatMessage.id == around_id).first()
        after_msgs = list(q.filter(ChatMessage.id > around_id).order_by(ChatMessage.id.asc()).limit(half).all())
        msgs = before_msgs + ([center] if center else []) + after_msgs
    else:
        if after_id is not None:
            q = q.filter(ChatMessage.id > after_id)
        if before_id is not None:
            q = q.filter(ChatMessage.id < before_id)
        msgs = list(reversed(q.order_by(ChatMessage.id.desc()).limit(limit).all()))

    # Reuse standard response mapping
    return _messages_to_responses(db, msgs, current_user)


@router.post("/messages", response_model=ChatMessageResponse, status_code=201)
def gigachat_send(
    body: GigaChatSendBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    user_text = (body.text or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")

    uid = int(current_user.id)
    st = _dialog_state.get(uid) or {}
    url_in_text = _extract_first_url(user_text)

    # Conversation flow:
    # 1) User: "отредактируй статью" -> ask for link, set pending
    # 2) User sends link -> store link, ask for text fragment (or next instruction), keep pending_text
    # 3) Any text after link -> treat as text to edit (mode=edit with context_url)
    if _is_edit_article_intent(user_text):
        # If the user already included a link — extract article text and edit immediately.
        if url_in_text:
            article_text = _load_training_article_text(db, url_in_text) or ""
            if _is_article_text_enough(article_text):
                _dialog_state[uid] = {"article_url": url_in_text, "article_text": article_text}
                mode = "edit"
                context_url = url_in_text
                context_text = article_text
                instruction = re.sub(r"\s*" + re.escape(url_in_text) + r"\s*", " ", user_text).strip()
                if not instruction:
                    instruction = "Исправь ошибки, улучши стиль, сделай текст более понятным. Верни только итоговый текст."
                history = _load_thread_history(db, uid, limit=12)
                edited = _call_gigachat(
                    user_text=instruction,
                    mode=mode,
                    context_text=context_text,
                    context_url=context_url,
                    history=history,
                )
                answer = f"[apply-training-article:{context_url}]\n{edited}"
            else:
                _dialog_state[uid] = {"pending": "edit_article"}
                mode = "chat"
                answer = (
                    "Я открыл статью по ссылке, но в базе почти нет текста (похоже, тело статьи пустое или не сохранено). "
                    "Сохраните текст статьи на странице редактора и повторите команду, либо вставьте сюда текст статьи."
                )
                context_url = None
                context_text = None
        else:
            _dialog_state[uid] = {"pending": "edit_article"}
            mode = "chat"
            answer = "Ок. Пришлите ссылку на статью, которую нужно отредактировать."
            context_url = None
            context_text = None
    elif st.get("pending") == "edit_article" and _looks_like_url(user_text):
        # got the link
        article_text = _load_training_article_text(db, user_text) or ""
        if _is_article_text_enough(article_text):
            _dialog_state[uid] = {"article_url": user_text, "article_text": article_text}
            mode = "chat"
            answer = "Ссылка принята. Что именно сделать с этой статьёй? (например: «исправь ошибки», «сделай стиль деловым», «сократи на 30%»)"
            context_url = None
            context_text = None
        else:
            _dialog_state[uid] = {"pending": "edit_article"}
            mode = "chat"
            answer = (
                "Ссылку вижу, но в статье почти нет текста (похоже, тело статьи пустое или не сохранено). "
                "Сохраните статью на странице редактора и пришлите ссылку ещё раз, либо вставьте сюда текст статьи."
            )
            context_url = None
            context_text = None
    elif st.get("article_url") and not _looks_like_url(user_text):
        # We already have a target article in state — treat message as instruction for editing.
        context_url = str(st.get("article_url") or "").strip() or None
        context_text = str(st.get("article_text") or "").strip() or None
        if context_url and context_text and (("исправ" in user_text.lower()) or ("сделай" in user_text.lower()) or ("перепиш" in user_text.lower()) or ("улучш" in user_text.lower())):
            mode = "edit"
            history = _load_thread_history(db, uid, limit=14)
            edited = _call_gigachat(
                user_text=user_text,
                mode=mode,
                context_text=context_text,
                context_url=context_url,
                history=history,
            )
            answer = f"[apply-training-article:{context_url}]\n{edited}"
        else:
            mode = "chat"
            answer = _call_gigachat(
                user_text=user_text,
                mode=mode,
                context_text=None,
                context_url=None,
                history=_load_thread_history(db, uid, limit=16),
            )
            context_url = None
            context_text = None
    elif st.get("pending") == "edit_article_text" and not _looks_like_url(user_text):
        mode = "edit"
        context_url = str(st.get("article_url") or "").strip() or None
        context_text = user_text
        # clear pending state after we got text
        _dialog_state[uid] = {}
        edited = _call_gigachat(
            user_text=user_text,
            mode=mode,
            context_text=context_text,
            context_url=context_url,
            history=_load_thread_history(db, uid, limit=12),
        )
        if context_url:
            answer = f"[apply-training-article:{context_url}]\n{edited}"
        else:
            answer = edited
    else:
        mode = "chat"
        context_url = None
        context_text = None
        answer = _call_gigachat(
            user_text=user_text,
            mode=mode,
            context_text=context_text,
            context_url=context_url,
            history=_load_thread_history(db, uid, limit=16),
        )

    # 1) Save user message (returned to UI)
    user_msg = ChatMessage(
        private_dialog_id=None,
        group_dialog_id=None,
        bot_thread_user_id=None,
        gigachat_thread_user_id=uid,
        sender_user_id=uid,
        text=user_text,
        is_deleted=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user_msg)
    db.flush()

    # 2) Save assistant response
    assistant_msg = ChatMessage(
        private_dialog_id=None,
        group_dialog_id=None,
        bot_thread_user_id=None,
        gigachat_thread_user_id=uid,
        sender_user_id=None,  # system/assistant
        text=answer,
        is_deleted=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(assistant_msg)
    db.flush()
    db.commit()

    # Optional push: only to current user (web uses polling anyway)
    try:
        _send_chat_push_to_users(
            db,
            user_ids=[int(current_user.id)],
            title="GigaChat",
            body=answer[:140] if answer else "",
        )
    except Exception:
        pass

    # Return standard response for user message (UI replaces temp)
    return _messages_to_responses(db, [user_msg], current_user)[0]


@router.post("/mark-read")
def gigachat_mark_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    uid = int(current_user.id)
    # Mark all assistant messages as read (and own, harmless)
    subq = (
        db.query(ChatMessage.id)
        .filter(ChatMessage.gigachat_thread_user_id == uid)
        .subquery()
    )
    # Insert reads for messages without row for this user
    unread_filter = ~db.query(ChatMessageRead.id).filter(
        ChatMessageRead.user_id == uid,
        ChatMessageRead.message_id == ChatMessage.id,
    ).exists()
    ids = [int(r[0]) for r in db.query(ChatMessage.id).filter(ChatMessage.id.in_(subq), unread_filter).all()]
    if not ids:
        return {"ok": True}
    for mid in ids:
        db.add(ChatMessageRead(message_id=mid, user_id=uid))
    db.commit()
    return {"ok": True}

