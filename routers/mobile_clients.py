"""Регистрация мобильных клиентов (версии APK/OTA) и просмотр для админов."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from database import get_db
from deps import get_admin_user, get_current_user_optional, is_admin
from models import MobileAppClient, User

router = APIRouter(tags=["mobile-clients"])


class MobileClientPingBody(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=128)
    app_slug: str = Field(default="apkprice", max_length=64)
    native_version: str | None = Field(None, max_length=64)
    native_build: int | None = None
    bundle_version: str | None = Field(None, max_length=128)
    offline_data_version: str | None = Field(None, max_length=128)
    platform: str = Field(default="android", max_length=32)
    os_version: str | None = Field(None, max_length=64)
    device_model: str | None = Field(None, max_length=128)
    device_manufacturer: str | None = Field(None, max_length=128)


class MobileClientPingResponse(BaseModel):
    ok: bool = True


class MobileClientRow(BaseModel):
    id: int
    device_id: str
    username: str | None = None
    app_slug: str
    native_version: str | None
    native_build: int | None
    bundle_version: str | None
    offline_data_version: str | None
    platform: str
    os_version: str | None
    device_model: str | None
    device_manufacturer: str | None
    first_seen_at: datetime
    last_seen_at: datetime

    class Config:
        from_attributes = True


@router.post("/api/mobile/clients/ping", response_model=MobileClientPingResponse)
def ping_mobile_client(
    body: MobileClientPingBody,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Вызывается из APK/WebView при запуске и после обновления. Опционально с Bearer — привязываем user_id."""
    now = datetime.now(timezone.utc)
    row = db.query(MobileAppClient).filter(MobileAppClient.device_id == body.device_id.strip()).first()
    uid = current_user.id if current_user and is_admin(current_user) or current_user else None
    # Для не-админов тоже сохраняем user_id — чтобы видеть, кто с какого аккаунта заходил в приложение.
    if current_user:
        uid = current_user.id

    if row:
        row.app_slug = body.app_slug.strip() or row.app_slug
        row.native_version = body.native_version
        row.native_build = body.native_build
        row.bundle_version = body.bundle_version
        row.offline_data_version = body.offline_data_version
        row.platform = (body.platform or "android").strip()[:32]
        row.os_version = body.os_version
        row.device_model = body.device_model
        row.device_manufacturer = body.device_manufacturer
        row.last_seen_at = now
        if uid is not None:
            row.user_id = uid
    else:
        row = MobileAppClient(
            device_id=body.device_id.strip()[:128],
            user_id=uid,
            app_slug=(body.app_slug or "apkprice").strip()[:64] or "apkprice",
            native_version=body.native_version,
            native_build=body.native_build,
            bundle_version=body.bundle_version,
            offline_data_version=body.offline_data_version,
            platform=(body.platform or "android").strip()[:32],
            os_version=body.os_version,
            device_model=body.device_model,
            device_manufacturer=body.device_manufacturer,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(row)
    db.commit()
    return MobileClientPingResponse(ok=True)


@router.get("/api/settings/mobile-clients", response_model=list[MobileClientRow])
def list_mobile_clients(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(MobileAppClient)
        .options(joinedload(MobileAppClient.user))
        .order_by(MobileAppClient.last_seen_at.desc())
        .limit(500)
        .all()
    )
    out: list[MobileClientRow] = []
    for r in rows:
        uname = r.user.username if r.user else None
        out.append(
            MobileClientRow(
                id=r.id,
                device_id=r.device_id,
                username=uname,
                app_slug=r.app_slug,
                native_version=r.native_version,
                native_build=r.native_build,
                bundle_version=r.bundle_version,
                offline_data_version=r.offline_data_version,
                platform=r.platform,
                os_version=r.os_version,
                device_model=r.device_model,
                device_manufacturer=r.device_manufacturer,
                first_seen_at=r.first_seen_at,
                last_seen_at=r.last_seen_at,
            )
        )
    return out


@router.delete("/api/settings/mobile-clients/{client_id}", status_code=204)
def delete_mobile_client(
    client_id: int,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Удалить запись устройства из реестра (админ)."""
    row = db.query(MobileAppClient).filter(MobileAppClient.id == client_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(row)
    db.commit()
    return None
