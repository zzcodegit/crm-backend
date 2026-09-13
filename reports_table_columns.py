"""Порядок столбцов таблицы отчётов: глобальный default и персональные настройки."""

from __future__ import annotations

# Синхронно с crm-frontend/src/reportsTableColumns.ts
ALLOWED_REPORT_TABLE_COLUMN_KEYS: frozenset[str] = frozenset(
    {
        "created_at",
        "user_username",
        "warehouse_name",
        "utro_should",
        "utro",
        "revenue",
        "nal",
        "ost",
        "ost_fact",
        "has_returns",
        "has_expenses",
        "return_bn",
        "return_nal",
        "bn_card_reconciliation",
        "bn_z_report",
        "encashment_nal",
        "encashment_bn",
        "vyhod",
        "percent",
        "vzyala",
        "dolg",
        "extra",
        "z_report",
        "card",
        "actions",
    }
)

CANONICAL_REPORT_TABLE_COLUMNS: list[str] = [
    "created_at",
    "user_username",
    "warehouse_name",
    "utro_should",
    "utro",
    "revenue",
    "nal",
    "ost",
    "ost_fact",
    "has_returns",
    "has_expenses",
    "return_bn",
    "return_nal",
    "bn_card_reconciliation",
    "bn_z_report",
    "encashment_nal",
    "encashment_bn",
    "vyhod",
    "percent",
    "vzyala",
    "dolg",
    "extra",
    "z_report",
    "card",
]

CANONICAL_REPORT_TABLE_COLUMNS_ADMIN: list[str] = [*CANONICAL_REPORT_TABLE_COLUMNS, "actions"]

# Синхронно с crm-frontend/src/reportsTableColumns.ts
REPORT_TABLE_COLUMN_LABELS: dict[str, str] = {
    "created_at": "Дата и время",
    "user_username": "Пользователь",
    "warehouse_name": "Точка",
    "utro_should": "На утро",
    "utro": "Утро",
    "revenue": "Выручка",
    "nal": "Наличные",
    "ost": "Ост. наличных (расчёт)",
    "ost_fact": "Ост. наличных (факт)",
    "has_returns": "Возвраты",
    "has_expenses": "Расходы",
    "return_bn": "Возвр. бн",
    "return_nal": "Возвр. нал",
    "bn_card_reconciliation": "Безнал сверка",
    "bn_z_report": "Безнал Z",
    "encashment_nal": "Инкасс. нал",
    "encashment_bn": "Инкасс. бн",
    "vyhod": "Выход",
    "percent": "%",
    "vzyala": "Взято",
    "dolg": "Долг",
    "extra": "Доплаты",
    "z_report": "Z-отчёт",
    "card": "Сверка",
    "actions": "Действия",
}


def normalize_report_table_column_labels(raw: object | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if key not in ALLOWED_REPORT_TABLE_COLUMN_KEYS:
            continue
        if not isinstance(val, str):
            continue
        text = val.strip()
        if text:
            out[str(key)] = text[:128]
    return out


def merge_report_table_column_labels(custom: dict[str, str] | None) -> dict[str, str]:
    merged = dict(REPORT_TABLE_COLUMN_LABELS)
    if custom:
        merged.update(custom)
    return merged


def normalize_report_table_columns(
    raw: list[str] | None,
    *,
    for_admin: bool,
    append_missing: bool = True,
) -> list[str]:
    """Уникальные ключи в порядке raw; append_missing добавляет скрытые обратно (полный канон)."""
    canonical = CANONICAL_REPORT_TABLE_COLUMNS_ADMIN if for_admin else CANONICAL_REPORT_TABLE_COLUMNS
    allowed = ALLOWED_REPORT_TABLE_COLUMN_KEYS
    if not raw:
        return list(canonical)
    seen: set[str] = set()
    out: list[str] = []
    for k in raw:
        if k not in allowed:
            continue
        if k == "actions" and not for_admin:
            continue
        if k in seen:
            continue
        out.append(k)
        seen.add(k)
    if append_missing:
        for k in canonical:
            if k not in seen:
                out.append(k)
                seen.add(k)
    return out


def parse_reports_columns_settings_blob(data: object) -> tuple[list[str], dict[str, str]]:
    """Поддержка старого формата (только список столбцов) и нового { columns, labels }."""
    if isinstance(data, list):
        cols = normalize_report_table_columns(
            [x for x in data if isinstance(x, str)],
            for_admin=True,
            append_missing=False,
        )
        return cols, {}
    if not isinstance(data, dict):
        return [], {}
    cols_raw = data.get("columns", [])
    cols: list[str] = []
    if isinstance(cols_raw, list):
        cols = [x for x in cols_raw if isinstance(x, str)]
    labels = normalize_report_table_column_labels(data.get("labels"))
    return cols, labels


def column_labels_overrides_only(custom: dict[str, str]) -> dict[str, str]:
    """Сохраняем только подписи, отличающиеся от стандартных."""
    normalized = normalize_report_table_column_labels(custom)
    return {
        k: v
        for k, v in normalized.items()
        if REPORT_TABLE_COLUMN_LABELS.get(k) != v
    }
