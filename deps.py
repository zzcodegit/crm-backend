from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from typing import Annotated

from database import get_db
from models import User
from auth import decode_token

security = HTTPBearer(auto_error=False)

ADMIN_GROUP_NAME = "Администратор"
MANAGER_GROUP_NAME = "Менеджер"
CONSULTANTS_GROUP_NAME = "Консультанты"
REPORTNIKI_GROUP_NAME = "Отчетники"
PRICE_GROUP_NAMES = {"прайс", "price"}


def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Session = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload or "sub" not in payload:
        return None
    user = (
        db.query(User)
        .options(joinedload(User.groups))
        .filter(User.username == payload["sub"])
        .first()
    )
    if not user or not user.is_active:
        return None
    return user


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    payload = decode_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Неверный токен")
    user = (
        db.query(User)
        .options(joinedload(User.groups))
        .filter(User.username == payload["sub"])
        .first()
    )
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


def is_admin(user: User) -> bool:
    return any(g.name == ADMIN_GROUP_NAME for g in user.groups)


def is_manager(user: User) -> bool:
    return any(g.name == MANAGER_GROUP_NAME for g in user.groups)


def is_consultant(user: User) -> bool:
    return any(g.name == CONSULTANTS_GROUP_NAME for g in user.groups)


def is_reportnik(user: User) -> bool:
    return any(g.name == REPORTNIKI_GROUP_NAME for g in user.groups)


def is_price_user(user: User) -> bool:
    return any((g.name or "").strip().lower() in PRICE_GROUP_NAMES for g in user.groups)


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Доступ только для администратора")
    return current_user


def get_admin_or_reportnik_user(current_user: User = Depends(get_current_user)) -> User:
    """Доступ к админскому просмотру отчётов (без права изменения)."""
    if not is_admin(current_user) and not is_reportnik(current_user):
        raise HTTPException(status_code=403, detail="Нет доступа к отчётам")
    return current_user


def get_schedule_manager_user(current_user: User = Depends(get_current_user)) -> User:
    from group_page_permissions import user_can_manage_schedule

    if not user_can_manage_schedule(current_user):
        raise HTTPException(status_code=403, detail="Нет доступа к графику работ")
    return current_user


def get_impersonator_username(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> str | None:
    """Логин администратора из JWT (claim `imp`), если включён режим входа под пользователем."""
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    imp = payload.get("imp")
    if imp is None or str(imp).strip() == "":
        return None
    return str(imp).strip()


def get_chat_user(current_user: User = Depends(get_current_user)) -> User:
    if is_price_user(current_user):
        raise HTTPException(status_code=403, detail="Чат недоступен для вашей группы")
    return current_user
