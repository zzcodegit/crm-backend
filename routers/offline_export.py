from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import (
    CustomFieldDefinition,
    Feature,
    Manufacturer,
    PricelistGroup,
    PricelistItem,
    PricelistMklGroup,
    PricelistMklItem,
    PricelistRxGroup,
    PricelistRxItem,
)

router = APIRouter(tags=["offline-export"])


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return None


_SIDEBAR_VIDEO_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "logs" / "sidebar_video_settings.json"


def _read_sidebar_video_settings() -> dict[str, Any]:
    """Как GET /api/settings/sidebar-video — из того же JSON, что и main.py."""
    try:
        raw = _SIDEBAR_VIDEO_SETTINGS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return {"video_url": None, "visible_group_ids": []}
    vu_raw = data.get("video_url")
    video_url = str(vu_raw).strip() if isinstance(vu_raw, str) and vu_raw.strip() else None
    ids_raw = data.get("visible_group_ids")
    visible_group_ids: list[int] = []
    if isinstance(ids_raw, list):
        for x in ids_raw:
            try:
                visible_group_ids.append(int(x))
            except (TypeError, ValueError):
                continue
    return {"video_url": video_url, "visible_group_ids": visible_group_ids}


def _collect_images(photo_urls: Any, photo_url: str | None) -> list[str]:
    out: list[str] = []
    if isinstance(photo_urls, list):
        out.extend(str(x) for x in photo_urls if x)
    if photo_url:
        out.append(photo_url)
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return uniq


def _serialize_pricelist_row(row: Any) -> dict[str, Any]:
    manufacturer = getattr(row, "manufacturer", None)
    manufacturer_country = getattr(getattr(manufacturer, "country", None), "name", None) if manufacturer else None
    images = _collect_images(getattr(row, "photo_urls", None), getattr(row, "photo_url", None))
    feature_ids = getattr(row, "feature_ids", None)
    feature_colors = getattr(row, "feature_colors", None)
    custom_values = getattr(row, "custom_values", None)
    barcodes_raw = getattr(row, "barcodes", None)
    barcode_sections_raw = getattr(row, "barcode_sections", None)
    barcodes: list[dict[str, Any]] = []
    barcode_sections: list[dict[str, Any]] = []
    # Поддерживаем все форматы хранения:
    # 1) legacy list[str]
    # 2) list[{code, price, description}]
    # 3) {"_v": 2, "sections": [{name, items:[...]}]}
    if isinstance(barcodes_raw, dict):
        sections_raw = barcodes_raw.get("sections")
        if isinstance(sections_raw, list):
            for sec in sections_raw:
                if not isinstance(sec, dict):
                    continue
                items_raw = sec.get("items")
                if not isinstance(items_raw, list):
                    continue
                entries: list[dict[str, Any]] = []
                for it in items_raw:
                    if isinstance(it, str):
                        code = it.strip()
                        if code:
                            entries.append({"code": code, "price": None, "description": None})
                    elif isinstance(it, dict):
                        code = str(it.get("code") or "").strip()
                        if code:
                            entries.append(
                                {
                                    "code": code,
                                    "price": _to_float(it.get("price")),
                                    "description": str(it.get("description") or "").strip() or None,
                                }
                            )
                if entries:
                    barcode_sections.append({"name": str(sec.get("name") or "").strip() or None, "items": entries})
                    barcodes.extend(entries)
    elif isinstance(barcodes_raw, list):
        for it in barcodes_raw:
            if isinstance(it, str):
                code = it.strip()
                if code:
                    barcodes.append({"code": code, "price": None, "description": None})
            elif isinstance(it, dict):
                code = str(it.get("code") or "").strip()
                if code:
                    barcodes.append(
                        {
                            "code": code,
                            "price": _to_float(it.get("price")),
                            "description": str(it.get("description") or "").strip() or None,
                        }
                    )
        if barcodes:
            barcode_sections = [{"name": None, "items": list(barcodes)}]
    if not barcodes and isinstance(barcode_sections_raw, list):
        for sec in barcode_sections_raw:
            if not isinstance(sec, dict):
                continue
            items_raw = sec.get("items")
            if not isinstance(items_raw, list):
                continue
            entries: list[dict[str, Any]] = []
            for it in items_raw:
                if isinstance(it, str):
                    code = it.strip()
                    if code:
                        entries.append({"code": code, "price": None, "description": None})
                elif isinstance(it, dict):
                    code = str(it.get("code") or "").strip()
                    if code:
                        entries.append(
                            {
                                "code": code,
                                "price": _to_float(it.get("price")),
                                "description": str(it.get("description") or "").strip() or None,
                            }
                        )
            if entries:
                barcode_sections.append({"name": str(sec.get("name") or "").strip() or None, "items": entries})
                barcodes.extend(entries)
    if not barcodes:
        barcode_single = str(getattr(row, "barcode", None) or "").strip()
        if barcode_single:
            barcodes = [{"code": barcode_single, "price": None, "description": None}]
            barcode_sections = [{"name": None, "items": list(barcodes)}]
    price = _to_float(getattr(row, "price", None))
    return {
        "id": row.id,
        "manufacturer_id": getattr(row, "manufacturer_id", None),
        "manufacturer_name": manufacturer.name if manufacturer else "",
        "manufacturer_image_url": getattr(manufacturer, "image_url", None) if manufacturer else None,
        "manufacturer_country_name": manufacturer_country,
        "lens_name": row.lens_name,
        "description": getattr(row, "description", None),
        "full_description": getattr(row, "full_description", None),
        "barcode": getattr(row, "barcode", None),
        "barcodes": barcodes,
        "barcode_sections": barcode_sections,
        "photo_url": images[0] if images else None,
        "photo_urls": images,
        "sph": getattr(row, "sph", None),
        "cyl": getattr(row, "cyl", None),
        "step": getattr(row, "step", None),
        "diameters": getattr(row, "diameters", None),
        "price": price if price is not None else 0.0,
        "price_from": bool(getattr(row, "price_from", False)),
        "is_promo": bool(getattr(row, "is_promo", False)),
        "group": getattr(row, "group", ""),
        "sort_index": int(getattr(row, "sort_index", 500) or 500),
        "material": getattr(row, "material", None),
        "uv_protection": bool(getattr(row, "uv_protection", False)),
        "lens_id": getattr(row, "lens_id", None),
        "coefficient": getattr(row, "coefficient", None),
        "feature_ids": feature_ids if isinstance(feature_ids, list) else [],
        "feature_colors": feature_colors if isinstance(feature_colors, dict) else {},
        "custom_values": custom_values if isinstance(custom_values, dict) else {},
        "hide_detail_link": bool(getattr(row, "hide_detail_link", False)),
        "hide_photo": bool(getattr(row, "hide_photo", False)),
        "enable_transposition_calc": bool(getattr(row, "enable_transposition_calc", False)),
        "admin_only": bool(getattr(row, "admin_only", False)),
    }


def _snapshot_payload(db: Session) -> dict[str, Any]:
    pricelist = (
        db.query(PricelistItem)
        .options(joinedload(PricelistItem.manufacturer))
        .order_by(PricelistItem.group, PricelistItem.sort_index, PricelistItem.id)
        .all()
    )
    pricelist_rx = (
        db.query(PricelistRxItem)
        .options(joinedload(PricelistRxItem.manufacturer))
        .order_by(PricelistRxItem.group, PricelistRxItem.sort_index, PricelistRxItem.id)
        .all()
    )
    pricelist_mkl = (
        db.query(PricelistMklItem)
        .options(joinedload(PricelistMklItem.manufacturer))
        .order_by(PricelistMklItem.group, PricelistMklItem.sort_index, PricelistMklItem.id)
        .all()
    )
    manufacturers = (
        db.query(Manufacturer)
        .options(joinedload(Manufacturer.country))
        .filter(Manufacturer.show_in_lens_catalog == True)  # noqa: E712
        .order_by(Manufacturer.name)
        .all()
    )
    manufacturers_payload = [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "country_id": m.country_id,
            "country": m.country.name if getattr(m, "country", None) else None,
            "image_url": m.image_url,
            "catalog_pdf_url": m.catalog_pdf_url,
            "show_in_lens_catalog": bool(getattr(m, "show_in_lens_catalog", True)),
            "open_pdf_in_lens_catalog": bool(getattr(m, "open_pdf_in_lens_catalog", True)),
            "show_country_in_lens_catalog": bool(getattr(m, "show_country_in_lens_catalog", True)),
            "show_description_in_lens_catalog": bool(getattr(m, "show_description_in_lens_catalog", True)),
        }
        for m in manufacturers
    ]
    warehouse_groups = db.query(PricelistGroup).order_by(PricelistGroup.sort_index, PricelistGroup.name).all()
    rx_groups = db.query(PricelistRxGroup).order_by(PricelistRxGroup.sort_index, PricelistRxGroup.name).all()
    mkl_groups = db.query(PricelistMklGroup).order_by(PricelistMklGroup.sort_index, PricelistMklGroup.name).all()
    features = db.query(Feature).order_by(Feature.name).all()
    custom_fields = (
        db.query(CustomFieldDefinition)
        .options(joinedload(CustomFieldDefinition.options))
        .order_by(CustomFieldDefinition.sort_index, CustomFieldDefinition.id)
        .all()
    )

    assets: set[str] = set()
    for row in pricelist:
        assets.update(_collect_images(getattr(row, "photo_urls", None), getattr(row, "photo_url", None)))
    # Как GET /api/pricelist-rx для не-админа: в APK только публичные позиции RX.
    pricelist_rx_public = [x for x in pricelist_rx if not bool(getattr(x, "admin_only", False))]
    for row in pricelist_rx_public:
        assets.update(_collect_images(getattr(row, "photo_urls", None), getattr(row, "photo_url", None)))
    for row in pricelist_mkl:
        assets.update(_collect_images(getattr(row, "photo_urls", None), getattr(row, "photo_url", None)))
    for m in manufacturers:
        if m.image_url:
            assets.add(m.image_url)
        if m.catalog_pdf_url:
            assets.add(m.catalog_pdf_url)
    for f in features:
        if getattr(f, "icon_url", None):
            assets.add(f.icon_url)

    sidebar_video = _read_sidebar_video_settings()
    sv_url = sidebar_video.get("video_url")
    if isinstance(sv_url, str):
        sv_u = sv_url.strip()
        if sv_u.startswith("/uploads/"):
            assets.add(sv_u.split("?")[0])
        elif sv_u.startswith("http://") or sv_u.startswith("https://"):
            try:
                path = urlparse(sv_u).path
                if path.startswith("/uploads/"):
                    assets.add(path.split("?")[0])
            except Exception:
                pass

    def _group_payload(rows: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "id": x.id,
                "name": x.name,
                "sort_index": int(getattr(x, "sort_index", 500) or 500),
                "display_properties_in_list": bool(getattr(x, "display_properties_in_list", True)),
                "display_as_tiles": bool(getattr(x, "display_as_tiles", False)),
                "tiles_per_page": int(getattr(x, "tiles_per_page", 4) or 4),
            }
            for x in rows
        ]

    def _feature_payload(rows: list[Any]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for x in rows:
            colors = getattr(x, "colors", None)
            payload.append(
                {
                    "id": x.id,
                    "name": x.name,
                    "icon_url": getattr(x, "icon_url", None),
                    "color": getattr(x, "color", None),
                    "colors": colors if isinstance(colors, list) else [],
                }
            )
        return payload

    def _custom_fields_payload(rows: list[Any]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for x in rows:
            options = []
            for opt in sorted(getattr(x, "options", []) or [], key=lambda o: (o.sort_index or 500, o.id)):
                if not getattr(opt, "is_active", True):
                    continue
                options.append(
                    {
                        "id": opt.id,
                        "field_id": opt.field_id,
                        "value": opt.value,
                        "sort_index": int(getattr(opt, "sort_index", 500) or 500),
                        "is_active": bool(getattr(opt, "is_active", True)),
                    }
                )
            payload.append(
                {
                    "id": x.id,
                    "code": x.code,
                    "label": x.label,
                    "field_type": x.field_type,
                    "is_required": bool(getattr(x, "is_required", False)),
                    "is_active": bool(getattr(x, "is_active", True)),
                    "show_in_warehouse": bool(getattr(x, "show_in_warehouse", True)),
                    "show_in_rx": bool(getattr(x, "show_in_rx", True)),
                    "show_in_mkl": bool(getattr(x, "show_in_mkl", True)),
                    "sort_index": int(getattr(x, "sort_index", 500) or 500),
                    "options": options,
                }
            )
        return payload

    snapshot_data = {
        "pricelist": [_serialize_pricelist_row(x) for x in pricelist],
        "pricelist_rx": [_serialize_pricelist_row(x) for x in pricelist_rx_public],
        "pricelist_mkl": [_serialize_pricelist_row(x) for x in pricelist_mkl],
        "lens_catalog": manufacturers_payload,
        "manufacturers": manufacturers_payload,
        "features": _feature_payload(features),
        "custom_fields": _custom_fields_payload(custom_fields),
        "pricelist_groups": _group_payload(warehouse_groups),
        "pricelist_rx_groups": _group_payload(rx_groups),
        "pricelist_mkl_groups": _group_payload(mkl_groups),
        "sidebar_video": sidebar_video,
        "assets": sorted(assets),
    }
    normalized = json.dumps(snapshot_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "version": checksum[:16],
        "checksum": checksum,
        "generated_at": generated_at,
        "snapshot": snapshot_data,
    }


_OFFLINE_VERSION_CACHE: dict[str, Any] | None = None
_OFFLINE_VERSION_CACHE_AT: float = 0.0
_OFFLINE_VERSION_TTL_SEC = 120.0


def _offline_version_meta(db: Session) -> dict[str, Any]:
    global _OFFLINE_VERSION_CACHE, _OFFLINE_VERSION_CACHE_AT
    now = time.monotonic()
    if _OFFLINE_VERSION_CACHE is not None and (now - _OFFLINE_VERSION_CACHE_AT) < _OFFLINE_VERSION_TTL_SEC:
        return _OFFLINE_VERSION_CACHE
    payload = _snapshot_payload(db)
    meta = {
        "version": payload["version"],
        "checksum": payload["checksum"],
        "generated_at": payload["generated_at"],
        "asset_count": len(payload["snapshot"]["assets"]),
    }
    _OFFLINE_VERSION_CACHE = meta
    _OFFLINE_VERSION_CACHE_AT = now
    return meta


@router.get("/api/offline/version")
def get_offline_version(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _offline_version_meta(db)


@router.get("/api/offline/snapshot")
def get_offline_snapshot(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _snapshot_payload(db)
