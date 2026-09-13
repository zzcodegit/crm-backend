from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from database import get_db
from deps import get_admin_user, get_current_user, is_admin, is_manager
from models import TrainingArticle, TrainingArticleView, User
from schemas import (
    TrainingArticleAnalyticsItem,
    TrainingArticleCreate,
    TrainingArticleListItem,
    TrainingArticleResponse,
    TrainingArticleUpdate,
    TrainingArticleViewReportItem,
)
from routers.training_courses_routes import register_training_course_routes

router = APIRouter(prefix="/api/training", tags=["training"])
register_training_course_routes(router)


def _display_name(user: User) -> str:
    parts = [user.last_name, user.first_name, user.patronymic]
    full = " ".join([p.strip() for p in parts if p and p.strip()]).strip()
    return full or user.username


def _can_training_analytics(user: User) -> bool:
    return is_admin(user) or is_manager(user)


def _require_training_analytics(user: User) -> None:
    if not _can_training_analytics(user):
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра аналитики")


def _to_response(article: TrainingArticle) -> TrainingArticleResponse:
    return TrainingArticleResponse(
        id=article.id,
        title=article.title,
        section=article.section or "Общее",
        preview_image_url=article.preview_image_url,
        content_html=article.content_html or "",
        is_published=bool(article.is_published),
        created_by_user_id=article.created_by_user_id,
        created_by_username=(article.created_by.username if article.created_by else None),
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


def _to_list_item(article: TrainingArticle) -> TrainingArticleListItem:
    return TrainingArticleListItem(
        id=article.id,
        title=article.title,
        section=article.section or "Общее",
        preview_image_url=article.preview_image_url,
        is_published=bool(article.is_published),
        created_by_user_id=article.created_by_user_id,
        created_by_username=(article.created_by.username if article.created_by else None),
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


def _get_article_or_404(db: Session, item_id: int) -> TrainingArticle:
    item = db.query(TrainingArticle).filter(TrainingArticle.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return item


@router.get("/articles", response_model=list[TrainingArticleListItem])
def list_articles(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = (
        db.query(TrainingArticle)
        .options(joinedload(TrainingArticle.created_by))
    )
    # Права определяем через группы пользователя (единый источник истины для ролей).
    can_view_unpublished = is_admin(current_user) or is_manager(current_user)
    if not can_view_unpublished:
        query = query.filter(TrainingArticle.is_published == True)
    items = query.order_by(TrainingArticle.updated_at.desc(), TrainingArticle.id.desc()).all()
    return [_to_list_item(x) for x in items]


@router.get("/articles/analytics", response_model=list[TrainingArticleAnalyticsItem])
def articles_analytics(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_training_analytics(current_user)
    articles = db.query(TrainingArticle).order_by(TrainingArticle.updated_at.desc(), TrainingArticle.id.desc()).all()
    stats_rows = (
        db.query(
            TrainingArticleView.article_id,
            func.count(TrainingArticleView.user_id).label("unique_viewers"),
            func.coalesce(func.sum(TrainingArticleView.view_count), 0).label("total_views"),
            func.max(TrainingArticleView.last_viewed_at).label("last_viewed_at"),
        )
        .group_by(TrainingArticleView.article_id)
        .all()
    )
    stats_map = {int(r.article_id): r for r in stats_rows}
    return [
        TrainingArticleAnalyticsItem(
            article_id=a.id,
            title=a.title,
            section=a.section or "Общее",
            is_published=bool(a.is_published),
            unique_viewers=int(stats_map[a.id].unique_viewers) if a.id in stats_map else 0,
            total_views=int(stats_map[a.id].total_views) if a.id in stats_map else 0,
            last_viewed_at=(stats_map[a.id].last_viewed_at if a.id in stats_map else None),
        )
        for a in articles
    ]


@router.get("/articles/{item_id}", response_model=TrainingArticleResponse)
def get_article(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = (
        db.query(TrainingArticle)
        .options(joinedload(TrainingArticle.created_by))
        .filter(TrainingArticle.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    if not item.is_published and not (is_admin(current_user) or is_manager(current_user)):
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return _to_response(item)


@router.post("/articles/{item_id}/view", status_code=204)
def record_article_view(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = _get_article_or_404(db, item_id)
    if not item.is_published and not (is_admin(current_user) or is_manager(current_user)):
        raise HTTPException(status_code=404, detail="Статья не найдена")

    now = datetime.now(timezone.utc)
    rec = (
        db.query(TrainingArticleView)
        .filter(
            TrainingArticleView.article_id == item_id,
            TrainingArticleView.user_id == current_user.id,
        )
        .first()
    )
    if rec:
        rec.view_count = int(rec.view_count or 0) + 1
        rec.last_viewed_at = now
    else:
        db.add(
            TrainingArticleView(
                article_id=item_id,
                user_id=current_user.id,
                view_count=1,
                first_viewed_at=now,
                last_viewed_at=now,
            )
        )
    db.commit()
    return None


@router.get("/articles/{item_id}/report", response_model=list[TrainingArticleViewReportItem])
def article_views_report(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_training_analytics(current_user)
    _get_article_or_404(db, item_id)

    users = db.query(User).filter(User.is_active == True).order_by(User.username.asc()).all()
    views = db.query(TrainingArticleView).filter(TrainingArticleView.article_id == item_id).all()
    view_map = {int(v.user_id): v for v in views}

    return [
        TrainingArticleViewReportItem(
            user_id=u.id,
            username=u.username,
            display_name=_display_name(u),
            visited=(int(u.id) in view_map),
            first_viewed_at=(view_map[int(u.id)].first_viewed_at if int(u.id) in view_map else None),
            last_viewed_at=(view_map[int(u.id)].last_viewed_at if int(u.id) in view_map else None),
            view_count=int(view_map[int(u.id)].view_count) if int(u.id) in view_map else 0,
        )
        for u in users
    ]


@router.post("/articles", response_model=TrainingArticleResponse, status_code=201)
def create_article(data: TrainingArticleCreate, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Заголовок обязателен")
    section = (data.section or "Общее").strip() or "Общее"

    obj = TrainingArticle(
        title=title,
        section=section,
        preview_image_url=(data.preview_image_url or "").strip() or None,
        content_html=data.content_html or "",
        is_published=bool(data.is_published),
        created_by_user_id=current_user.id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    obj = (
        db.query(TrainingArticle)
        .options(joinedload(TrainingArticle.created_by))
        .filter(TrainingArticle.id == obj.id)
        .first()
    )
    return _to_response(obj)


@router.patch("/articles/{item_id}", response_model=TrainingArticleResponse)
def update_article(
    item_id: int,
    data: TrainingArticleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    item = db.query(TrainingArticle).filter(TrainingArticle.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Статья не найдена")

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
    if "content_html" in payload:
        item.content_html = payload["content_html"] or ""
    if "is_published" in payload:
        item.is_published = bool(payload["is_published"])

    db.commit()
    db.refresh(item)
    item = (
        db.query(TrainingArticle)
        .options(joinedload(TrainingArticle.created_by))
        .filter(TrainingArticle.id == item_id)
        .first()
    )
    return _to_response(item)


@router.delete("/articles/{item_id}", status_code=204)
def delete_article(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    item = db.query(TrainingArticle).filter(TrainingArticle.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    db.delete(item)
    db.commit()
    return None
