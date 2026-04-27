from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

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
    images = _collect_images(getattr(row, "photo_urls", None), getattr(row, "photo_url", None))
    feature_ids = getattr(row, "feature_ids", None)
    feature_colors = getattr(row, "feature_colors", None)
    custom_values = getattr(row, "custom_values", None)
    barcodes = getattr(row, "barcodes", None)
    barcode_sections = getattr(row, "barcode_sections", None)
    price = _to_float(getattr(row, "price", None))
    return {
        "id": row.id,
        "manufacturer_id": getattr(row, "manufacturer_id", None),
        "manufacturer_name": manufacturer.name if manufacturer else "",
        "lens_name": row.lens_name,
        "description": getattr(row, "description", None),
        "full_description": getattr(row, "full_description", None),
        "barcode": getattr(row, "barcode", None),
        "barcodes": barcodes if isinstance(barcodes, list) else [],
        "barcode_sections": barcode_sections if isinstance(barcode_sections, list) else [],
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
    for row in pricelist_rx:
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
        "pricelist_rx": [_serialize_pricelist_row(x) for x in pricelist_rx],
        "pricelist_mkl": [_serialize_pricelist_row(x) for x in pricelist_mkl],
        "lens_catalog": manufacturers_payload,
        "manufacturers": manufacturers_payload,
        "features": _feature_payload(features),
        "custom_fields": _custom_fields_payload(custom_fields),
        "pricelist_groups": _group_payload(warehouse_groups),
        "pricelist_rx_groups": _group_payload(rx_groups),
        "pricelist_mkl_groups": _group_payload(mkl_groups),
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


@router.get("/api/offline/version")
def get_offline_version(db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = _snapshot_payload(db)
    return {
        "version": payload["version"],
        "checksum": payload["checksum"],
        "generated_at": payload["generated_at"],
        "asset_count": len(payload["snapshot"]["assets"]),
    }


@router.get("/api/offline/snapshot")
def get_offline_snapshot(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _snapshot_payload(db)
