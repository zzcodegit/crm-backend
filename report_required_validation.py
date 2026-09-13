"""
Проверка обязательных полей отчёта при отправке (не черновик).
Ключи задаются администратором в /api/settings/report-required-fields
"""
from __future__ import annotations

from schemas import DailyReportCreate


# Допустимые ключи (защита от произвольных строк из JSON)
ALLOWED_REPORT_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "warehouse_id",
        "utro",
        "revenue",
        "nal",
        "ost",
        "bn_card_reconciliation",
        "bn_z_report",
        "return_bn",
        "return_nal",
        "returns_details",
        "vyhod",
        "percent",
        "vzyala",
        "dolg",
        "z_report_urls",
        "card_reconciliation_urls",
        "extra_payments",
        "expenses",
        "encashment_nal",
        "encashment_bn",
    }
)

FIELD_LABELS_RU: dict[str, str] = {
    "warehouse_id": "Точка (склад)",
    "utro": "Утро (фактическое значение)",
    "revenue": "Выручка",
    "nal": "Наличные",
    "ost": "Остаток наличных",
    "bn_card_reconciliation": "Безнал сверка итогов",
    "bn_z_report": "Безнал Z-отчёт",
    "return_bn": "Сумма возвратов по безналу",
    "return_nal": "Сумма возвратов по налу",
    "returns_details": "Хотя бы одна строка возвратов (детализация)",
    "vyhod": "Выход (зарплата)",
    "percent": "Процент (зарплата)",
    "vzyala": "Взято (зарплата)",
    "dolg": "Долг (зарплата)",
    "z_report_urls": "Файлы Z-отчёта",
    "card_reconciliation_urls": "Файлы сверки по картам",
    "extra_payments": "Доплаты (хотя бы одна строка)",
    "expenses": "Расходы (хотя бы одна строка)",
    "encashment_nal": "Инкассация: сумма (нал)",
    "encashment_bn": "Инкассация: сумма (безнал)",
}


def _has_vzyala(data: DailyReportCreate) -> bool:
    if data.vzyala_details:
        return any(getattr(x, "amount", None) is not None for x in data.vzyala_details)
    return data.vzyala is not None


def _has_dolg(data: DailyReportCreate) -> bool:
    if data.dolg_details:
        return any(getattr(x, "amount", None) is not None for x in data.dolg_details)
    return data.dolg is not None


def _returns_details_nonempty(data: DailyReportCreate) -> bool:
    for r in data.returns_details or []:
        if getattr(r, "amount", None) is not None:
            return True
        if (getattr(r, "date_check", None) or "").strip():
            return True
        if (getattr(r, "consultant_last_name", None) or "").strip():
            return True
        if (getattr(r, "return_reason", None) or "").strip():
            return True
    return False


def validate_report_required_fields(data: DailyReportCreate, required_keys: list[str]) -> None:
    """Бросает ValueError с текстом на русском, если не хватает полей."""
    missing_labels: list[str] = []
    keys = [k for k in required_keys if isinstance(k, str) and k in ALLOWED_REPORT_REQUIRED_KEYS]

    for key in keys:
        if key == "warehouse_id":
            if data.warehouse_id is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "utro":
            if data.utro is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "revenue":
            if data.revenue is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "nal":
            if data.nal is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "ost":
            if data.ost is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "bn_card_reconciliation":
            if data.bn_card_reconciliation is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "bn_z_report":
            if data.bn_z_report is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "return_bn":
            if not data.has_returns or data.return_bn is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "return_nal":
            if not data.has_returns or data.return_nal is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "returns_details":
            if not data.has_returns or not _returns_details_nonempty(data):
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "vyhod":
            if data.vyhod is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "percent":
            if data.percent is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "vzyala":
            if not _has_vzyala(data):
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "dolg":
            if not _has_dolg(data):
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "z_report_urls":
            if not data.z_report_urls or len(data.z_report_urls) == 0:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "card_reconciliation_urls":
            if not data.card_reconciliation_urls or len(data.card_reconciliation_urls) == 0:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "extra_payments":
            if not data.extra_payments or len(data.extra_payments) == 0:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "expenses":
            if not data.has_expenses or not data.expenses or len(data.expenses) == 0:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "encashment_nal":
            if not data.has_encashment or data.encashment_nal is None:
                missing_labels.append(FIELD_LABELS_RU[key])
        elif key == "encashment_bn":
            if not data.has_encashment or data.encashment_bn is None:
                missing_labels.append(FIELD_LABELS_RU[key])

    if missing_labels:
        raise ValueError("Не заполнены обязательные поля: " + "; ".join(missing_labels))


def validate_revenue_breakdown(data: DailyReportCreate) -> None:
    """Наличные + безнал сверка итогов должны равняться выручке."""
    if data.revenue is None or data.nal is None or data.bn_card_reconciliation is None:
        return
    total = round(float(data.nal) + float(data.bn_card_reconciliation), 2)
    rev = round(float(data.revenue), 2)
    if total != rev:
        raise ValueError(
            "Выручка должна равняться сумме полей «Наличные» и «Безнал сверка итогов»."
        )
