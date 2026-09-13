from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from database import get_db
from deps import get_admin_user, get_current_user, is_admin
from models import NormativeAct, NormativeActSignature, User
from schemas import (
    NormativeActCreate,
    NormativeActResponse,
    NormativeActSignReportItem,
    NormativeActSignResponse,
    NormativeActUpdate,
)

router = APIRouter(prefix="/api/normative-acts", tags=["normative-acts"])


def _display_name(user: User) -> str:
    parts = [user.last_name, user.first_name, user.patronymic]
    full = " ".join([p.strip() for p in parts if p and p.strip()]).strip()
    return full or user.username


def _to_response(article: NormativeAct, signed: NormativeActSignature | None = None) -> NormativeActResponse:
    return NormativeActResponse(
        id=article.id,
        title=article.title,
        section=article.section or "Общее",
        preview_image_url=article.preview_image_url,
        attachment_url=article.attachment_url,
        attachment_filename=article.attachment_filename,
        visible_user_ids=[int(x) for x in (article.visible_user_ids or []) if str(x).isdigit()],
        content_html=article.content_html or "",
        is_published=bool(article.is_published),
        created_by_user_id=article.created_by_user_id,
        created_by_username=(article.created_by.username if article.created_by else None),
        created_at=article.created_at,
        updated_at=article.updated_at,
        signed_by_me=bool(signed),
        signed_at=(signed.signed_at if signed else None),
    )


def _normalized_visible_user_ids(raw) -> list[int]:
    if raw is None:
        return []
    out: list[int] = []
    for x in raw:
        try:
            v = int(x)
            if v > 0 and v not in out:
                out.append(v)
        except Exception:
            continue
    return out


def _visible_user_ids_for_storage(raw, author_user_id: int | None) -> list[int] | None:
    """Пустой список/null — документ для всех; иначе только выбранные + автор."""
    visible = _normalized_visible_user_ids(raw)
    if not visible:
        return None
    if author_user_id is not None and author_user_id not in visible:
        visible.append(author_user_id)
    return visible


def _can_view(article: NormativeAct, user: User, *, for_admin_ui: bool = False) -> bool:
    """
    Пустой visible_user_ids — документ виден всем.
    Иначе — только автор, пользователи из списка и (в админ-интерфейсе) администраторы CRM.
    """
    if for_admin_ui and is_admin(user):
        return True
    visible = _normalized_visible_user_ids(article.visible_user_ids or [])
    if not visible:
        return True
    author_id = article.created_by_user_id
    if author_id is not None and user.id == author_id:
        return True
    return user.id in visible


@router.get("/articles", response_model=list[NormativeActResponse])
def list_articles(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    admin_ui = is_admin(current_user)
    items = (
        db.query(NormativeAct)
        .options(joinedload(NormativeAct.created_by))
        .filter(NormativeAct.is_published == True)
        .order_by(NormativeAct.updated_at.desc(), NormativeAct.id.desc())
        .all()
    )
    items = [x for x in items if _can_view(x, current_user, for_admin_ui=admin_ui)]
    signatures = (
        db.query(NormativeActSignature)
        .filter(NormativeActSignature.user_id == current_user.id)
        .all()
    )
    sign_map = {s.act_id: s for s in signatures}
    return [_to_response(x, sign_map.get(x.id)) for x in items]


@router.get("/articles/{item_id}", response_model=NormativeActResponse)
def get_article(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = (
        db.query(NormativeAct)
        .options(joinedload(NormativeAct.created_by))
        .filter(NormativeAct.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if not _can_view(item, current_user, for_admin_ui=is_admin(current_user)):
        raise HTTPException(status_code=403, detail="Нет доступа к документу")
    sign = (
        db.query(NormativeActSignature)
        .filter(NormativeActSignature.act_id == item_id, NormativeActSignature.user_id == current_user.id)
        .first()
    )
    return _to_response(item, sign)


@router.post("/articles", response_model=NormativeActResponse, status_code=201)
def create_article(data: NormativeActCreate, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Заголовок обязателен")
    section = (data.section or "Общее").strip() or "Общее"
    obj = NormativeAct(
        title=title,
        section=section,
        preview_image_url=(data.preview_image_url or "").strip() or None,
        attachment_url=(data.attachment_url or "").strip() or None,
        attachment_filename=(data.attachment_filename or "").strip() or None,
        visible_user_ids=_visible_user_ids_for_storage(data.visible_user_ids, current_user.id),
        content_html=data.content_html or "",
        is_published=bool(data.is_published),
        created_by_user_id=current_user.id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    obj = db.query(NormativeAct).options(joinedload(NormativeAct.created_by)).filter(NormativeAct.id == obj.id).first()
    return _to_response(obj)


@router.patch("/articles/{item_id}", response_model=NormativeActResponse)
def update_article(
    item_id: int,
    data: NormativeActUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    item = db.query(NormativeAct).filter(NormativeAct.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Документ не найден")
    payload = data.model_dump(exclude_unset=True)
    if "title" in payload:
        title = (payload["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Заголовок обязателен")
        item.title = title
    if "section" in payload:
        item.section = (payload["section"] or "Общее").strip() or "Общее"
    if "preview_image_url" in payload:
        item.preview_image_url = (payload["preview_image_url"] or "").strip() or None
    if "attachment_url" in payload:
        item.attachment_url = (payload["attachment_url"] or "").strip() or None
    if "attachment_filename" in payload:
        item.attachment_filename = (payload["attachment_filename"] or "").strip() or None
    if "visible_user_ids" in payload:
        item.visible_user_ids = _visible_user_ids_for_storage(
            payload["visible_user_ids"],
            item.created_by_user_id,
        )
    if "content_html" in payload:
        item.content_html = payload["content_html"] or ""
    if "is_published" in payload:
        item.is_published = bool(payload["is_published"])
    db.commit()
    db.refresh(item)
    item = db.query(NormativeAct).options(joinedload(NormativeAct.created_by)).filter(NormativeAct.id == item_id).first()
    return _to_response(item)


@router.delete("/articles/{item_id}", status_code=204)
def delete_article(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    item = db.query(NormativeAct).filter(NormativeAct.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Документ не найден")
    db.delete(item)
    db.commit()
    return None


@router.post("/articles/{item_id}/sign", response_model=NormativeActSignResponse)
def sign_article(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(NormativeAct).filter(NormativeAct.id == item_id, NormativeAct.is_published == True).first()
    if not item:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if not _can_view(item, current_user, for_admin_ui=False):
        raise HTTPException(status_code=403, detail="Нет доступа к документу")
    existing = (
        db.query(NormativeActSignature)
        .filter(NormativeActSignature.act_id == item_id, NormativeActSignature.user_id == current_user.id)
        .first()
    )
    if existing:
        return NormativeActSignResponse(ok=True, signed_at=existing.signed_at)
    sign = NormativeActSignature(act_id=item_id, user_id=current_user.id)
    db.add(sign)
    db.commit()
    db.refresh(sign)
    return NormativeActSignResponse(ok=True, signed_at=sign.signed_at)


@router.get("/articles/{item_id}/report", response_model=list[NormativeActSignReportItem])
def sign_report(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    item = db.query(NormativeAct).filter(NormativeAct.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Документ не найден")
    visible_user_ids = _normalized_visible_user_ids(item.visible_user_ids or [])
    if not visible_user_ids:
        report_user_ids: list[int] | None = None
    else:
        report_user_ids = list(visible_user_ids)
    users_query = db.query(User).filter(User.is_active == True)
    if report_user_ids is not None:
        users_query = users_query.filter(User.id.in_(report_user_ids))
    users = users_query.order_by(User.username.asc()).all()
    signatures = db.query(NormativeActSignature).filter(NormativeActSignature.act_id == item_id).all()
    sign_map = {s.user_id: s for s in signatures}
    return [
        NormativeActSignReportItem(
            user_id=u.id,
            username=u.username,
            display_name=_display_name(u),
            signed=(u.id in sign_map),
            signed_at=(sign_map[u.id].signed_at if u.id in sign_map else None),
        )
        for u in users
    ]
