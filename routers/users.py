from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User, Group
from sqlalchemy import func as sa_func
from schemas import UserResponse, UserCreate, UserUpdate, InviteUserRequest
from auth import get_password_hash
from deps import get_admin_user
from chat_default_groups import apply_default_chat_groups_to_user
from schedule_user_sync import rename_user_in_schedules

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    users = db.query(User).order_by(User.username).all()
    return users


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")
    user = User(
        username=data.username,
        hashed_password=get_password_hash(data.password),
        is_active=True,
        first_name=data.first_name or None,
        last_name=data.last_name or None,
        patronymic=data.patronymic or None,
        telegram_id=data.telegram_id or None,
        phone=data.phone or None,
        birth_date=data.birth_date,
    )
    db.add(user)
    db.flush()
    apply_default_chat_groups_to_user(db, user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    old_username = user.username
    old_first_name = user.first_name
    old_last_name = user.last_name
    if data.username is not None:
        new_username = (data.username or "").strip()
        if not new_username:
            raise HTTPException(status_code=400, detail="Логин не может быть пустым")
        if new_username != user.username:
            taken = (
                db.query(User.id)
                .filter(User.username == new_username, User.id != user_id)
                .first()
            )
            if taken:
                raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")
            user.username = new_username
    if data.first_name is not None:
        user.first_name = data.first_name or None
    if data.last_name is not None:
        user.last_name = data.last_name or None
    if data.patronymic is not None:
        user.patronymic = data.patronymic or None
    if data.telegram_id is not None:
        user.telegram_id = data.telegram_id or None
    if data.phone is not None:
        user.phone = data.phone or None
    if "birth_date" in data.model_fields_set:
        user.birth_date = data.birth_date
    if "schedule_color" in data.model_fields_set:
        user.schedule_color = data.schedule_color or None
    if data.is_active is not None:
        user.is_active = data.is_active
    # Пустой password в PATCH не должен затирать текущий пароль (как «пусто = не менять» в UI).
    if "password" in data.model_fields_set:
        pwd = (data.password or "").strip()
        if pwd:
            user.hashed_password = get_password_hash(pwd)
    rename_user_in_schedules(
        db,
        old_username=old_username,
        old_first_name=old_first_name,
        old_last_name=old_last_name,
        user=user,
    )
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    exists = db.query(User.id).filter(User.id == user_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    # Важно: удаляем пользователя прямым SQL DELETE, чтобы сработали
    # on delete cascade/set null на уровне БД и ORM не пытался обнулить
    # not-null foreign keys (например drive_items.owner_user_id).
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.commit()
    return None


@router.post("/invite", response_model=UserResponse, status_code=201)
def invite_user(
    data: InviteUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    fio = (data.fio or "").strip()
    if not fio:
        raise HTTPException(status_code=400, detail="Укажите ФИО")

    # Минимальная логика: логин = введённое ФИО.
    username = " ".join(fio.split())
    user = (
        db.query(User)
        .filter(sa_func.lower(User.username) == sa_func.lower(username))
        .first()
    )

    parts = username.split()
    last_name = parts[0] if len(parts) >= 1 else None
    first_name = parts[1] if len(parts) >= 2 else None
    patronymic = " ".join(parts[2:]) if len(parts) >= 3 else None

    # Пароль ещё не задан: hashed_password храним пустым значением.
    # Это позволит вход без пароля вернуть специальный статус, а затем задать пароль.
    if not user:
        user = User(
            username=username,
            hashed_password="",
            is_active=True,
            first_name=first_name or None,
            last_name=last_name or None,
            patronymic=patronymic or None,
        )
        db.add(user)
        db.flush()

    apply_default_chat_groups_to_user(db, user)

    # Добавляем в группу, если передана (дополнительно к настройке по умолчанию)
    if data.group_name:
        group_name = (data.group_name or "").strip()
        if not group_name:
            group_name = None
        if group_name:
            group = db.query(Group).filter(Group.name == group_name).first()
            if not group:
                raise HTTPException(status_code=400, detail=f"Группа не найдена: {group_name}")
            # Подстраховка от дублей (many-to-many)
            if group not in user.groups:
                user.groups.append(group)
            db.flush()

    db.commit()
    db.refresh(user)
    return user
