"""Права групп на разделы CRM (файл logs/group_page_permissions.json)."""

from __future__ import annotations

import json
from pathlib import Path

from models import User

from deps import is_admin

GROUP_PERMISSIONS_FILE = Path("/home/crm-backend/logs/group_page_permissions.json")

SCHEDULE_SECTION_KEY = "scheduleManagement"

ALLOWED_SECTION_KEYS: frozenset[str] = frozenset(
    {
        "dashboard",
        "orders",
        "lensCatalog",
        "drive",
        "pricelist",
        "pricelistRx",
        "pricelistMkl",
        "reports",
        "training",
        "normativeActs",
        "chat",
        "supplyTickets",
        "tasks",
        SCHEDULE_SECTION_KEY,
    }
)


def load_group_permissions_map() -> dict[str, list[str]]:
    if not GROUP_PERMISSIONS_FILE.exists():
        return {}
    try:
        data = json.loads(GROUP_PERMISSIONS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: dict[str, list[str]] = {}
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, list):
                continue
            out[key] = [v for v in value if isinstance(v, str) and v in ALLOWED_SECTION_KEYS]
        return out
    except Exception:
        return {}


def group_has_schedule_management(group_id: int, permissions: dict[str, list[str]] | None = None) -> bool:
    """График работ: явно включён, если у группы есть запись и scheduleManagement не в deny."""
    perms = permissions if permissions is not None else load_group_permissions_map()
    denied = perms.get(str(group_id))
    if denied is None:
        return False
    return SCHEDULE_SECTION_KEY not in denied


def user_can_manage_schedule(user: User) -> bool:
    if is_admin(user):
        return True
    if not user.groups:
        return False
    perms = load_group_permissions_map()
    return any(group_has_schedule_management(g.id, perms) for g in user.groups)
