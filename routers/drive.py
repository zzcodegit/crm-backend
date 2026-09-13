from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import uuid4
from sqlalchemy.orm import Session

from database import get_db
from models import DriveItem, User
from schemas import (
    DriveItemResponse,
    DriveItemCreate,
    DriveItemUpdate,
    DriveItemCopyBody,
    DriveFolderPickerItem,
    DrivePublicItemResponse,
    DriveBreadcrumbItem,
)
from deps import get_current_user, is_admin


router = APIRouter()


def _user_group_ids(user: User) -> list[int]:
    try:
        return [g.id for g in user.groups]
    except Exception:
        return []


def _can_access(item: DriveItem, user: User, group_ids: list[int]) -> bool:
    if getattr(item, "is_deleted", False):
        return False
    if item.owner_user_id == user.id:
        return True
    users = set(item.shared_user_ids or [])
    groups = set(item.shared_group_ids or [])
    if users and user.id in users:
        return True
    if groups and any(gid in groups for gid in group_ids):
        return True
    return False


def _is_ancestor_of(db: Session, ancestor_id: int, node_id: int) -> bool:
    """True если ancestor_id встречается при подъёме от node_id к корню (node внутри ancestor)."""
    cur_id: Optional[int] = node_id
    seen: set[int] = set()
    while cur_id is not None:
        if cur_id in seen:
            break
        seen.add(cur_id)
        if cur_id == ancestor_id:
            return True
        row = db.query(DriveItem).filter(DriveItem.id == cur_id).first()
        if not row:
            break
        cur_id = row.parent_id
    return False


def _copy_display_name(name: str, is_folder: bool) -> str:
    if is_folder:
        return f"{name} (копия)"
    dot = name.rfind(".")
    if dot > 0:
        return f"{name[:dot]} (копия){name[dot:]}"
    return f"{name} (копия)"


def _clone_drive_subtree(
    db: Session,
    src: DriveItem,
    new_parent_id: Optional[int],
    user: User,
) -> DriveItem:
    new = DriveItem(
        parent_id=new_parent_id,
        is_folder=src.is_folder,
        name=_copy_display_name(src.name, src.is_folder),
        owner_user_id=user.id,
        file_url=src.file_url,
        mime_type=src.mime_type,
        size_bytes=src.size_bytes,
        folder_icon=src.folder_icon if src.is_folder else None,
        shared_user_ids=[],
        shared_group_ids=[],
    )
    db.add(new)
    db.flush()
    if src.is_folder:
        children = (
            db.query(DriveItem)
            .filter(DriveItem.parent_id == src.id, DriveItem.is_deleted.is_(False))
            .all()
        )
        for ch in children:
            _clone_drive_subtree(db, ch, new.id, user)
    return new


@router.get("/api/drive/items", response_model=List[DriveItemResponse])
def list_drive_items(
    parent_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None, min_length=1),
    trashed: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    admin = is_admin(user)
    q = db.query(DriveItem)
    if trashed:
        # Корзина по умолчанию — только свои удалённые, но админ может видеть удалённые всех пользователей.
        q = q.filter(DriveItem.is_deleted.is_(True))
        if not admin:
            q = q.filter(DriveItem.owner_user_id == user.id)
    else:
        q = q.filter(DriveItem.is_deleted.is_(False))
        if parent_id is None:
            q = q.filter(DriveItem.parent_id.is_(None))
        else:
            q = q.filter(DriveItem.parent_id == parent_id)
    if search:
        like = f"%{search}%"
        q = q.filter(DriveItem.name.ilike(like))
    items = q.order_by(DriveItem.is_folder.desc(), DriveItem.name.asc()).all()
    # Администратор видит все элементы (кроме скрытых как deleted в обычном режиме).
    # Для остальных — только доступные по шарингу/владению.
    if admin:
        visible = items
    else:
        gids = _user_group_ids(user)
        visible = [it for it in items if trashed or _can_access(it, user, gids)]
    return [DriveItemResponse.from_orm(it) for it in visible]


@router.get("/api/drive/path", response_model=List[DriveBreadcrumbItem])
def get_drive_path(
    parent_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Хлебные крошки: путь от корня до parent_id (включая parent_id), без "Корень".
    Корень обозначается parent_id=None → [].
    """
    if parent_id is None:
        return []
    node = db.query(DriveItem).filter(DriveItem.id == parent_id).first()
    if not node or getattr(node, "is_deleted", False) or not node.is_folder:
        raise HTTPException(status_code=404, detail="Папка не найдена")
    admin = is_admin(user)
    gids = _user_group_ids(user)
    if not admin and not _can_access(node, user, gids):
        raise HTTPException(status_code=403, detail="Нет прав")

    out: list[DriveBreadcrumbItem] = []
    seen: set[int] = set()
    cur: Optional[DriveItem] = node
    while cur is not None:
        if cur.id in seen:
            break
        seen.add(cur.id)
        if not admin and not _can_access(cur, user, gids):
            raise HTTPException(status_code=403, detail="Нет прав")
        out.append(DriveBreadcrumbItem(id=cur.id, name=cur.name))
        if cur.parent_id is None:
            break
        cur = db.query(DriveItem).filter(DriveItem.id == cur.parent_id).first()

    out.reverse()
    return out


@router.get("/api/drive/items/{item_id}", response_model=DriveItemResponse)
def get_drive_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = db.query(DriveItem).filter(DriveItem.id == item_id).first()
    if not obj or getattr(obj, "is_deleted", False):
        raise HTTPException(status_code=404, detail="Элемент не найден")
    if not is_admin(user):
        gids = _user_group_ids(user)
        if not _can_access(obj, user, gids):
            raise HTTPException(status_code=403, detail="Нет прав")
    return DriveItemResponse.from_orm(obj)


@router.post("/api/drive/items", response_model=DriveItemResponse, status_code=201)
def create_drive_item(
    data: DriveItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Проверка родителя и прав
    parent: Optional[DriveItem] = None
    if data.parent_id is not None:
        parent = db.query(DriveItem).filter(DriveItem.id == data.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Родительская папка не найдена")
        gids = _user_group_ids(user)
        if not _can_access(parent, user, gids) or not parent.is_folder:
            raise HTTPException(status_code=403, detail="Нет прав на эту папку")

    obj = DriveItem(
        parent_id=data.parent_id,
        is_folder=data.is_folder,
        name=data.name.strip(),
        owner_user_id=user.id,
        file_url=data.file_url,
        mime_type=data.mime_type,
        size_bytes=data.size_bytes,
        shared_user_ids=data.shared_user_ids or [],
        shared_group_ids=data.shared_group_ids or [],
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return DriveItemResponse.from_orm(obj)


@router.patch("/api/drive/items/{item_id}", response_model=DriveItemResponse)
def update_drive_item(
    item_id: int,
    data: DriveItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = db.query(DriveItem).filter(DriveItem.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    gids = _user_group_ids(user)
    if not _can_access(obj, user, gids):
        raise HTTPException(status_code=403, detail="Нет прав")

    if data.name is not None:
        obj.name = data.name.strip() or obj.name
    if data.parent_id is not None and data.parent_id != obj.parent_id:
        if data.parent_id == 0:
            obj.parent_id = None
        else:
            parent = db.query(DriveItem).filter(DriveItem.id == data.parent_id).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Новая папка не найдена")
            if not parent.is_folder or not _can_access(parent, user, gids):
                raise HTTPException(status_code=403, detail="Нет прав на новую папку")
            if obj.is_folder and _is_ancestor_of(db, obj.id, parent.id):
                raise HTTPException(
                    status_code=400,
                    detail="Нельзя переместить папку внутрь самой себя",
                )
            obj.parent_id = parent.id
    if data.shared_user_ids is not None:
        obj.shared_user_ids = list({int(x) for x in data.shared_user_ids})
    if data.shared_group_ids is not None:
        obj.shared_group_ids = list({int(x) for x in data.shared_group_ids})
    if data.folder_icon is not None:
        if not obj.is_folder:
            raise HTTPException(status_code=400, detail="Иконку можно менять только у папки")
        icon = (data.folder_icon or "").strip()
        obj.folder_icon = icon or None
    if data.public_enabled is not None:
        if obj.is_folder:
            raise HTTPException(status_code=400, detail="Публичная ссылка доступна только для файлов")
        if obj.owner_user_id != user.id and not is_admin(user):
            raise HTTPException(status_code=403, detail="Изменять публичную ссылку может только владелец")
        if data.public_enabled:
            if not obj.public_token:
                obj.public_token = uuid4().hex
            obj.public_enabled = True
        else:
            obj.public_enabled = False
            obj.public_token = None

    db.commit()
    db.refresh(obj)
    return DriveItemResponse.from_orm(obj)


@router.get("/api/public/drive/{token}", response_model=DrivePublicItemResponse)
def get_public_drive_item(token: str, db: Session = Depends(get_db)):
    tok = (token or "").strip()
    if not tok:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    obj = db.query(DriveItem).filter(DriveItem.public_token == tok).first()
    if not obj or getattr(obj, "is_deleted", False) or obj.is_folder or not getattr(obj, "public_enabled", False):
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return DrivePublicItemResponse(
        item_id=obj.id,
        name=obj.name,
        file_url=obj.file_url,
        mime_type=obj.mime_type,
        size_bytes=obj.size_bytes,
    )


@router.post("/api/drive/items/{item_id}/copy", response_model=DriveItemResponse, status_code=201)
def copy_drive_item(
    item_id: int,
    data: DriveItemCopyBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    src = db.query(DriveItem).filter(DriveItem.id == item_id).first()
    if not src or getattr(src, "is_deleted", False):
        raise HTTPException(status_code=404, detail="Элемент не найден")
    gids = _user_group_ids(user)
    if not is_admin(user) and not _can_access(src, user, gids):
        raise HTTPException(status_code=403, detail="Нет прав")

    target_parent_id: Optional[int] = src.parent_id
    if data.parent_id is not None:
        if data.parent_id == 0:
            target_parent_id = None
        else:
            parent = db.query(DriveItem).filter(DriveItem.id == data.parent_id).first()
            if not parent or not parent.is_folder:
                raise HTTPException(status_code=404, detail="Папка назначения не найдена")
            if not _can_access(parent, user, gids) and not is_admin(user):
                raise HTTPException(status_code=403, detail="Нет прав на папку назначения")
            if src.is_folder and _is_ancestor_of(db, src.id, parent.id):
                raise HTTPException(
                    status_code=400,
                    detail="Нельзя копировать папку внутрь самой себя",
                )
            target_parent_id = parent.id

    new_root = _clone_drive_subtree(db, src, target_parent_id, user)
    db.commit()
    db.refresh(new_root)
    return DriveItemResponse.from_orm(new_root)


@router.get("/api/drive/folders", response_model=List[DriveFolderPickerItem])
def list_drive_folders_picker(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(DriveItem).filter(DriveItem.is_folder.is_(True), DriveItem.is_deleted.is_(False))
    rows = q.order_by(DriveItem.name.asc()).all()
    admin = is_admin(user)
    if admin:
        visible = rows
    else:
        gids = _user_group_ids(user)
        visible = [f for f in rows if _can_access(f, user, gids)]
    return [DriveFolderPickerItem(id=f.id, parent_id=f.parent_id, name=f.name) for f in visible]


@router.delete("/api/drive/items/{item_id}", status_code=204)
def delete_drive_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = db.query(DriveItem).filter(DriveItem.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    if obj.owner_user_id != user.id and not is_admin(user):
        raise HTTPException(status_code=403, detail="Удалять может только владелец")
    obj.is_deleted = True
    obj.deleted_at = datetime.now(timezone.utc)
    obj.deleted_by_user_id = user.id
    db.commit()
    return None


@router.post("/api/drive/items/{item_id}/restore", response_model=DriveItemResponse)
def restore_drive_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = db.query(DriveItem).filter(DriveItem.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    if obj.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Восстанавливать может только владелец")
    if not obj.is_deleted:
        return DriveItemResponse.from_orm(obj)
    obj.is_deleted = False
    obj.deleted_at = None
    obj.deleted_by_user_id = None
    db.commit()
    db.refresh(obj)
    return DriveItemResponse.from_orm(obj)


@router.delete("/api/drive/items/{item_id}/purge", status_code=204)
def purge_drive_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = db.query(DriveItem).filter(DriveItem.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    if obj.owner_user_id != user.id and not is_admin(user):
        raise HTTPException(status_code=403, detail="Удалять может только владелец")
    db.delete(obj)
    db.commit()
    return None

