"""
Черновики и опубликованный график работы (недели → правки ячеек).
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from deps import CONSULTANTS_GROUP_NAME, get_current_user, get_schedule_manager_user, is_consultant
from models import Group, User, WorkScheduleConfirmation, WorkScheduleDraft, WorkSchedulePublished
from schemas import (
    WorkScheduleConfirmBody,
    WorkScheduleConfirmationReportResponse,
    WorkScheduleConfirmationReportRow,
    WorkScheduleDraftCreate,
    WorkScheduleDraftResponse,
    WorkScheduleDraftUpdate,
    WorkScheduleMyConfirmationResponse,
    WorkScheduleWeeksPayload,
)

router = APIRouter(prefix="/api/work-schedule", tags=["work-schedule"])

PUBLISHED_ID = 1
_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_week_start(raw: str) -> str:
    s = (raw or "").strip()
    if not _YMD_RE.match(s):
        raise HTTPException(
            status_code=400,
            detail="week_start: укажите дату понедельника недели в формате YYYY-MM-DD",
        )
    return s


def _user_display_name(u: User) -> str:
    last = (u.last_name or "").strip()
    first = (u.first_name or "").strip()
    if last or first:
        initial = f" {first[0]}." if first else ""
        return f"{last}{initial}".strip()
    return (u.username or "").strip()


def _norm_schedule_text(s: str) -> str:
    t = " ".join((s or "").lower().replace("ё", "е").split())
    return t


def _user_schedule_match_variants(u: User) -> list[str]:
    """Варианты строк, как консультант может быть указан в ячейке графика."""
    first = (u.first_name or "").strip()
    last = (u.last_name or "").strip()
    user = (u.username or "").strip()
    raw: list[str] = []
    if first and last:
        raw.append(f"{first} {last}")
        raw.append(f"{last} {first}")
    if last:
        raw.append(last)
        if first:
            raw.append(f"{last} {first[0]}.")
    if user:
        raw.append(user)
    seen: set[str] = set()
    out: list[str] = []
    for x in raw:
        n = _norm_schedule_text(x)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


_SKIP_CELL_VALUES = frozenset(
    {
        "",
        "—",
        "-",
        "–",
        "выходной",
        "отпуск",
        "больничный",
    }
)


def _schedule_cell_refers_to_user(cell_raw: str, u: User) -> bool:
    """Совпадение с логикой главной (ФИО / фамилия в тексте ячейки)."""
    cell = _norm_schedule_text(cell_raw)
    if not cell or cell in _SKIP_CELL_VALUES:
        return False
    variants = _user_schedule_match_variants(u)
    if not variants:
        return False
    for v in variants:
        if cell == v or v in cell or cell in v:
            return True
    last = (u.last_name or "").strip()
    if last:
        ln = _norm_schedule_text(last)
        if len(ln) >= 2 and ln in cell:
            return True
    return False


def _consultant_colors_map(db: Session) -> dict[str, str]:
    """Ключ — как в ячейках графика (имя и фамилия из карточки пользователя)."""
    out: dict[str, str] = {}
    for u in db.query(User).filter(User.is_active == True).all():
        c = (u.schedule_color or "").strip()
        if not c:
            continue
        first = (u.first_name or "").strip()
        last = (u.last_name or "").strip()
        key = f"{first} {last}".strip() if (first or last) else (u.username or "").strip()
        if key:
            out[key] = c
    return out


def _published_week_cells_for_week_start(db: Session, week_start: str) -> list[str]:
    """Все значения ячеек опубликованной недели (point|day → консультант/—)."""
    row = db.query(WorkSchedulePublished).filter(WorkSchedulePublished.id == PUBLISHED_ID).first()
    if not row or not row.payload or not isinstance(row.payload, dict):
        return []
    weeks = row.payload.get("weeks")
    if not isinstance(weeks, dict):
        return []
    wm = weeks.get(week_start)
    if not isinstance(wm, dict):
        return []
    return [str(v) for v in wm.values()]


def _consultants_in_published_week(consultants: list[User], week_cells: list[str]) -> list[User]:
    """Только консультанты, чья фамилия/ФИО встречается хотя бы в одной ячейке недели."""
    if not week_cells:
        return []
    out: list[User] = []
    for u in consultants:
        for val in week_cells:
            if _schedule_cell_refers_to_user(val, u):
                out.append(u)
                break
    return out


def _draft_to_response(d: WorkScheduleDraft) -> WorkScheduleDraftResponse:
    return WorkScheduleDraftResponse(
        id=d.id,
        name=d.name,
        payload=d.payload if isinstance(d.payload, dict) else {},
        created_at=d.created_at,
        updated_at=getattr(d, "updated_at", None) or d.created_at,
    )


@router.post("/confirmation", response_model=WorkScheduleMyConfirmationResponse)
def confirm_schedule(
    data: WorkScheduleConfirmBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Консультант подтверждает ознакомление с графиком на указанную неделю."""
    if not is_consultant(current_user):
        raise HTTPException(status_code=403, detail="Подтверждение доступно только группе «Консультанты»")
    week_start = _normalize_week_start(data.week_start)
    now = datetime.now(timezone.utc)
    row = (
        db.query(WorkScheduleConfirmation)
        .filter(
            WorkScheduleConfirmation.user_id == current_user.id,
            WorkScheduleConfirmation.week_start == week_start,
        )
        .first()
    )
    if row:
        row.confirmed_at = now
    else:
        row = WorkScheduleConfirmation(user_id=current_user.id, week_start=week_start, confirmed_at=now)
        db.add(row)
    db.commit()
    db.refresh(row)
    return WorkScheduleMyConfirmationResponse(
        week_start=week_start,
        confirmed=True,
        confirmed_at=row.confirmed_at,
    )


@router.get("/confirmation/me", response_model=WorkScheduleMyConfirmationResponse)
def get_my_confirmation(
    week_start: str = Query(..., description="Понедельник недели YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_consultant(current_user):
        raise HTTPException(status_code=403, detail="Доступно только группе «Консультанты»")
    ws = _normalize_week_start(week_start)
    row = (
        db.query(WorkScheduleConfirmation)
        .filter(
            WorkScheduleConfirmation.user_id == current_user.id,
            WorkScheduleConfirmation.week_start == ws,
        )
        .first()
    )
    return WorkScheduleMyConfirmationResponse(
        week_start=ws,
        confirmed=row is not None,
        confirmed_at=row.confirmed_at if row else None,
    )


@router.get("/confirmations/report", response_model=WorkScheduleConfirmationReportResponse)
def confirmations_report(
    week_start: str = Query(..., description="Понедельник недели YYYY-MM-DD"),
    db: Session = Depends(get_db),
    _: User = Depends(get_schedule_manager_user),
):
    """Сводка по консультантам: кто подтвердил график на неделю."""
    ws = _normalize_week_start(week_start)
    group = db.query(Group).filter(Group.name == CONSULTANTS_GROUP_NAME).first()
    if not group:
        return WorkScheduleConfirmationReportResponse(
            week_start=ws,
            total_consultants=0,
            confirmed_count=0,
            rows=[],
        )

    consultants = (
        db.query(User)
        .join(User.groups)
        .filter(Group.id == group.id)
        .filter(User.is_active.is_(True))
        .order_by(User.last_name, User.first_name, User.username)
        .all()
    )

    week_cells = _published_week_cells_for_week_start(db, ws)
    consultants = _consultants_in_published_week(consultants, week_cells)

    conf_map = {
        c.user_id: c
        for c in db.query(WorkScheduleConfirmation).filter(WorkScheduleConfirmation.week_start == ws).all()
    }

    rows: list[WorkScheduleConfirmationReportRow] = []
    for u in consultants:
        c = conf_map.get(u.id)
        rows.append(
            WorkScheduleConfirmationReportRow(
                user_id=u.id,
                username=u.username,
                display_name=_user_display_name(u),
                confirmed_at=c.confirmed_at if c else None,
            )
        )
    confirmed_count = sum(1 for r in rows if r.confirmed_at is not None)
    return WorkScheduleConfirmationReportResponse(
        week_start=ws,
        total_consultants=len(rows),
        confirmed_count=confirmed_count,
        rows=rows,
    )


@router.get("/published", response_model=WorkScheduleWeeksPayload)
def get_published_schedule(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    colors = _consultant_colors_map(db)
    row = db.query(WorkSchedulePublished).filter(WorkSchedulePublished.id == PUBLISHED_ID).first()
    if not row or not row.payload:
        return WorkScheduleWeeksPayload(weeks={}, consultant_colors=colors)
    p = row.payload
    if isinstance(p, dict) and "weeks" in p:
        return WorkScheduleWeeksPayload(weeks=p.get("weeks") or {}, consultant_colors=colors)
    return WorkScheduleWeeksPayload(weeks={}, consultant_colors=colors)


def _published_weeks_from_row(row: WorkSchedulePublished | None) -> dict[str, dict[str, str]]:
    if not row or not row.payload or not isinstance(row.payload, dict):
        return {}
    p = row.payload.get("weeks")
    if not isinstance(p, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for k, v in p.items():
        if isinstance(v, dict):
            out[str(k)] = {str(a): str(b) for a, b in v.items()}
        else:
            out[str(k)] = {}
    return out


@router.post("/publish", response_model=WorkScheduleWeeksPayload)
def publish_schedule(
    data: WorkScheduleWeeksPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_schedule_manager_user),
):
    """Обновляет только переданные недели; остальные опубликованные недели сохраняются."""
    body = data.model_dump(mode="json")
    incoming_weeks = body.get("weeks") or {}
    if not isinstance(incoming_weeks, dict):
        incoming_weeks = {}

    row = db.query(WorkSchedulePublished).filter(WorkSchedulePublished.id == PUBLISHED_ID).first()
    now = datetime.now(timezone.utc)
    existing = _published_weeks_from_row(row)

    merged = {**existing}
    for k, v in incoming_weeks.items():
        ks = str(k)
        if isinstance(v, dict):
            merged[ks] = {str(a): str(b) for a, b in v.items()}
        else:
            merged[ks] = {}

    new_payload = {"weeks": merged}
    if not row:
        row = WorkSchedulePublished(
            id=PUBLISHED_ID,
            payload=new_payload,
            published_at=now,
            published_by_id=current_user.id,
        )
        db.add(row)
    else:
        row.payload = new_payload
        row.published_at = now
        row.published_by_id = current_user.id
    db.commit()
    return WorkScheduleWeeksPayload(weeks=merged, consultant_colors=_consultant_colors_map(db))


@router.delete("/published/week/{week_start}", status_code=204)
def delete_published_week(
    week_start: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_schedule_manager_user),
):
    """Убрать неделю из опубликованного графика (с главной исчезнет)."""
    ws = _normalize_week_start(week_start)
    row = db.query(WorkSchedulePublished).filter(WorkSchedulePublished.id == PUBLISHED_ID).first()
    if not row or not row.payload or not isinstance(row.payload, dict):
        raise HTTPException(status_code=404, detail="Нет опубликованного графика")
    weeks = row.payload.get("weeks")
    if not isinstance(weeks, dict) or ws not in weeks:
        raise HTTPException(status_code=404, detail="Эта неделя не опубликована")

    new_weeks = {k: v for k, v in weeks.items() if k != ws}
    row.payload = {**row.payload, "weeks": new_weeks}
    row.published_at = datetime.now(timezone.utc)
    row.published_by_id = current_user.id
    db.query(WorkScheduleConfirmation).filter(WorkScheduleConfirmation.week_start == ws).delete()
    db.commit()
    return None


@router.get("/drafts", response_model=list[WorkScheduleDraftResponse])
def list_drafts(
    db: Session = Depends(get_db),
    _: User = Depends(get_schedule_manager_user),
):
    items = db.query(WorkScheduleDraft).order_by(WorkScheduleDraft.id.desc()).all()
    return [_draft_to_response(d) for d in items]


@router.get("/drafts/{draft_id}", response_model=WorkScheduleDraftResponse)
def get_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_schedule_manager_user),
):
    d = db.query(WorkScheduleDraft).filter(WorkScheduleDraft.id == draft_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    return _draft_to_response(d)


@router.post("/drafts", response_model=WorkScheduleDraftResponse, status_code=201)
def create_draft(
    data: WorkScheduleDraftCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_schedule_manager_user),
):
    name = (data.name or "").strip() or "Черновик"
    d = WorkScheduleDraft(
        name=name,
        payload=data.payload.model_dump(mode="json"),
        user_id=current_user.id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return _draft_to_response(d)


@router.patch("/drafts/{draft_id}", response_model=WorkScheduleDraftResponse)
def update_draft(
    draft_id: int,
    data: WorkScheduleDraftUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_schedule_manager_user),
):
    d = db.query(WorkScheduleDraft).filter(WorkScheduleDraft.id == draft_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    if data.name is not None:
        d.name = (data.name.strip() or d.name)[:256]
    if data.payload is not None:
        d.payload = data.payload.model_dump(mode="json")
    d.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(d)
    return _draft_to_response(d)


@router.delete("/drafts/{draft_id}", status_code=204)
def delete_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_schedule_manager_user),
):
    d = db.query(WorkScheduleDraft).filter(WorkScheduleDraft.id == draft_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    db.delete(d)
    db.commit()
    return None
