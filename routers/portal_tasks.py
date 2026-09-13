from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from database import get_db
from deps import get_current_user, is_admin
from models import PortalTask, User
from schemas import PortalTaskResponse, PortalTaskCreate, PortalTaskUpdate, TaskAssigneeOption

router = APIRouter(tags=["portal-tasks"])

ALLOWED_STATUS = {"new", "in_progress", "done"}
ALLOWED_PRIORITY = {"low", "medium", "high"}


def _user_label(u: User | None) -> str | None:
    if not u:
        return None
    parts = [u.last_name, u.first_name, u.patronymic]
    name = " ".join(p for p in parts if p).strip()
    return name or u.username


def _to_response(task: PortalTask) -> PortalTaskResponse:
    created_username = task.created_by.username if task.created_by else None
    return PortalTaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        created_by_user_id=task.created_by_user_id,
        created_by_username=created_username,
        assignee_user_id=task.assignee_user_id,
        assignee_label=_user_label(task.assignee),
        due_at=task.due_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _task_query(db: Session):
    return (
        db.query(PortalTask)
        .options(joinedload(PortalTask.created_by), joinedload(PortalTask.assignee))
        .order_by(PortalTask.created_at.desc(), PortalTask.id.desc())
    )


def _can_delete(task: PortalTask, user: User) -> bool:
    if is_admin(user):
        return True
    if task.created_by_user_id == user.id:
        return True
    if task.assignee_user_id == user.id:
        return True
    return False


@router.get("/api/portal-tasks/assignees", response_model=list[TaskAssigneeOption])
def list_task_assignees(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    users = db.query(User).filter(User.is_active.is_(True)).order_by(User.last_name, User.first_name, User.username).all()
    return [TaskAssigneeOption(id=u.id, username=u.username, label=_user_label(u) or u.username) for u in users]


@router.get("/api/portal-tasks", response_model=list[PortalTaskResponse])
def list_portal_tasks(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    tasks = _task_query(db).all()
    return [_to_response(t) for t in tasks]


@router.post("/api/portal-tasks", response_model=PortalTaskResponse, status_code=201)
def create_portal_task(data: PortalTaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    status = data.status.strip().lower()
    priority = data.priority.strip().lower()
    if status not in ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail="Неверный статус")
    if priority not in ALLOWED_PRIORITY:
        raise HTTPException(status_code=400, detail="Неверный приоритет")
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Заголовок обязателен")
    assignee_id = data.assignee_user_id
    if assignee_id is not None:
        u = db.query(User).filter(User.id == assignee_id, User.is_active.is_(True)).first()
        if not u:
            raise HTTPException(status_code=400, detail="Ответственный не найден")
    task = PortalTask(
        title=title,
        description=(data.description or "").strip() or None,
        status=status,
        priority=priority,
        created_by_user_id=current_user.id,
        assignee_user_id=assignee_id,
        due_at=data.due_at,
    )
    db.add(task)
    db.commit()
    task = _task_query(db).filter(PortalTask.id == task.id).first()
    assert task
    return _to_response(task)


@router.patch("/api/portal-tasks/{task_id}", response_model=PortalTaskResponse)
def update_portal_task(
    task_id: int, data: PortalTaskUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    task = _task_query(db).filter(PortalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    payload = data.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] is not None:
        payload["status"] = str(payload["status"]).strip().lower()
        if payload["status"] not in ALLOWED_STATUS:
            raise HTTPException(status_code=400, detail="Неверный статус")
    if "priority" in payload and payload["priority"] is not None:
        payload["priority"] = str(payload["priority"]).strip().lower()
        if payload["priority"] not in ALLOWED_PRIORITY:
            raise HTTPException(status_code=400, detail="Неверный приоритет")
    if "title" in payload and payload["title"] is not None:
        payload["title"] = str(payload["title"]).strip()
        if not payload["title"]:
            raise HTTPException(status_code=400, detail="Заголовок обязателен")
    if "description" in payload and payload["description"] is not None:
        payload["description"] = str(payload["description"]).strip() or None
    if "assignee_user_id" in payload:
        aid = payload["assignee_user_id"]
        if aid is not None:
            u = db.query(User).filter(User.id == aid, User.is_active.is_(True)).first()
            if not u:
                raise HTTPException(status_code=400, detail="Ответственный не найден")
    for key, value in payload.items():
        setattr(task, key, value)
    db.commit()
    task = _task_query(db).filter(PortalTask.id == task_id).first()
    assert task
    return _to_response(task)


@router.delete("/api/portal-tasks/{task_id}", status_code=204)
def delete_portal_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(PortalTask).filter(PortalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if not _can_delete(task, current_user):
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления")
    db.delete(task)
    db.commit()
    return None
