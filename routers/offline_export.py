from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import Manufacturer, PricelistItem, PricelistMklItem, PricelistRxItem

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
    return {
        "id": row.id,
        "manufacturer_id": getattr(row, "manufacturer_id", None),
        "manufacturer_name": manufacturer.name if manufacturer else "",
        "lens_name": row.lens_name,
        "description": getattr(row, "description", None),
        "full_description": getattr(row, "full_description", None),
        "price": _to_float(getattr(row, "price", None)),
        "price_from": bool(getattr(row, "price_from", False)),
        "group": getattr(row, "group", ""),
        "sort_index": int(getattr(row, "sort_index", 500) or 500),
        "material": getattr(row, "material", None),
        "uv_protection": bool(getattr(row, "uv_protection", False)),
        "images": images,
        "primary_image": images[0] if images else None,
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
            "country": m.country.name if getattr(m, "country", None) else None,
            "image_url": m.image_url,
            "catalog_pdf_url": m.catalog_pdf_url,
            "open_pdf_in_lens_catalog": bool(getattr(m, "open_pdf_in_lens_catalog", True)),
            "show_country_in_lens_catalog": bool(getattr(m, "show_country_in_lens_catalog", True)),
            "show_description_in_lens_catalog": bool(getattr(m, "show_description_in_lens_catalog", True)),
        }
        for m in manufacturers
    ]

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

    snapshot_data = {
        "pricelist": [_serialize_pricelist_row(x) for x in pricelist],
        "pricelist_rx": [_serialize_pricelist_row(x) for x in pricelist_rx],
        "pricelist_mkl": [_serialize_pricelist_row(x) for x in pricelist_mkl],
        "lens_catalog": manufacturers_payload,
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
