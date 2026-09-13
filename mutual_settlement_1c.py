"""Контроль дубликатов bonus_arr из 1С.

Взаимозачёт: один документ (номер 00ЦБ-N) в рамках календарного года —
первая запись остаётся, повтор не пишем и не обновляем.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from models import Order1cExchangeLog

MUTUAL_SETTLEMENT_DOC_RE = re.compile(r"взаимозач", re.IGNORECASE)
DOC_NUMBER_RE = re.compile(r"(?:00\s*ЦБ|00CB|00цб)\s*-\s*(\d+)", re.IGNORECASE)
DOC_DATE_RE = re.compile(r"от\s+(\d{1,2})\.(\d{1,2})\.(\d{4})", re.IGNORECASE)


def normalize_order_number(value: Any) -> str:
    return str(value or "").replace("\xa0", " ").strip()


def normalize_bonus_sum(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def is_mutual_settlement_row(row: dict) -> bool:
    doc = str(row.get("doc") or "")
    return bool(MUTUAL_SETTLEMENT_DOC_RE.search(doc))


def extract_doc_number(doc: str) -> int | None:
    text = str(doc or "")
    m = DOC_NUMBER_RE.search(text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    nums = re.findall(r"\d+", text)
    if not nums:
        return None
    try:
        return int(nums[-1])
    except ValueError:
        return None


def extract_operation_year(operation_date: str | None) -> int | None:
    raw = str(operation_date or "").strip()
    if not raw:
        return None
    date_part = raw.split(maxsplit=1)[0].strip()
    parts = date_part.split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def extract_year_from_doc(doc: str | None) -> int | None:
    """Год из хвоста doc: «… от 09.09.2026 15:13:23»."""
    m = DOC_DATE_RE.search(str(doc or ""))
    if not m:
        return None
    try:
        return int(m.group(3))
    except ValueError:
        return None


def extract_row_year(row: dict) -> int | None:
    """Год для ключа дубля: сначала operation_date, иначе дата в doc."""
    year = extract_operation_year(str(row.get("operation_date") or ""))
    if year is not None:
        return year
    return extract_year_from_doc(str(row.get("doc") or ""))


def mutual_settlement_key(row: dict) -> tuple[int, str] | None:
    """Старый ключ (год, order_number) — для совместимости со сводками."""
    order_number = normalize_order_number(row.get("order_number"))
    if not order_number:
        return None
    year = extract_row_year(row)
    if year is None:
        return None
    return year, order_number


def mutual_settlement_doc_year_key(row: dict) -> tuple[int, int] | None:
    """Ключ дубля взаимозачёта: (календарный год, номер документа 00ЦБ-N)."""
    if not is_mutual_settlement_row(row):
        return None
    doc = str(row.get("doc") or "")
    doc_num = extract_doc_number(doc)
    year = extract_row_year(row)
    if doc_num is None or year is None:
        return None
    return year, doc_num


def bonus_doc_sum_key(row: dict) -> tuple[str, float] | None:
    """Ключ дубля для прочих строк bonus_arr: полный doc + сумма."""
    doc = str(row.get("doc") or "").strip()
    if not doc:
        return None
    amount = normalize_bonus_sum(row.get("sum"))
    if amount is None:
        return None
    return doc, amount


def _iter_bonus_rows_from_logs(db: Session):
    logs = (
        db.query(Order1cExchangeLog)
        .filter(Order1cExchangeLog.json_parse_ok.is_(True))
        .order_by(Order1cExchangeLog.created_at.asc(), Order1cExchangeLog.id.asc())
        .all()
    )
    for lg in logs:
        raw = (lg.body_text or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        bonus_arr = payload.get("bonus_arr")
        if not isinstance(bonus_arr, list):
            continue
        for row in bonus_arr:
            if row is None or not isinstance(row, dict):
                continue
            if row.get("_removed_from_debts"):
                continue
            doc = str(row.get("doc") or "").strip()
            amount = normalize_bonus_sum(row.get("sum"))
            is_mutual = is_mutual_settlement_row(row)
            yield {
                "log_id": lg.id,
                "doc": doc,
                "sum": amount,
                "doc_num": extract_doc_number(doc),
                "year": extract_row_year(row),
                "doc_year_key": mutual_settlement_doc_year_key(row) if is_mutual else None,
                "key": mutual_settlement_key(row) if is_mutual else None,
                "is_mutual": is_mutual,
            }


def find_existing_bonus_doc_sums(db: Session) -> set[tuple[str, float]]:
    """Множество уже записанных пар (doc, sum) для не-взаимозачётных строк."""
    existing: set[tuple[str, float]] = set()
    for entry in _iter_bonus_rows_from_logs(db):
        if entry.get("is_mutual"):
            continue
        doc = entry["doc"]
        amount = entry["sum"]
        if doc and amount is not None:
            existing.add((doc, amount))
    return existing


def find_existing_mutual_doc_years(db: Session) -> set[tuple[int, int]]:
    """Уже принятые взаимозачёты: (год, номер документа)."""
    existing: set[tuple[int, int]] = set()
    for entry in _iter_bonus_rows_from_logs(db):
        key = entry.get("doc_year_key")
        if key is not None:
            existing.add(key)
    return existing


def find_existing_mutual_settlements(db: Session) -> tuple[dict[str, dict], dict[tuple[int, str], dict]]:
    """Индексы существующих взаимозачётов: по полному doc и по (год, заказ)."""
    by_doc: dict[str, dict] = {}
    by_order_year: dict[tuple[int, str], dict] = {}
    for entry in _iter_bonus_rows_from_logs(db):
        if not entry.get("is_mutual"):
            continue
        doc = entry["doc"]
        if doc and doc not in by_doc:
            by_doc[doc] = entry
        key = entry["key"]
        if key is None:
            continue
        prev = by_order_year.get(key)
        doc_num = entry["doc_num"]
        if prev is None:
            by_order_year[key] = entry
            continue
        prev_num = prev.get("doc_num")
        if doc_num is not None and (prev_num is None or doc_num < prev_num):
            by_order_year[key] = entry
    return by_doc, by_order_year


def validate_bonus_arr_mutual_settlements(db: Session, payload: dict) -> tuple[bool, str | None, bool]:
    """
    Проверка входящего bonus_arr перед записью лога 1С.

    Взаимозачёт: дубль = тот же номер документа (00ЦБ-N) в том же календарном году.
    Первая запись побеждает; повтор (даже с другой суммой) не пишем и не обновляем.

    Прочие строки bonus_arr: по-прежнему doc + sum.

    Returns:
        ok — можно ли принять запрос;
        error — текст ошибки для 1С;
        skip_persist — не создавать новый лог.
    """
    bonus_arr = payload.get("bonus_arr")
    if not isinstance(bonus_arr, list):
        return True, None, False

    mutual_keys: list[tuple[int, int]] = []
    other_keys: list[tuple[str, float]] = []
    for row in bonus_arr:
        if not isinstance(row, dict):
            continue
        if is_mutual_settlement_row(row):
            key = mutual_settlement_doc_year_key(row)
            if key is not None:
                mutual_keys.append(key)
            continue
        other = bonus_doc_sum_key(row)
        if other is not None:
            other_keys.append(other)

    if not mutual_keys and not other_keys:
        return True, None, False

    if mutual_keys:
        existing_mutual = find_existing_mutual_doc_years(db)
        mutual_all_dup = all(k in existing_mutual for k in mutual_keys)
    else:
        mutual_all_dup = True

    if other_keys:
        existing_other = find_existing_bonus_doc_sums(db)
        other_all_dup = all(k in existing_other for k in other_keys)
    else:
        other_all_dup = True

    # Пропускаем запись только если все проверяемые строки — повторы.
    if mutual_all_dup and other_all_dup and (mutual_keys or other_keys):
        return True, None, True

    return True, None, False


def is_mutual_settlement_entry(entry: dict) -> bool:
    doc = str(entry.get("doc") or "")
    return bool(MUTUAL_SETTLEMENT_DOC_RE.search(doc))


def pick_preferred_mutual_settlement(prev: dict | None, entry: dict) -> dict:
    """Для одного заказа в году оставляем запись с минимальным номером документа."""
    if prev is None:
        return entry
    prev_num = extract_doc_number(str(prev.get("doc") or ""))
    entry_num = extract_doc_number(str(entry.get("doc") or ""))
    if entry_num is None:
        return prev
    if prev_num is None or entry_num < prev_num:
        return entry
    return prev
