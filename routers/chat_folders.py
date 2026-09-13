"""Пользовательские папки для организации чатов."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from database import get_db
from deps import get_chat_user
from models import ChatFolder, ChatFolderItem, GroupChatMember, PrivateDialog, User
from schemas import (
    ChatFolderAddItemRequest,
    ChatFolderCreateRequest,
    ChatFolderItemResponse,
    ChatFolderResponse,
    ChatFolderUpdateRequest,
)

router = APIRouter(prefix="/api/chat/folders", tags=["chat-folders"])

MAX_FOLDERS_PER_USER = 30
MAX_FOLDER_NAME_LEN = 64


def _folder_to_response(folder: ChatFolder) -> ChatFolderResponse:
    return ChatFolderResponse(
        id=folder.id,
        name=folder.name,
        position=folder.position,
        items=[
            ChatFolderItemResponse(
                id=it.id,
                chat_type=it.chat_type,
                private_dialog_id=it.private_dialog_id,
                group_dialog_id=it.group_dialog_id,
            )
            for it in sorted(folder.items, key=lambda x: (x.position, x.id))
        ],
    )


def _require_folder_owner(db: Session, user: User, folder_id: int) -> ChatFolder:
    folder = db.query(ChatFolder).filter(ChatFolder.id == folder_id, ChatFolder.user_id == user.id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Папка не найдена")
    return folder


def _validate_chat_access(
    db: Session,
    user: User,
    *,
    chat_type: str,
    private_dialog_id: int | None,
    group_dialog_id: int | None,
) -> tuple[str, int | None, int | None]:
    ct = (chat_type or "").strip().lower()
    if ct == "private":
        if not private_dialog_id:
            raise HTTPException(status_code=400, detail="Укажите private_dialog_id")
        dialog = db.query(PrivateDialog).filter(PrivateDialog.id == private_dialog_id).first()
        if not dialog:
            raise HTTPException(status_code=404, detail="Диалог не найден")
        if dialog.user1_id != user.id and dialog.user2_id != user.id:
            raise HTTPException(status_code=403, detail="Нет доступа к диалогу")
        hidden = (dialog.user1_id == user.id and dialog.user1_hidden) or (
            dialog.user2_id == user.id and dialog.user2_hidden
        )
        if hidden:
            raise HTTPException(status_code=400, detail="Чат скрыт из списка")
        return "private", int(private_dialog_id), None
    if ct == "group":
        if not group_dialog_id:
            raise HTTPException(status_code=400, detail="Укажите group_dialog_id")
        member = (
            db.query(GroupChatMember)
            .filter(GroupChatMember.dialog_id == group_dialog_id, GroupChatMember.user_id == user.id)
            .first()
        )
        if not member or not member.is_active:
            raise HTTPException(status_code=403, detail="Нет доступа к группе")
        return "group", None, int(group_dialog_id)
    raise HTTPException(status_code=400, detail="chat_type: private или group")


@router.get("", response_model=list[ChatFolderResponse])
def list_folders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    folders = (
        db.query(ChatFolder)
        .options(selectinload(ChatFolder.items))
        .filter(ChatFolder.user_id == current_user.id)
        .order_by(ChatFolder.position.asc(), ChatFolder.id.asc())
        .all()
    )
    return [_folder_to_response(f) for f in folders]


@router.post("", response_model=ChatFolderResponse, status_code=201)
def create_folder(
    body: ChatFolderCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Введите название папки")
    if len(name) > MAX_FOLDER_NAME_LEN:
        raise HTTPException(status_code=400, detail="Название слишком длинное")
    count = db.query(ChatFolder).filter(ChatFolder.user_id == current_user.id).count()
    if count >= MAX_FOLDERS_PER_USER:
        raise HTTPException(status_code=400, detail=f"Не больше {MAX_FOLDERS_PER_USER} папок")
    max_pos = (
        db.query(ChatFolder.position)
        .filter(ChatFolder.user_id == current_user.id)
        .order_by(ChatFolder.position.desc())
        .limit(1)
        .scalar()
    )
    folder = ChatFolder(
        user_id=current_user.id,
        name=name,
        position=(max_pos or 0) + 1,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return _folder_to_response(folder)


@router.patch("/{folder_id}", response_model=ChatFolderResponse)
def update_folder(
    folder_id: int,
    body: ChatFolderUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    folder = _require_folder_owner(db, current_user, folder_id)
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Введите название папки")
        if len(name) > MAX_FOLDER_NAME_LEN:
            raise HTTPException(status_code=400, detail="Название слишком длинное")
        folder.name = name
    if body.position is not None:
        folder.position = int(body.position)
    db.commit()
    db.refresh(folder)
    return _folder_to_response(folder)


@router.delete("/{folder_id}", status_code=204)
def delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    folder = _require_folder_owner(db, current_user, folder_id)
    db.delete(folder)
    db.commit()
    return None


@router.post("/{folder_id}/items", response_model=ChatFolderItemResponse, status_code=201)
def add_folder_item(
    folder_id: int,
    body: ChatFolderAddItemRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    folder = _require_folder_owner(db, current_user, folder_id)
    ct, priv_id, group_id = _validate_chat_access(
        db,
        current_user,
        chat_type=body.chat_type,
        private_dialog_id=body.private_dialog_id,
        group_dialog_id=body.group_dialog_id,
    )
    q = db.query(ChatFolderItem).filter(
        ChatFolderItem.folder_id == folder.id,
        ChatFolderItem.chat_type == ct,
    )
    if ct == "private":
        q = q.filter(ChatFolderItem.private_dialog_id == priv_id)
    else:
        q = q.filter(ChatFolderItem.group_dialog_id == group_id)
    existing = q.first()
    if existing:
        return ChatFolderItemResponse(
            id=existing.id,
            chat_type=existing.chat_type,
            private_dialog_id=existing.private_dialog_id,
            group_dialog_id=existing.group_dialog_id,
        )
    max_pos = (
        db.query(ChatFolderItem.position)
        .filter(ChatFolderItem.folder_id == folder.id)
        .order_by(ChatFolderItem.position.desc())
        .limit(1)
        .scalar()
    )
    item = ChatFolderItem(
        folder_id=folder.id,
        user_id=current_user.id,
        chat_type=ct,
        private_dialog_id=priv_id,
        group_dialog_id=group_id,
        position=(max_pos or 0) + 1,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return ChatFolderItemResponse(
        id=item.id,
        chat_type=item.chat_type,
        private_dialog_id=item.private_dialog_id,
        group_dialog_id=item.group_dialog_id,
    )


@router.delete("/{folder_id}/items/{item_id}", status_code=204)
def remove_folder_item(
    folder_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_chat_user),
):
    _require_folder_owner(db, current_user, folder_id)
    item = (
        db.query(ChatFolderItem)
        .filter(
            ChatFolderItem.id == item_id,
            ChatFolderItem.folder_id == folder_id,
            ChatFolderItem.user_id == current_user.id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    db.delete(item)
    db.commit()
    return None
