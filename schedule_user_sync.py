"""Переименование сотрудника в опубликованном графике и черновиках."""
from __future__ import annotations

from sqlalchemy.orm import Session

from models import User, WorkScheduleDraft, WorkSchedulePublished
from routers.work_schedule import (
    PUBLISHED_ID,
    _schedule_cell_refers_to_user,
    _SKIP_CELL_VALUES,
)


def schedule_label_for_user(u: User) -> str:
    """Как в интерфейсе графика: «имя фамилия» или логин."""
    first = (u.first_name or "").strip()
    last = (u.last_name or "").strip()
    s = f"{first} {last}".strip()
    return s or (u.username or "").strip()


def _user_snapshot(username: str | None, first_name: str | None, last_name: str | None) -> User:
    u = User()
    u.username = username or ""
    u.first_name = first_name
    u.last_name = last_name
    return u


def _rewrite_cell_value(cell: str, old_u: User, new_label: str) -> tuple[str, bool]:
    if not cell or cell.strip() in _SKIP_CELL_VALUES:
        return cell, False
    lines = cell.split("\n")
    changed = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and stripped not in _SKIP_CELL_VALUES and _schedule_cell_refers_to_user(stripped, old_u):
            new_lines.append(new_label)
            changed = True
        else:
            new_lines.append(line)
    if not changed:
        return cell, False
    return "\n".join(new_lines), True


def _rename_in_weeks(weeks: dict, old_u: User, new_label: str) -> int:
    if not isinstance(weeks, dict) or not new_label:
        return 0
    updates = 0
    for _week, cells in weeks.items():
        if not isinstance(cells, dict):
            continue
        for key, raw in list(cells.items()):
            if not isinstance(raw, str):
                continue
            new_val, ok = _rewrite_cell_value(raw, old_u, new_label)
            if ok:
                cells[key] = new_val
                updates += 1
    return updates


def rename_user_in_schedules(
    db: Session,
    *,
    old_username: str | None,
    old_first_name: str | None,
    old_last_name: str | None,
    user: User,
) -> int:
    """Обновляет ФИО/логин в ячейках графика, где фигурировал сотрудник."""
    new_label = schedule_label_for_user(user)
    old_u = _user_snapshot(old_username, old_first_name, old_last_name)
    old_label = schedule_label_for_user(old_u)
    if not new_label or new_label == old_label:
        return 0

    total = 0

    row = db.query(WorkSchedulePublished).filter(WorkSchedulePublished.id == PUBLISHED_ID).first()
    if row and row.payload and isinstance(row.payload, dict):
        weeks = row.payload.get("weeks")
        if isinstance(weeks, dict):
            total += _rename_in_weeks(weeks, old_u, new_label)
            row.payload = {**row.payload, "weeks": weeks}

    for draft in db.query(WorkScheduleDraft).all():
        payload = draft.payload
        if not payload or not isinstance(payload, dict):
            continue
        weeks = payload.get("weeks")
        if not isinstance(weeks, dict):
            continue
        n = _rename_in_weeks(weeks, old_u, new_label)
        if n:
            draft.payload = {**payload, "weeks": weeks}
            total += n

    return total
