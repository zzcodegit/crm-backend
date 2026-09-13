"""
API отчётов консультантов. Отправка отчёта доступна только пользователям из группы «Консультанты».
"""
import json
import re
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from sqlalchemy.orm import joinedload

from database import get_db
from models import (
    CentralCashPayout,
    DailyReport,
    DebtReason,
    EncashmentReceipt,
    ExpenseArticle,
    ManualEmployeeDebt,
    ManualWithholding,
    Order1cExchangeLog,
    TakenReason,
    TakenSource,
    User,
    Warehouse,
    Group,
)
from mutual_settlement_1c import (
    is_mutual_settlement_entry,
    mutual_settlement_dup_key_from_entry,
)
from schemas import (
    AvailableDebtResponse,
    AvailableDebtRow,
    DebtSummaryResponse,
    DebtSummaryRow,
    DebtTakeEventItem,
    DailyReportAdminPatch,
    DailyReportCreate,
    DailyReportResponse,
    ConsultantItem,
    EmployeeLedgerLine,
    EmployeeLedgerResponse,
    EmployeeSalaryBalanceResponse,
    EmployeeSalaryWithholdingItem,
    EncashmentReceiptMarkRequest,
    EncashmentReportItem,
    EncashmentSummaryResponse,
    EncashmentSummaryRow,
    ExpenseDetailRow,
    ExpenseSummaryResponse,
    ExpenseSummaryRow,
    ManualDebtCreate,
    ManualDebtUpdate,
    ManualDebtResponse,
    OneCDebtItemUpdate,
    TakenSummaryResponse,
    TakenSummaryRow,
    WarehouseLastOstResponse,
)
from deps import get_current_user, get_admin_user, get_admin_or_reportnik_user, is_admin, is_manager, is_reportnik
from report_required_validation import (
    ALLOWED_REPORT_REQUIRED_KEYS,
    validate_report_required_fields,
    validate_revenue_breakdown,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])

REPORT_REQUIRED_FIELDS_FILE = Path(__file__).resolve().parent.parent / "logs" / "report_required_fields.json"


def _load_required_report_keys() -> list[str]:
    if not REPORT_REQUIRED_FIELDS_FILE.exists():
        return []
    try:
        raw = json.loads(REPORT_REQUIRED_FIELDS_FILE.read_text(encoding="utf-8"))
        req = raw.get("required", [])
        if not isinstance(req, list):
            return []
        return [x for x in req if isinstance(x, str) and x in ALLOWED_REPORT_REQUIRED_KEYS]
    except Exception:
        return []

CONSULTANTS_GROUP_NAME = "Консультанты"


def _is_consultant(user: User) -> bool:
    return any(g.name == CONSULTANTS_GROUP_NAME for g in user.groups)


def _validate_report_author_user_id(db: Session, user_id: int) -> int:
    """Пользователь-отправитель отчёта должен быть активным и входить в группу «Консультанты»."""
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="Некорректный пользователь")
    user = (
        db.query(User)
        .options(joinedload(User.groups))
        .filter(User.id == user_id)
        .first()
    )
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Пользователь не найден или неактивен")
    group = db.query(Group).filter(Group.name == CONSULTANTS_GROUP_NAME).first()
    if not group:
        raise HTTPException(status_code=500, detail="Группа «Консультанты» не настроена")
    if not any(g.id == group.id for g in user.groups):
        raise HTTPException(
            status_code=400,
            detail="Отчёт можно привязать только к пользователю из группы «Консультанты»",
        )
    return user_id


def _safe_returns_details(raw) -> list[dict]:
    """Из JSONB иногда попадает не list[dict] — иначе DailyReportResponse падает с 500."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _safe_extra_payments_rows(raw) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _safe_vzyala_details_rows(raw) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


# Виртуальная причина «Взято» при зачёте долга (нет в справочнике taken_reasons).
TAKE_DEBT_REASON_VIRTUAL_ID = -999001
TAKE_DEBT_REASON_LABEL = "Забрать долг"
VZYALA_SOURCE_BALANCE = "Баланс"
VZYALA_SOURCE_CASH_REGISTER = "из кассы"


class _VzyalaDisplayContext:
    """Справочники и индекс долгов для подписей в vzyala_details."""

    __slots__ = ("taken_reason_by_id", "taken_source_by_id", "debt_by_uid")

    def __init__(
        self,
        taken_reason_by_id: dict[int, str],
        taken_source_by_id: dict[int, str],
        debt_by_uid: dict[str, dict],
    ):
        self.taken_reason_by_id = taken_reason_by_id
        self.taken_source_by_id = taken_source_by_id
        self.debt_by_uid = debt_by_uid


def _load_vzyala_display_context(
    db: Session,
    *,
    only_debt_uids: set[str] | None = None,
) -> _VzyalaDisplayContext:
    """Индекс долгов для подписей «Взято».

    only_debt_uids: если задан — индексируем только эти uid (ускорение сводки «Взято»).
    """
    taken_reason_by_id = {x.id: x.name for x in db.query(TakenReason).all()}
    taken_reason_by_id[TAKE_DEBT_REASON_VIRTUAL_ID] = TAKE_DEBT_REASON_LABEL
    taken_source_by_id = {x.id: x.name for x in db.query(TakenSource).all()}
    debt_reason_by_id = {x.id: x.name for x in db.query(DebtReason).all()}
    warehouse_by_id = {x.id: x.name for x in db.query(Warehouse).all()}
    debt_by_uid: dict[str, dict] = {}
    want = only_debt_uids

    def _put_debt(uid: str, **fields) -> None:
        if not uid:
            return
        if want is not None and uid not in want:
            return
        prev = debt_by_uid.get(uid, {})
        merged = {**prev, **{k: v for k, v in fields.items() if v is not None and v != ""}}
        debt_by_uid[uid] = merged

    reports = (
        db.query(
            DailyReport.id,
            DailyReport.warehouse_id,
            DailyReport.dolg_details,
            DailyReport.submitted_at,
            DailyReport.created_at,
        )
        .filter(DailyReport.is_draft.is_(False))
        .all()
    )
    for report in reports:
        for row in _safe_dolg_details_rows(report.dolg_details):
            uid = str(row.get("debt_row_uid") or "").strip()
            if not uid:
                continue
            drid = row.get("debt_reason_id") if isinstance(row.get("debt_reason_id"), int) else None
            row_wh_id = row.get("warehouse_id") if isinstance(row.get("warehouse_id"), int) else None
            wh_id = row_wh_id if row_wh_id is not None else report.warehouse_id
            wh_name = warehouse_by_id.get(wh_id) if wh_id is not None else None
            _put_debt(
                uid,
                debt_origin="report",
                debt_reason_name=debt_reason_by_id.get(drid) if drid is not None else None,
                order_number=str(row.get("order_number") or ""),
                debt_report_id=report.id,
                debt_date=_debt_date_display(
                    str(row.get("report_month")).strip() if row.get("report_month") is not None else None,
                    report.submitted_at,
                    report.created_at,
                ),
                warehouse_id=wh_id,
                warehouse_name=wh_name,
            )

    for m in (
        db.query(ManualEmployeeDebt)
        .options(joinedload(ManualEmployeeDebt.warehouse))
        .all()
    ):
        uid = str(m.debt_row_uid or "").strip()
        if not uid:
            continue
        drn = debt_reason_by_id.get(m.debt_reason_id) if m.debt_reason_id is not None else None
        m_wh_id = m.warehouse_id
        m_wh_name = m.warehouse.name if getattr(m, "warehouse", None) else warehouse_by_id.get(m_wh_id) if m_wh_id else None
        _put_debt(
            uid,
            debt_origin="manual",
            debt_reason_name=drn,
            order_number=str(m.order_number or ""),
            debt_report_id=0,
            admin_note=(m.note or "").strip() or None,
            debt_date=_debt_date_display(
                str(m.report_month).strip() if m.report_month is not None else None,
                m.created_at,
                m.created_at,
            ),
            warehouse_id=m_wh_id,
            warehouse_name=m_wh_name,
        )

    if want is None:
        for entry in _collect_one_c_bonus_debts(db):
            uid = str(entry["uid"])
            label = str(entry.get("record_type_label") or "").strip()
            _put_debt(
                uid,
                debt_origin="1c",
                debt_reason_name=(f"1С: {label}" if label else "1С"),
                order_number=str(entry.get("order_number") or ""),
                doc=str(entry.get("doc") or "").strip() or None,
                comment=str(entry.get("comment") or "").strip() or None,
                record_type=label or None,
                debt_report_id=0,
                debt_date=_debt_date_display(
                    str(entry.get("operation_date")).strip() if entry.get("operation_date") else None,
                    entry.get("log_created_at"),
                    entry.get("log_created_at"),
                ),
                warehouse_id=entry.get("warehouse_id"),
                warehouse_name=entry.get("warehouse_name"),
            )
    else:
        # Только нужные строки 1С по uid вида 1c-log-{log_id}-{index} — без полного скана логов.
        needed_by_log: dict[int, set[int]] = defaultdict(set)
        for uid in want:
            m = _ONE_C_DEBT_UID_RE.match(uid)
            if not m:
                continue
            needed_by_log[int(m.group(1))].add(int(m.group(2)))
        if needed_by_log:
            log_ids = list(needed_by_log.keys())
            # чанками — IN слишком большого списка тяжелее для планировщика
            chunk = 500
            for off in range(0, len(log_ids), chunk):
                part = log_ids[off : off + chunk]
                logs = db.query(Order1cExchangeLog).filter(Order1cExchangeLog.id.in_(part)).all()
                for lg in logs:
                    idxs = needed_by_log.get(lg.id) or set()
                    raw = (lg.body_text or "").strip()
                    if not raw or not idxs:
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
                    for i in idxs:
                        if i < 0 or i >= len(bonus_arr):
                            continue
                        row = bonus_arr[i]
                        if not isinstance(row, dict) or row.get("_removed_from_debts"):
                            continue
                        uid = f"1c-log-{lg.id}-{i}"
                        record_type = str(row.get("record_type") or "").strip()
                        label = "Процент" if record_type.upper() == "ОРП" else record_type
                        op_date = _format_one_c_operation_date(str(row.get("operation_date") or ""))
                        _put_debt(
                            uid,
                            debt_origin="1c",
                            debt_reason_name=(f"1С: {label}" if label else "1С"),
                            order_number=str(row.get("order_number") or "").strip(),
                            doc=str(row.get("doc") or "").strip() or None,
                            comment=str(row.get("comment") or "").strip() or None,
                            record_type=label or None,
                            debt_report_id=0,
                            debt_date=_debt_date_display(op_date, lg.created_at, lg.created_at),
                        )

    return _VzyalaDisplayContext(taken_reason_by_id, taken_source_by_id, debt_by_uid)


def _vzyala_row_amount(row: dict) -> float:
    raw = row.get("amount")
    try:
        amt = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    return amt if amt > DEBT_AMOUNT_EPS else 0.0


def _resolve_vzyala_taken_source_name(
    row: dict,
    ctx: _VzyalaDisplayContext,
    cc_pool_remaining: list[float],
) -> str | None:
    """«Откуда взято»: справочник или Баланс / из кассы (FIFO по остатку ЦК до отчёта)."""
    tsid = row.get("taken_source_id") if isinstance(row.get("taken_source_id"), int) else None
    explicit = ctx.taken_source_by_id.get(tsid) if tsid is not None else None

    amt = _vzyala_row_amount(row)
    from_pool: str | None = None
    if amt > DEBT_AMOUNT_EPS:
        pool = cc_pool_remaining[0]
        if pool >= amt - DEBT_AMOUNT_EPS:
            from_pool = VZYALA_SOURCE_BALANCE
        else:
            from_pool = VZYALA_SOURCE_CASH_REGISTER
        cc_pool_remaining[0] = pool - amt

    if explicit:
        return explicit
    return from_pool


def _linked_debt_source_label(
    linked_uid: str,
    debt: dict,
    *,
    linked_report_id: int | None,
) -> tuple[str | None, str | None]:
    """Подпись документа долга для колонки «Источник»: (label, kind)."""
    if not linked_uid:
        return None, None
    origin = str(debt.get("debt_origin") or "").strip()
    if not origin:
        if linked_uid.startswith("1c-log-"):
            origin = "1c"
        elif int(debt.get("debt_report_id") or 0) > 0:
            origin = "report"
        else:
            origin = "manual"

    parts: list[str] = []
    if origin == "1c":
        doc = str(debt.get("doc") or "").strip()
        if doc:
            parts.append(doc)
        else:
            parts.append(str(debt.get("debt_reason_name") or "1С").strip() or "1С")
        rt = str(debt.get("record_type") or "").strip()
        if rt and rt not in (parts[0] if parts else ""):
            parts.append(f"тип: {rt}")
        onum = str(debt.get("order_number") or "").strip()
        if onum:
            parts.append(f"заказ {onum}")
        comment = str(debt.get("comment") or "").strip()
        if comment:
            parts.append(comment)
        return " · ".join(parts), "1c"

    if origin == "report":
        rid = linked_report_id or debt.get("debt_report_id")
        head = f"Отчёт #{rid}" if rid else "Отчёт"
        parts.append(head)
        drn = str(debt.get("debt_reason_name") or "").strip()
        if drn:
            parts.append(drn)
        onum = str(debt.get("order_number") or "").strip()
        if onum:
            parts.append(f"заказ {onum}")
        return " · ".join(parts), "report"

    # manual
    parts.append("Ручной долг")
    drn = str(debt.get("debt_reason_name") or "").strip()
    if drn:
        parts.append(drn)
    note = str(debt.get("admin_note") or "").strip()
    if note:
        parts.append(note)
    onum = str(debt.get("order_number") or "").strip()
    if onum:
        parts.append(f"заказ {onum}")
    return " · ".join(parts), "manual"


def _enrich_vzyala_details_rows(
    rows: list[dict],
    ctx: _VzyalaDisplayContext | None,
    *,
    db: Session | None = None,
    report: DailyReport | None = None,
) -> list[dict]:
    if not rows or ctx is None:
        return rows
    cc_pool_remaining = [0.0]
    if db is not None and report is not None:
        cc_pool_remaining[0] = max(
            0.0,
            _employee_salary_balance(db, report.user_id, exclude_report_id=report.id).balance,
        )

    out: list[dict] = []
    for row in rows:
        r = dict(row)
        linked = str(r.get("linked_debt_row_uid") or "").strip()
        trid = r.get("taken_reason_id") if isinstance(r.get("taken_reason_id"), int) else None

        if linked:
            debt = ctx.debt_by_uid.get(linked, {})
            drn = (debt.get("debt_reason_name") or "").strip()
            r["taken_reason_name"] = drn or TAKE_DEBT_REASON_LABEL
            debt_date = (debt.get("debt_date") or "").strip()
            if debt_date:
                r["linked_debt_date"] = debt_date
            if r.get("warehouse_id") is None and debt.get("warehouse_id") is not None:
                r["warehouse_id"] = debt["warehouse_id"]
            if not str(r.get("warehouse_name") or "").strip() and debt.get("warehouse_name"):
                r["warehouse_name"] = debt["warehouse_name"]
        else:
            if trid == TAKE_DEBT_REASON_VIRTUAL_ID:
                r["taken_reason_name"] = TAKE_DEBT_REASON_LABEL
            elif trid is not None:
                r["taken_reason_name"] = ctx.taken_reason_by_id.get(trid)

        src_name = _resolve_vzyala_taken_source_name(r, ctx, cc_pool_remaining)
        if src_name:
            r["taken_source_name"] = src_name
        out.append(r)
    return out


def _safe_dolg_details_rows(raw) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _is_debt_row_admin_closed(row: dict) -> bool:
    """Долг закрыт администратором в сводке (не из 1С) — не показывать в активных долгах."""
    if row.get("admin_closed") in (True, "true", 1, "1"):
        return True
    return bool(str(row.get("closed_at") or "").strip())


def _find_report_dolg_row_by_uid(db: Session, debt_row_uid: str) -> tuple[DailyReport, list[dict], int]:
    uid = str(debt_row_uid or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Не указан идентификатор долга")
    reports = (
        db.query(DailyReport)
        .filter(DailyReport.is_draft.is_(False))
        .order_by(DailyReport.id.desc())
        .all()
    )
    for report in reports:
        rows = _safe_dolg_details_rows(getattr(report, "dolg_details", None))
        for idx, row in enumerate(rows):
            if str(row.get("debt_row_uid") or "").strip() == uid:
                return report, rows, idx
    raise HTTPException(status_code=404, detail="Строка долга в отчётах не найдена")


DEBT_AMOUNT_EPS = 1e-6
_ONE_C_DEBT_UID_RE = re.compile(r"^1c-log-(\d+)-(\d+)$")


def _normalize_person_name(s: str | None) -> str:
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.strip().split())


def _format_one_c_operation_date(s: str | None) -> str | None:
    """Из даты 1С вида «20.05.2026 0:00:00» оставляет только «20.05.2026»."""
    raw = (s or "").strip()
    if not raw:
        return None
    if " " in raw:
        raw = raw.split(maxsplit=1)[0].strip()
    return raw or None


def _debt_date_display(
    report_month: str | None,
    submitted_at: datetime | None,
    created_at: datetime | None,
) -> str | None:
    """Дата возникновения долга для детализации «Взято»."""
    rm = (report_month or "").strip()
    if rm:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", rm):
            try:
                d = date_type.fromisoformat(rm)
                return d.strftime("%d.%m.%Y")
            except ValueError:
                pass
        one_c = _format_one_c_operation_date(rm)
        if one_c:
            return one_c
        return rm
    ts = submitted_at or created_at
    if ts is not None:
        try:
            return ts.astimezone(timezone.utc).strftime("%d.%m.%Y") if ts.tzinfo else ts.strftime("%d.%m.%Y")
        except (AttributeError, ValueError):
            return str(ts)[:10]
    return None


def _consultant_fio_variants(u: User) -> list[str]:
    parts = [(u.last_name or "").strip(), (u.first_name or "").strip(), (u.patronymic or "").strip()]
    non_empty = [p for p in parts if p]
    variants: list[str] = []
    if non_empty:
        variants.append(_normalize_person_name(" ".join(non_empty)))
        if len(non_empty) >= 2:
            variants.append(_normalize_person_name(f"{non_empty[1]} {non_empty[0]}"))
            variants.append(_normalize_person_name(f"{non_empty[0]} {non_empty[1]}"))
    username = _normalize_person_name(u.username or "")
    if username:
        variants.append(username)
    return variants


def _build_consultant_name_index(db: Session) -> dict[str, int]:
    """Ключ — нормализованное ФИО (нижний регистр), значение — user_id консультанта."""
    index: dict[str, int] = {}
    group = db.query(Group).filter(Group.name == CONSULTANTS_GROUP_NAME).first()
    if not group:
        return index
    users = (
        db.query(User)
        .join(User.groups)
        .filter(Group.id == group.id, User.is_active.is_(True))
        .all()
    )
    for u in users:
        for variant in _consultant_fio_variants(u):
            key = variant.lower()
            if key:
                index[key] = u.id
    return index


def _find_consultant_user_id_by_name(
    consultant_name: str | None,
    consultant_index: dict[str, int],
) -> int | None:
    n = _normalize_person_name(consultant_name)
    if not n:
        return None
    return consultant_index.get(n.lower())


def _find_warehouse_id_by_trade_point_name(db: Session, trade_point: str | None) -> int | None:
    tp = _normalize_person_name(trade_point)
    if not tp:
        return None
    tp_lower = tp.lower()
    for wh in db.query(Warehouse).all():
        name = _normalize_person_name(wh.name)
        if not name:
            continue
        nl = name.lower()
        if nl == tp_lower or nl in tp_lower or tp_lower in nl:
            return wh.id
    return None


def _match_warehouse_id_by_trade_point(trade_point: str | None, warehouses: list[Warehouse]) -> int | None:
    tp = _normalize_person_name(trade_point)
    if not tp:
        return None
    tp_lower = tp.lower()
    for wh in warehouses:
        name = _normalize_person_name(wh.name)
        if not name:
            continue
        nl = name.lower()
        if nl == tp_lower or nl in tp_lower or tp_lower in nl:
            return wh.id
    return None


def _parse_one_c_debt_uid(uid: str) -> tuple[int, int] | None:
    m = _ONE_C_DEBT_UID_RE.match(str(uid).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _one_c_bonus_amount_from_log(db: Session, log_id: int, index: int) -> float | None:
    lg = db.query(Order1cExchangeLog).filter(Order1cExchangeLog.id == log_id).first()
    if not lg or not lg.json_parse_ok:
        return None
    raw = (lg.body_text or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    bonus_arr = payload.get("bonus_arr")
    if not isinstance(bonus_arr, list) or index < 0 or index >= len(bonus_arr):
        return None
    row = bonus_arr[index]
    if not isinstance(row, dict):
        return None
    raw_sum = row.get("sum")
    try:
        amount = float(raw_sum) if raw_sum is not None else None
    except (TypeError, ValueError):
        amount = None
    if amount is None or amount <= DEBT_AMOUNT_EPS:
        return None
    return amount


def _collect_one_c_bonus_debts(db: Session, *, for_user_id: int | None = None) -> list[dict]:
    """Все строки bonus_arr из успешных логов 1С, пригодные как долги к зачёту."""
    warehouses = db.query(Warehouse).all()
    warehouse_by_id = {x.id: x.name for x in warehouses}
    user_by_id = {x.id: x.username for x in db.query(User).all()}
    consultant_index = _build_consultant_name_index(db)
    out: list[dict] = []
    one_c_logs = (
        db.query(Order1cExchangeLog)
        .filter(Order1cExchangeLog.json_parse_ok.is_(True))
        .order_by(Order1cExchangeLog.created_at.asc(), Order1cExchangeLog.id.asc())
        .all()
    )
    for lg in one_c_logs:
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
        for i, row in enumerate(bonus_arr):
            if row is None or not isinstance(row, dict):
                continue
            if row.get("_removed_from_debts"):
                continue
            raw_sum = row.get("sum")
            try:
                amount = float(raw_sum) if raw_sum is not None else None
            except (TypeError, ValueError):
                amount = None
            if amount is None or amount <= DEBT_AMOUNT_EPS:
                continue
            consultant_name = str(row.get("consultant") or "").strip()
            user_id = _find_consultant_user_id_by_name(consultant_name, consultant_index) or 0
            if for_user_id is not None and user_id != for_user_id:
                continue
            record_type = str(row.get("record_type") or "").strip()
            record_type_label = "Процент" if record_type.upper() == "ОРП" else record_type
            trade_point = str(row.get("trade_point") or "").strip()
            wh_id = _match_warehouse_id_by_trade_point(trade_point, warehouses)
            out.append(
                {
                    "uid": f"1c-log-{lg.id}-{i}",
                    "log_id": lg.id,
                    "log_created_at": lg.created_at,
                    "amount": amount,
                    "user_id": user_id,
                    "user_name": user_by_id.get(user_id, consultant_name or "1С") if user_id else (consultant_name or "1С"),
                    "consultant": consultant_name,
                    "record_type": record_type,
                    "record_type_label": record_type_label,
                    "trade_point": trade_point,
                    "order_number": str(row.get("order_number") or "").strip(),
                    "operation_date": _format_one_c_operation_date(str(row.get("operation_date") or "")) or "",
                    "doc": str(row.get("doc") or "").strip(),
                    "comment": str(row.get("comment") or "").strip(),
                    "warehouse_id": wh_id,
                    "warehouse_name": warehouse_by_id.get(wh_id) if wh_id else (trade_point or None),
                }
            )
    if not out:
        return out
    # Одна и та же смена/документ/мотивация может прийти из 1С повторно.
    # Взаимозачёт: тип + год + номер 00ЦБ-N + консультант — оставляем ПЕРВУЮ запись.
    # Два консультанта на одном документе — обе строки остаются.
    # Прочее: ключ user+doc+comment+type+sum — оставляем последнюю.
    best_by_key: dict[tuple, dict] = {}
    for entry in out:
        doc_key = str(entry.get("doc") or "").strip()
        if is_mutual_settlement_entry(entry):
            mkey = mutual_settlement_dup_key_from_entry(entry)
            if mkey is not None:
                dedupe_key: tuple = ("mutual",) + mkey
                prev = best_by_key.get(dedupe_key)
                # первая по времени лога
                if prev is None or (entry.get("log_created_at") or datetime.max.replace(tzinfo=timezone.utc)) < (
                    prev.get("log_created_at") or datetime.max.replace(tzinfo=timezone.utc)
                ):
                    best_by_key[dedupe_key] = entry
                continue
        comment_key = str(entry.get("comment") or "").strip()
        dedupe_key = (
            int(entry.get("user_id") or 0),
            doc_key,
            comment_key,
            str(entry.get("record_type_label") or "").strip(),
            round(float(entry["amount"]), 2),
        )
        prev = best_by_key.get(dedupe_key)
        if prev is None or (entry.get("log_created_at") or datetime.min.replace(tzinfo=timezone.utc)) >= (
            prev.get("log_created_at") or datetime.min.replace(tzinfo=timezone.utc)
        ):
            best_by_key[dedupe_key] = entry
    return list(best_by_key.values())


def _one_c_entry_admin_note(entry: dict) -> str | None:
    """Текст для UI: doc и/или comment из bonus_arr (мотивация и т.п.)."""
    parts: list[str] = []
    doc = str(entry.get("doc") or "").strip()
    comment = str(entry.get("comment") or "").strip()
    if doc:
        parts.append(doc)
    if comment:
        parts.append(comment)
    return "\n".join(parts) if parts else None


class ManualWithholdingCreate(BaseModel):
    user_id: int
    amount: float = Field(gt=0)
    warehouse_id: int | None = None
    report_month: str | None = None
    reason: str | None = None
    note: str | None = None


class ManualDebtWithholdBody(BaseModel):
    """Удержание по ручной записи долга: создаёт ManualWithholding (погашается в блоке отчёта)."""

    amount: float | None = Field(default=None, gt=0, description="По умолчанию — остаток долга")
    reason: str | None = None
    note: str | None = None


class ManualWithholdingUpdate(BaseModel):
    """Частичное обновление ручного удержания (админ)."""

    user_id: int | None = None
    amount: float | None = Field(default=None, gt=0)
    warehouse_id: int | None = None
    report_month: str | None = None
    reason: str | None = None
    note: str | None = None


class ManualWithholdingItem(BaseModel):
    id: int
    created_at: datetime | None = None
    user_id: int
    user_name: str
    amount: float
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    report_month: str | None = None
    reason: str | None = None
    note: str | None = None
    recorded_by_user_id: int | None = None
    recorded_by_name: str | None = None
    closed: bool = False
    closed_at: datetime | None = None
    closed_by_user_id: int | None = None
    closed_by_name: str | None = None


class ManualWithholdingResponse(BaseModel):
    rows: list[ManualWithholdingItem]


def _build_taken_amounts_by_debt_uid(
    db: Session,
    exclude_report_id: int | None = None,
) -> dict[str, float]:
    """Суммы «Взято» по linked_debt_row_uid — один проход по отправленным отчётам."""
    totals: dict[str, float] = {}
    reports = db.query(DailyReport).filter(DailyReport.is_draft.is_(False)).all()
    for report in reports:
        if exclude_report_id is not None and report.id == exclude_report_id:
            continue
        for row in _safe_vzyala_details_rows(getattr(report, "vzyala_details", None)):
            uid = str(row.get("linked_debt_row_uid") or "").strip()
            if not uid:
                continue
            raw = row.get("amount")
            try:
                amt = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                amt = None
            if amt is not None and amt > 0:
                totals[uid] = totals.get(uid, 0.0) + amt
    return totals


def _sum_taken_amounts_for_debt_uid(
    db: Session,
    debt_uid: str,
    exclude_report_id: int | None = None,
    taken_by_uid: dict[str, float] | None = None,
) -> float:
    """Сумма «Взято» по linked_debt_row_uid по всем отправленным отчётам (опционально без одного отчёта — при редактировании)."""
    uid = str(debt_uid).strip()
    if not uid:
        return 0.0
    if taken_by_uid is not None:
        return taken_by_uid.get(uid, 0.0)
    return _build_taken_amounts_by_debt_uid(db, exclude_report_id).get(uid, 0.0)


def _dolg_original_amount_from_reports(db: Session, debt_uid: str) -> float | None:
    """Сумма строки долга в dolg_details отчёта по debt_row_uid."""
    uid = str(debt_uid).strip()
    if not uid:
        return None
    reports = db.query(DailyReport).filter(DailyReport.is_draft.is_(False)).all()
    for report in reports:
        for row in _safe_dolg_details_rows(getattr(report, "dolg_details", None)):
            if str(row.get("debt_row_uid") or "").strip() != uid:
                continue
            raw = row.get("amount")
            try:
                return float(raw) if raw is not None else None
            except (TypeError, ValueError):
                return None
    return None


def _debt_original_amount_for_uid(db: Session, debt_uid: str) -> float | None:
    """Оригинальная сумма долга: из отчёта, ручной записи или строки bonus_arr из 1С."""
    v = _dolg_original_amount_from_reports(db, debt_uid)
    if v is not None:
        return v
    md = db.query(ManualEmployeeDebt).filter(ManualEmployeeDebt.debt_row_uid == str(debt_uid).strip()).first()
    if md is not None and md.amount is not None:
        return float(md.amount)
    parsed = _parse_one_c_debt_uid(debt_uid)
    if parsed is not None:
        return _one_c_bonus_amount_from_log(db, parsed[0], parsed[1])
    return None


def _validate_vzyala_linked_debts(
    db: Session,
    data: DailyReportCreate,
    exclude_report_id: int | None,
) -> None:
    """Частичное погашение: сумма по linked_debt_row_uid не больше остатка долга."""
    if not data.vzyala_details:
        return
    for item in data.vzyala_details:
        row = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        linked = str(row.get("linked_debt_row_uid") or "").strip()
        if not linked:
            continue
        raw_amt = row.get("amount")
        try:
            amt = float(raw_amt) if raw_amt is not None else None
        except (TypeError, ValueError):
            amt = None
        if amt is None or amt <= DEBT_AMOUNT_EPS:
            raise HTTPException(
                status_code=400,
                detail="Укажите сумму больше нуля в строке «Забрать долг».",
            )
        original = _debt_original_amount_for_uid(db, linked)
        if original is None:
            raise HTTPException(status_code=400, detail=f"Строка долга не найдена (uid: {linked})")
        taken_others = _sum_taken_amounts_for_debt_uid(db, linked, exclude_report_id)
        max_allowed = original - taken_others
        if amt > max_allowed + 1e-4:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"По этому долгу можно зачесть не больше {max_allowed:.2f} "
                    f"(из {original:.2f} всего; уже зачтено {original - max_allowed:.2f}). Указано: {amt:.2f}."
                ),
            )


def _sum_vzyala_amount_from_data(data: DailyReportCreate) -> float:
    if data.vzyala_details:
        total = 0.0
        for item in data.vzyala_details:
            try:
                amt = float(item.amount)
            except (TypeError, ValueError):
                continue
            if amt > DEBT_AMOUNT_EPS:
                total += amt
        return total
    if data.vzyala is not None:
        try:
            v = float(data.vzyala)
            return v if v > DEBT_AMOUNT_EPS else 0.0
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _taken_source_name_is_cash_from_register(name: str | None) -> bool:
    n = (name or "").strip().lower()
    return "налич" in n and "касс" in n


def _taken_source_is_cash_from_register(db: Session, taken_source_id: int | None) -> bool:
    if taken_source_id is None:
        return False
    src = db.query(TakenSource).filter(TakenSource.id == taken_source_id).first()
    return _taken_source_name_is_cash_from_register(src.name if src else None)


def _expenses_from_cash_register_sum(db: Session, data: DailyReportCreate) -> float:
    if not data.has_expenses or not data.expenses:
        return 0.0
    total = 0.0
    for item in data.expenses:
        ts_id = getattr(item, "taken_source_id", None)
        if not _taken_source_is_cash_from_register(db, ts_id):
            continue
        try:
            total += float(item.amount)
        except (TypeError, ValueError):
            continue
    return total


def _sum_withholding_applied_from_data(data: DailyReportCreate) -> float:
    """Сумма погашений удержаний в отчёте — увеличивает наличные в кассе точки."""
    total = 0.0
    for item in getattr(data, "withholding_details", None) or []:
        try:
            amt = float(getattr(item, "amount", None) if not isinstance(item, dict) else item.get("amount"))
        except (TypeError, ValueError):
            continue
        if amt is None or amt <= DEBT_AMOUNT_EPS:
            continue
        total += amt
    return round(total, 2)


def _withholding_applied_map(raw) -> dict[int, float]:
    out: dict[int, float] = {}
    if not raw:
        return out
    rows = raw if isinstance(raw, list) else []
    for item in rows:
        if isinstance(item, dict):
            wid = item.get("withholding_id")
            amt_raw = item.get("amount")
        else:
            wid = getattr(item, "withholding_id", None)
            amt_raw = getattr(item, "amount", None)
        try:
            wid_i = int(wid)
            amt = float(amt_raw)
        except (TypeError, ValueError):
            continue
        if wid_i <= 0 or amt <= DEBT_AMOUNT_EPS:
            continue
        out[wid_i] = round(out.get(wid_i, 0.0) + amt, 2)
    return out


def _cash_base_before_vzyala(data: DailyReportCreate, db: Session | None = None) -> float:
    """Касса до забора «Взято» из наличных (сверх выплат ЦК), с учётом погашенных удержаний."""
    u = float(data.utro or 0)
    n = float(data.nal or 0)
    ret = float(data.return_nal or 0) if data.has_returns else 0.0
    enc_nal = float(data.encashment_nal or 0) if data.has_encashment else 0.0
    exp_sum = _expenses_from_cash_register_sum(db, data) if db is not None else 0.0
    wh_sum = _sum_withholding_applied_from_data(data)
    return round(u + n - ret - enc_nal - exp_sum + wh_sum, 2)


def _vzyala_amount_for_report(report: DailyReport) -> float:
    """Сумма блока «Взято» в одном отправленном отчёте."""
    rows = _safe_vzyala_details_rows(getattr(report, "vzyala_details", None))
    if rows:
        total = 0.0
        for row in rows:
            raw = row.get("amount")
            try:
                amt = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                amt = None
            if amt is None or amt <= DEBT_AMOUNT_EPS:
                continue
            total += amt
        return total
    try:
        legacy = float(report.vzyala) if report.vzyala is not None else None
    except (TypeError, ValueError):
        legacy = None
    if legacy is not None and legacy > DEBT_AMOUNT_EPS:
        return legacy
    return 0.0


def _vzyala_from_cash_register(
    db: Session,
    user_id: int,
    data: DailyReportCreate,
    *,
    exclude_report_id: int | None = None,
) -> float:
    total = _sum_vzyala_amount_from_data(data)
    if total <= DEBT_AMOUNT_EPS:
        return 0.0
    bal = _employee_salary_balance(db, user_id, exclude_report_id=exclude_report_id)
    available_cc = max(0.0, float(bal.balance))
    return max(0.0, round(total - available_cc, 2))


def _apply_withholding_details_delta(
    db: Session,
    user_id: int,
    new_details,
    prev_details,
    *,
    closed_by_user_id: int | None,
    report_id: int | None = None,
) -> None:
    """
    Применяем погашения удержаний из отчёта (дельта относительно предыдущих значений отчёта).
    Полностью погашенные закрываются; частичные уменьшают остаток amount.
    """
    new_map = _withholding_applied_map(new_details)
    prev_map = _withholding_applied_map(prev_details)
    all_ids = set(new_map) | set(prev_map)
    if not all_ids:
        return
    now = datetime.now(timezone.utc)
    note_base = f"Погашено отчётом #{report_id}" if report_id else "Погашено в отчёте"
    for wid in sorted(all_ids):
        new_amt = float(new_map.get(wid, 0.0))
        prev_amt = float(prev_map.get(wid, 0.0))
        delta = round(new_amt - prev_amt, 2)
        if abs(delta) <= DEBT_AMOUNT_EPS:
            continue
        row = (
            db.query(ManualWithholding)
            .filter(ManualWithholding.id == wid, ManualWithholding.user_id == user_id)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=400, detail=f"Удержание #{wid} не найдено")
        current_open = 0.0 if bool(row.closed) else float(row.amount or 0)
        if delta > DEBT_AMOUNT_EPS and delta > current_open + DEBT_AMOUNT_EPS:
            raise HTTPException(
                status_code=400,
                detail=f"По удержанию #{wid} можно отметить не больше {current_open:.2f} ₽",
            )
        new_open = round(current_open - delta, 2)
        prev_note = (row.note or "").strip()
        if new_open <= DEBT_AMOUNT_EPS:
            row.closed = True
            row.closed_at = now
            row.closed_by_user_id = closed_by_user_id
            if row.amount is None or float(row.amount or 0) <= DEBT_AMOUNT_EPS:
                # сохраняем отображаемую сумму закрытого удержания
                try:
                    row.amount = round(float(row.amount or 0) + current_open, 2) if current_open > DEBT_AMOUNT_EPS else row.amount
                except (TypeError, ValueError):
                    pass
            note_extra = note_base if new_amt > DEBT_AMOUNT_EPS else f"Корректировка: {note_base}"
            if note_extra not in prev_note:
                row.note = f"{prev_note} · {note_extra}".strip(" ·") if prev_note else note_extra
        else:
            row.closed = False
            row.closed_at = None
            row.closed_by_user_id = None
            row.amount = new_open
            note_extra = f"{note_base} (−{new_amt:.2f} ₽)" if new_amt > DEBT_AMOUNT_EPS else note_base
            if note_extra not in prev_note:
                row.note = f"{prev_note} · {note_extra}".strip(" ·") if prev_note else note_extra


def _computed_report_ost(
    data: DailyReportCreate,
    *,
    db: Session | None = None,
    user_id: int | None = None,
    exclude_report_id: int | None = None,
) -> float:
    """Расчётный остаток наличных в кассе (как в форме отчёта): база минус забор из кассы в «Взято»."""
    base = _cash_base_before_vzyala(data, db)
    from_cash = 0.0
    if db is not None and user_id is not None:
        from_cash = _vzyala_from_cash_register(db, user_id, data, exclude_report_id=exclude_report_id)
    elif data.ost is not None:
        try:
            return float(data.ost)
        except (TypeError, ValueError):
            pass
    return round(base - from_cash, 2)


def _validate_vzyala_cash_against_ost(
    db: Session,
    user_id: int,
    data: DailyReportCreate,
    *,
    exclude_report_id: int | None = None,
) -> None:
    """
    Сумма «Взято» сверх выплат из ЦК физически берётся из кассы точки и не может
    превышать наличные до этого забора.
    """
    total = _sum_vzyala_amount_from_data(data)
    if total <= DEBT_AMOUNT_EPS:
        return
    from_cash = _vzyala_from_cash_register(db, user_id, data, exclude_report_id=exclude_report_id)
    if from_cash <= DEBT_AMOUNT_EPS:
        return
    cash_before = _cash_base_before_vzyala(data, db)
    if from_cash > cash_before + 1e-4:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Из кассы точки можно взять не больше {cash_before:.2f} ₽. "
                "Уменьшите сумму или частично зачтите долг в другом отчёте."
            ),
        )


def _safe_expenses_rows(raw) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _safe_str_list(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [str(x) for x in raw if x is not None and str(x) != ""]
    return []


def _normalize_extra_payment_rows(rows: list | None) -> list[dict]:
    """Приводит элементы extra_payments к единому полю consultant_last_name (ФИО могло лежать под разными ключами)."""
    if not rows:
        return []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = dict(row)
        name: str | None = None
        for key in (
            "consultant_last_name",
            "consultantLastName",
            "consultant_name",
            "consultantName",
            "seller_fio",
            "seller_name",
            "fio",
            "consultant",
        ):
            val = d.get(key)
            if isinstance(val, str) and val.strip():
                name = val.strip()
                break
        if name:
            d["consultant_last_name"] = name
        out.append(d)
    return out



def _safe_withholding_details_rows(raw) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            wid = int(item.get("withholding_id"))
            amt = float(item.get("amount"))
        except (TypeError, ValueError):
            continue
        if wid <= 0 or amt <= DEBT_AMOUNT_EPS:
            continue
        out.append({"withholding_id": wid, "amount": round(amt, 2)})
    return out


def _report_to_response(
    r: DailyReport,
    warehouse_name: str = "",
    user_username: str = "",
    vzyala_display_ctx: _VzyalaDisplayContext | None = None,
    db: Session | None = None,
) -> DailyReportResponse:
    if not warehouse_name and hasattr(r, "warehouse") and r.warehouse:
        warehouse_name = r.warehouse.name
    if not user_username and hasattr(r, "user") and r.user:
        user_username = r.user.username
    vzyala_details = _enrich_vzyala_details_rows(
        _safe_vzyala_details_rows(getattr(r, "vzyala_details", None)),
        vzyala_display_ctx,
        db=db,
        report=r,
    )
    return DailyReportResponse(
        id=r.id,
        created_at=r.created_at,
        submitted_at=getattr(r, "submitted_at", None),
        user_id=r.user_id,
        user_username=user_username,
        warehouse_id=r.warehouse_id,
        warehouse_name=warehouse_name,
        utro=float(r.utro) if r.utro is not None else None,
        revenue=float(r.revenue) if r.revenue is not None else None,
        nal=float(r.nal) if r.nal is not None else None,
        bn=float(r.bn) if r.bn is not None else None,
        ost=float(r.ost) if r.ost is not None else None,
        ost_fact=float(r.ost_fact) if getattr(r, "ost_fact", None) is not None else None,
        is_draft=bool(getattr(r, "is_draft", False)),
        has_returns=r.has_returns or False,
        return_bn=float(r.return_bn) if r.return_bn is not None else None,
        return_nal=float(r.return_nal) if r.return_nal is not None else None,
        returns_details=_safe_returns_details(getattr(r, "returns_details", None)),
        bn_card_reconciliation=float(r.bn_card_reconciliation) if r.bn_card_reconciliation is not None else None,
        bn_z_report=float(r.bn_z_report) if r.bn_z_report is not None else None,
        extra_payments=_normalize_extra_payment_rows(_safe_extra_payments_rows(getattr(r, "extra_payments", None))),
        vyhod=float(r.vyhod) if r.vyhod is not None else None,
        percent=float(r.percent) if r.percent is not None else None,
        vzyala=float(r.vzyala) if r.vzyala is not None else None,
        vzyala_details=vzyala_details,
        dolg=float(r.dolg) if r.dolg is not None else None,
        dolg_details=_safe_dolg_details_rows(getattr(r, "dolg_details", None)),
        has_expenses=bool(getattr(r, "has_expenses", False)),
        expenses=_safe_expenses_rows(getattr(r, "expenses", None)),
        z_report_urls=_safe_str_list(getattr(r, "z_report_urls", None)),
        card_reconciliation_urls=_safe_str_list(getattr(r, "card_reconciliation_urls", None)),
        has_encashment=bool(getattr(r, "has_encashment", False)),
        encashment_nal=float(r.encashment_nal) if getattr(r, "encashment_nal", None) is not None else None,
        encashment_bn=float(r.encashment_bn) if getattr(r, "encashment_bn", None) is not None else None,
        withholding_details=_safe_withholding_details_rows(getattr(r, "withholding_details", None)),
    )


def _extra_payments_json(data: DailyReportCreate) -> list[dict]:
    return [
        {
            "amount": p.amount,
            "order_number": p.order_number or "",
            "consultant_last_name": (p.consultant_last_name or "").strip() or None,
        }
        for p in (data.extra_payments or [])
    ]


def _vzyala_details_json(data: DailyReportCreate) -> list[dict] | None:
    if not data.vzyala_details:
        return None
    return [item.model_dump(mode="json") for item in data.vzyala_details]


def _dolg_details_json(data: DailyReportCreate) -> list[dict] | None:
    if not data.dolg_details:
        return None
    return [item.model_dump(mode="json") for item in data.dolg_details]


def _ensure_dolg_row_uids(rows: list[dict] | None) -> list[dict] | None:
    """Гарантирует уникальный id у каждой строки долга."""
    if not rows:
        return rows
    changed = False
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        uid = str(item.get("debt_row_uid") or "").strip()
        if not uid:
            item["debt_row_uid"] = str(uuid4())
            changed = True
        out.append(item)
    return out if changed else rows


def _apply_daily_report_fields(target: DailyReport, data: DailyReportCreate) -> None:
    extra_payments_json = _extra_payments_json(data)
    target.warehouse_id = data.warehouse_id
    target.utro = data.utro
    target.revenue = data.revenue
    target.nal = data.nal
    target.bn = data.bn
    target.ost = data.ost
    target.ost_fact = data.ost_fact
    target.has_returns = data.has_returns
    target.return_bn = data.return_bn if data.has_returns else None
    target.return_nal = data.return_nal if data.has_returns else None
    target.returns_details = (
        [item.model_dump(mode="json") for item in data.returns_details]
        if data.returns_details
        else None
    )
    target.bn_card_reconciliation = data.bn_card_reconciliation
    target.bn_z_report = data.bn_z_report
    target.extra_payments = extra_payments_json or None
    target.vyhod = data.vyhod
    target.percent = data.percent
    if data.vzyala_details:
        target.vzyala_details = _vzyala_details_json(data)
        target.vzyala = sum(x.amount for x in data.vzyala_details)
    else:
        target.vzyala_details = None
        target.vzyala = data.vzyala
    if data.dolg_details:
        target.dolg_details = _ensure_dolg_row_uids(_dolg_details_json(data))
        target.dolg = sum(x.amount for x in data.dolg_details)
    else:
        target.dolg_details = None
        target.dolg = data.dolg
    target.has_expenses = bool(data.has_expenses)
    if data.has_expenses:
        target.expenses = (
            [item.model_dump(mode="json") for item in data.expenses]
            if data.expenses
            else []
        )
    else:
        target.expenses = None
    target.z_report_urls = data.z_report_urls or []
    target.card_reconciliation_urls = data.card_reconciliation_urls or []
    target.has_encashment = bool(data.has_encashment)
    if data.has_encashment:
        target.encashment_nal = data.encashment_nal
        target.encashment_bn = data.encashment_bn
    else:
        target.encashment_nal = None
        target.encashment_bn = None
    if getattr(data, "withholding_details", None):
        target.withholding_details = [
            {"withholding_id": int(x.withholding_id), "amount": round(float(x.amount), 2)}
            for x in data.withholding_details
            if float(x.amount) > DEBT_AMOUNT_EPS and int(x.withholding_id) > 0
        ] or None
    else:
        target.withholding_details = None
    target.is_draft = bool(data.is_draft)


@router.get("/debts/available", response_model=AvailableDebtResponse)
def get_available_debts(
    user_id: int | None = Query(default=None),
    exclude_report_id: int | None = Query(
        default=None,
        description="Не учитывать «Взято» из этого отчёта (при редактировании — чтобы видеть остаток с учётом текущих строк)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Долги прошлых периодов, доступные к зачёту в «Взято».
    Поле amount — остаток (оригинал минус сумма уже зачтённого по linked_debt_row_uid); допускается частичное погашение.
    """
    target_user_id = current_user.id
    if user_id is not None and user_id > 0:
        if is_admin(current_user) or is_manager(current_user):
            target_user_id = user_id
        elif user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Недостаточно прав")

    reports = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.warehouse))
        .filter(DailyReport.user_id == target_user_id, DailyReport.is_draft.is_(False))
        .order_by(DailyReport.created_at.desc(), DailyReport.id.desc())
        .all()
    )

    changed_reports: list[DailyReport] = []
    for report in reports:
        dg_rows = _safe_dolg_details_rows(getattr(report, "dolg_details", None))
        normalized = _ensure_dolg_row_uids(dg_rows)
        if normalized is not dg_rows:
            report.dolg_details = normalized
            changed_reports.append(report)

    if changed_reports:
        db.commit()

    debt_reason_by_id = {x.id: x.name for x in db.query(DebtReason).all()}
    warehouse_by_id_avail = {x.id: x.name for x in db.query(Warehouse).all()}
    taken_by_uid = _build_taken_amounts_by_debt_uid(db, exclude_report_id)
    rows: list[AvailableDebtRow] = []
    for report in reports:
        dg_rows = _safe_dolg_details_rows(getattr(report, "dolg_details", None))
        for row in dg_rows:
            uid = str(row.get("debt_row_uid") or "").strip()
            if not uid or _is_debt_row_admin_closed(row):
                continue
            amount_raw = row.get("amount")
            try:
                original = float(amount_raw) if amount_raw is not None else None
            except (TypeError, ValueError):
                original = None
            if original is None or original <= DEBT_AMOUNT_EPS:
                continue
            taken = taken_by_uid.get(uid, 0.0)
            remaining = original - taken
            if remaining <= DEBT_AMOUNT_EPS:
                continue
            debt_reason_id = row.get("debt_reason_id") if isinstance(row.get("debt_reason_id"), int) else None
            row_wh_id = row.get("warehouse_id") if isinstance(row.get("warehouse_id"), int) else None
            wh_id, wh_name = _resolve_row_warehouse_display(
                row_warehouse_id=row_wh_id,
                report=report,
                warehouse_by_id=warehouse_by_id_avail,
            )
            rows.append(
                AvailableDebtRow(
                    debt_row_uid=uid,
                    report_id=report.id,
                    report_created_at=report.created_at,
                    report_submitted_at=getattr(report, "submitted_at", None),
                    amount=remaining,
                    order_number=str(row.get("order_number") or ""),
                    debt_reason_id=debt_reason_id,
                    debt_reason_name=debt_reason_by_id.get(debt_reason_id) if debt_reason_id is not None else None,
                    report_month=(str(row.get("report_month")).strip() if row.get("report_month") is not None else None),
                    warehouse_id=wh_id,
                    warehouse_name=wh_name,
                )
            )

    manual_q = (
        db.query(ManualEmployeeDebt)
        .options(joinedload(ManualEmployeeDebt.warehouse))
        .filter(ManualEmployeeDebt.user_id == target_user_id)
        .all()
    )
    for m in manual_q:
        uid = str(m.debt_row_uid or "").strip()
        if not uid:
            continue
        try:
            original = float(m.amount) if m.amount is not None else None
        except (TypeError, ValueError):
            original = None
        if original is None or original <= DEBT_AMOUNT_EPS:
            continue
        taken = taken_by_uid.get(uid, 0.0)
        remaining = original - taken
        if remaining <= DEBT_AMOUNT_EPS:
            continue
        rows.append(
            AvailableDebtRow(
                debt_row_uid=uid,
                report_id=0,
                report_created_at=m.created_at,
                report_submitted_at=m.created_at,
                amount=remaining,
                order_number=str(m.order_number or ""),
                debt_reason_id=m.debt_reason_id,
                debt_reason_name=debt_reason_by_id.get(m.debt_reason_id) if m.debt_reason_id is not None else None,
                report_month=(str(m.report_month).strip() if m.report_month is not None else None),
                warehouse_id=m.warehouse_id,
                warehouse_name=(m.warehouse.name if getattr(m, "warehouse", None) else None),
                manual_debt_id=m.id,
                admin_note=(str(m.note).strip() if m.note else None) or None,
            )
        )

    for entry in _collect_one_c_bonus_debts(db, for_user_id=target_user_id):
        uid = str(entry["uid"])
        original = float(entry["amount"])
        taken = taken_by_uid.get(uid, 0.0)
        remaining = original - taken
        if remaining <= DEBT_AMOUNT_EPS:
            continue
        label = str(entry.get("record_type_label") or "").strip()
        rows.append(
            AvailableDebtRow(
                debt_row_uid=uid,
                report_id=0,
                report_created_at=entry.get("log_created_at"),
                report_submitted_at=entry.get("log_created_at"),
                amount=remaining,
                order_number=str(entry.get("order_number") or ""),
                debt_reason_id=None,
                debt_reason_name=(f"1С: {label}" if label else "1С"),
                report_month=(str(entry.get("operation_date")).strip() if entry.get("operation_date") else None),
                warehouse_id=entry.get("warehouse_id"),
                warehouse_name=entry.get("warehouse_name"),
                admin_note=_one_c_entry_admin_note(entry),
            )
        )

    return AvailableDebtResponse(rows=rows)


def _remaining_debt_total_for_user(db: Session, user_id: int) -> float:
    total = 0.0
    taken_by_uid = _build_taken_amounts_by_debt_uid(db, None)
    reports = db.query(DailyReport).filter(DailyReport.user_id == user_id, DailyReport.is_draft.is_(False)).all()
    for report in reports:
        for row in _safe_dolg_details_rows(getattr(report, "dolg_details", None)):
            uid = str(row.get("debt_row_uid") or "").strip()
            if not uid or _is_debt_row_admin_closed(row):
                continue
            raw = row.get("amount")
            try:
                orig = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                orig = None
            if orig is None or orig <= DEBT_AMOUNT_EPS:
                continue
            taken = taken_by_uid.get(uid, 0.0)
            total += max(0.0, orig - taken)
    for m in db.query(ManualEmployeeDebt).filter(ManualEmployeeDebt.user_id == user_id).all():
        uid = str(m.debt_row_uid or "").strip()
        if not uid:
            continue
        try:
            orig = float(m.amount) if m.amount is not None else None
        except (TypeError, ValueError):
            continue
        if orig is None or orig <= DEBT_AMOUNT_EPS:
            continue
        taken = taken_by_uid.get(uid, 0.0)
        total += max(0.0, orig - taken)
    for entry in _collect_one_c_bonus_debts(db, for_user_id=user_id):
        uid = str(entry["uid"])
        orig = float(entry["amount"])
        taken = taken_by_uid.get(uid, 0.0)
        total += max(0.0, orig - taken)
    return total


def _vzyala_totals_for_user(db: Session, user_id: int) -> tuple[float, float]:
    """(сумма всех «Взято», сумма с привязкой к долгу)."""
    total = 0.0
    linked = 0.0
    reports = db.query(DailyReport).filter(DailyReport.user_id == user_id, DailyReport.is_draft.is_(False)).all()
    for report in reports:
        for row in _safe_vzyala_details_rows(getattr(report, "vzyala_details", None)):
            raw = row.get("amount")
            try:
                amt = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                amt = None
            if amt is None or amt <= DEBT_AMOUNT_EPS:
                continue
            total += amt
            if str(row.get("linked_debt_row_uid") or "").strip():
                linked += amt
    return total, linked


def _central_cash_issued_for_user(db: Session, user_id: int) -> float:
    """Сумма выплат сотруднику из центральной кассы."""
    rows = db.query(CentralCashPayout).filter(CentralCashPayout.paid_to_user_id == user_id).all()
    total = 0.0
    for row in rows:
        try:
            total += float(row.amount) if row.amount is not None else 0.0
        except (TypeError, ValueError):
            continue
    return total


def _open_manual_withholding_rows(db: Session, user_id: int) -> list[ManualWithholding]:
    return (
        db.query(ManualWithholding)
        .options(joinedload(ManualWithholding.warehouse))
        .filter(ManualWithholding.user_id == user_id, ManualWithholding.closed.is_(False))
        .order_by(ManualWithholding.created_at.desc(), ManualWithholding.id.desc())
        .all()
    )


def _open_manual_withholdings_sum_and_items(
    db: Session, user_id: int
) -> tuple[float, list[EmployeeSalaryWithholdingItem]]:
    """Сумма и список открытых ручных удержаний (для блока отчёта; на баланс не влияют)."""
    total = 0.0
    items: list[EmployeeSalaryWithholdingItem] = []
    for row in _open_manual_withholding_rows(db, user_id):
        try:
            amt = float(row.amount) if row.amount is not None else 0.0
        except (TypeError, ValueError):
            continue
        if amt <= DEBT_AMOUNT_EPS:
            continue
        total += amt
        wh = getattr(row, "warehouse", None)
        items.append(
            EmployeeSalaryWithholdingItem(
                id=row.id,
                amount=amt,
                reason=(row.reason or "").strip() or None,
                note=(row.note or "").strip() or None,
                report_month=(row.report_month or "").strip() or None,
                warehouse_name=(wh.name if wh is not None else None),
            )
        )
    return total, items


def _open_manual_withholdings_sum(db: Session, user_id: int) -> float:
    total, _ = _open_manual_withholdings_sum_and_items(db, user_id)
    return total


def _cc_pool_balance_before_by_report_id(
    db: Session,
    reports: list[DailyReport],
) -> dict[int, float]:
    """Остаток ЦК до «Взято» каждого отчёта — один проход FIFO на сотрудника (без N+1)."""
    payouts = (
        db.query(CentralCashPayout)
        .order_by(CentralCashPayout.created_at.asc(), CentralCashPayout.id.asc())
        .all()
    )
    payouts_by_user: dict[int, list[CentralCashPayout]] = defaultdict(list)
    for p in payouts:
        payouts_by_user[int(p.paid_to_user_id)].append(p)

    by_user: dict[int, list[DailyReport]] = defaultdict(list)
    for report in reports:
        by_user[int(report.user_id)].append(report)

    out: dict[int, float] = {}
    for user_id, user_reports in by_user.items():
        user_reports.sort(
            key=lambda r: (
                getattr(r, "submitted_at", None) or r.created_at or datetime.min.replace(tzinfo=timezone.utc),
                r.id,
            )
        )
        ups = payouts_by_user.get(user_id, [])
        pools = [float(p.amount or 0) for p in ups]
        payout_ats = [p.created_at for p in ups]
        issued = sum(pools)
        if issued <= DEBT_AMOUNT_EPS:
            for report in user_reports:
                out[report.id] = 0.0
            continue
        for report in user_reports:
            out[report.id] = sum(max(0.0, p) for p in pools)
            ts = getattr(report, "submitted_at", None) or report.created_at
            if not ts:
                continue
            vsum = _vzyala_amount_for_report(report)
            if vsum <= DEBT_AMOUNT_EPS:
                continue
            remaining = vsum
            for i, payout_at in enumerate(payout_ats):
                if payout_at and ts < payout_at:
                    continue
                take = min(remaining, pools[i])
                pools[i] -= take
                remaining -= take
                if remaining <= DEBT_AMOUNT_EPS:
                    break
    return out


def _employee_salary_balance(
    db: Session, user_id: int, *, exclude_report_id: int | None = None
) -> EmployeeSalaryBalanceResponse:
    """
    Остаток выплат из центральной кассы.
    «Взято» списывается только из отчётов, отправленных не раньше соответствующей выплаты (FIFO по датам).
    Старые отчёты до первой выплаты ЦК пул не уменьшают.
    Ручные удержания (/reports/withholding) на баланс не влияют — погашаются отдельным блоком в отчёте.
    """
    payouts = (
        db.query(CentralCashPayout)
        .filter(CentralCashPayout.paid_to_user_id == user_id)
        .order_by(CentralCashPayout.created_at.asc(), CentralCashPayout.id.asc())
        .all()
    )
    issued = _central_cash_issued_for_user(db, user_id)
    withholdings, withholding_items = _open_manual_withholdings_sum_and_items(db, user_id)

    if issued <= DEBT_AMOUNT_EPS:
        return EmployeeSalaryBalanceResponse(
            user_id=user_id,
            central_cash_issued=0.0,
            vzyala_taken=0.0,
            manual_withholdings=withholdings,
            withholding_items=withholding_items,
            balance=0.0,
        )

    pools = [float(p.amount) for p in payouts]
    payout_ats = [p.created_at for p in payouts]

    reports = (
        db.query(DailyReport)
        .filter(DailyReport.user_id == user_id, DailyReport.is_draft.is_(False))
        .order_by(func.coalesce(DailyReport.submitted_at, DailyReport.created_at).asc(), DailyReport.id.asc())
        .all()
    )

    for report in reports:
        if exclude_report_id is not None and report.id == exclude_report_id:
            continue
        ts = getattr(report, "submitted_at", None) or report.created_at
        if not ts:
            continue
        vsum = _vzyala_amount_for_report(report)
        if vsum <= DEBT_AMOUNT_EPS:
            continue
        remaining = vsum
        for i, payout_at in enumerate(payout_ats):
            if payout_at and ts < payout_at:
                continue
            take = min(remaining, pools[i])
            pools[i] -= take
            remaining -= take
            if remaining <= DEBT_AMOUNT_EPS:
                break

    # Остаток ЦК после «Взято» никогда не уходит ниже 0 (перебор «Взято» — из кассы точки, не в минус баланса).
    cc_balance = sum(max(0.0, p) for p in pools)
    taken_from_cc = max(0.0, issued - cc_balance)
    return EmployeeSalaryBalanceResponse(
        user_id=user_id,
        central_cash_issued=issued,
        vzyala_taken=taken_from_cc,
        manual_withholdings=withholdings,
        withholding_items=withholding_items,
        balance=cc_balance,
    )


def _resolve_row_warehouse_display(
    *,
    row_warehouse_id: int | None,
    report: DailyReport | None,
    warehouse_by_id: dict[int, str],
    manual_warehouse: Warehouse | None = None,
) -> tuple[int | None, str | None]:
    """Точка из строки долга/взято; если в строке пусто — из отчёта или ручной записи."""
    wid = row_warehouse_id
    if wid is None and report is not None:
        wid = getattr(report, "warehouse_id", None)
    name: str | None = None
    if wid is not None:
        name = warehouse_by_id.get(wid)
    if not name and manual_warehouse is not None:
        name = manual_warehouse.name
        if wid is None:
            wid = manual_warehouse.id
    if not name and report is not None and getattr(report, "warehouse", None):
        name = report.warehouse.name
        if wid is None:
            wid = report.warehouse_id
    return wid, (name.strip() if isinstance(name, str) and name.strip() else None)


def _compute_debts_summary_rows(db: Session) -> list[DebtSummaryRow]:
    """
    Полная сводка по долгам (все сотрудники).
    Для личного вида консультанта отфильтровать строки по debt_user_id.
    """
    debt_reason_by_id = {x.id: x.name for x in db.query(DebtReason).all()}
    taken_reason_by_id = {x.id: x.name for x in db.query(TakenReason).all()}
    user_by_id = {x.id: x.username for x in db.query(User).all()}
    warehouse_by_id = {x.id: x.name for x in db.query(Warehouse).all()}

    reports = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.warehouse))
        .filter(DailyReport.is_draft.is_(False))
        .order_by(func.coalesce(DailyReport.submitted_at, DailyReport.created_at).asc(), DailyReport.id.asc())
        .all()
    )

    debt_rows_by_uid: dict[str, DebtSummaryRow] = {}
    changed_reports: list[DailyReport] = []

    for report in reports:
        dg_rows = _safe_dolg_details_rows(getattr(report, "dolg_details", None))
        normalized = _ensure_dolg_row_uids(dg_rows)
        if normalized is not dg_rows:
            report.dolg_details = normalized
            changed_reports.append(report)
            dg_rows = normalized or []
        for row in dg_rows:
            uid = str(row.get("debt_row_uid") or "").strip()
            if not uid or _is_debt_row_admin_closed(row):
                continue
            amount_raw = row.get("amount")
            try:
                amount = float(amount_raw) if amount_raw is not None else None
            except (TypeError, ValueError):
                amount = None
            if amount is None:
                continue
            debt_reason_id = row.get("debt_reason_id") if isinstance(row.get("debt_reason_id"), int) else None
            row_wh_id = row.get("warehouse_id") if isinstance(row.get("warehouse_id"), int) else None
            warehouse_id, warehouse_name = _resolve_row_warehouse_display(
                row_warehouse_id=row_wh_id,
                report=report,
                warehouse_by_id=warehouse_by_id,
            )
            debt_rows_by_uid[uid] = DebtSummaryRow(
                debt_row_uid=uid,
                debt_report_id=report.id,
                debt_created_at=report.created_at,
                debt_submitted_at=getattr(report, "submitted_at", None),
                debt_user_id=report.user_id,
                debt_user_name=user_by_id.get(report.user_id, ""),
                debt_amount=amount,
                debt_order_number=str(row.get("order_number") or ""),
                debt_reason_id=debt_reason_id,
                debt_reason_name=debt_reason_by_id.get(debt_reason_id) if debt_reason_id is not None else None,
                debt_report_month=(str(row.get("report_month")).strip() if row.get("report_month") is not None else None),
                debt_warehouse_id=warehouse_id,
                debt_warehouse_name=warehouse_name,
                status="open",
                debt_source="report",
            )

    if changed_reports:
        db.commit()

    manual_debts = (
        db.query(ManualEmployeeDebt)
        .options(joinedload(ManualEmployeeDebt.warehouse))
        .all()
    )
    for m in manual_debts:
        uid = str(m.debt_row_uid or "").strip()
        if not uid or uid in debt_rows_by_uid:
            continue
        try:
            amount = float(m.amount) if m.amount is not None else None
        except (TypeError, ValueError):
            continue
        if amount is None or amount <= DEBT_AMOUNT_EPS:
            continue
        m_wh_id, m_wh_name = _resolve_row_warehouse_display(
            row_warehouse_id=m.warehouse_id,
            report=None,
            warehouse_by_id=warehouse_by_id,
            manual_warehouse=getattr(m, "warehouse", None),
        )
        debt_rows_by_uid[uid] = DebtSummaryRow(
            debt_row_uid=uid,
            debt_report_id=0,
            debt_created_at=m.created_at,
            debt_submitted_at=m.created_at,
            debt_user_id=m.user_id,
            debt_user_name=user_by_id.get(m.user_id, ""),
            debt_amount=amount,
            debt_order_number=str(m.order_number or ""),
            debt_reason_id=m.debt_reason_id,
            debt_reason_name=debt_reason_by_id.get(m.debt_reason_id) if m.debt_reason_id is not None else None,
            debt_report_month=(str(m.report_month).strip() if m.report_month is not None else None),
            debt_warehouse_id=m_wh_id,
            debt_warehouse_name=m_wh_name,
            status="open",
            debt_source="manual",
            manual_debt_id=m.id,
            admin_note=(m.note or "").strip() or None,
        )

    # Дополняем сводку данными из 1С (bonus_arr) с привязкой к консультанту по ФИО.
    for entry in _collect_one_c_bonus_debts(db):
        uid = entry["uid"]
        if uid in debt_rows_by_uid:
            continue
        user_id = int(entry["user_id"] or 0)
        label = entry.get("record_type_label") or ""
        debt_rows_by_uid[uid] = DebtSummaryRow(
            debt_row_uid=uid,
            debt_report_id=0,
            debt_created_at=entry["log_created_at"],
            debt_submitted_at=entry["log_created_at"],
            debt_user_id=user_id,
            debt_user_name=str(entry.get("user_name") or ""),
            debt_amount=float(entry["amount"]),
            debt_order_number=str(entry.get("order_number") or ""),
            debt_reason_id=None,
            debt_reason_name=(f"1С: {label}" if label else "1С"),
            debt_report_month=entry.get("operation_date") or None,
            debt_warehouse_id=entry.get("warehouse_id"),
            debt_warehouse_name=entry.get("warehouse_name"),
            status="open",
            debt_source="1c",
            one_c_exchange_log_id=int(entry["log_id"]),
            admin_note=_one_c_entry_admin_note(entry),
        )

    taken_sum: dict[str, float] = defaultdict(float)
    taken_events_by_uid: dict[str, list[DebtTakeEventItem]] = defaultdict(list)
    for report in reports:
        vz_rows = _safe_vzyala_details_rows(getattr(report, "vzyala_details", None))
        for row in vz_rows:
            uid = str(row.get("linked_debt_row_uid") or "").strip()
            if not uid:
                continue
            raw_amt = row.get("amount")
            try:
                amt = float(raw_amt) if raw_amt is not None else None
            except (TypeError, ValueError):
                amt = None
            if amt is None or amt <= DEBT_AMOUNT_EPS:
                continue
            taken_sum[uid] += amt
            taken_reason_id = row.get("taken_reason_id") if isinstance(row.get("taken_reason_id"), int) else None
            taken_at = getattr(report, "submitted_at", None) or report.created_at
            taken_events_by_uid[uid].append(
                DebtTakeEventItem(
                    amount=amt,
                    report_id=report.id,
                    taken_at=taken_at,
                    taken_user_id=report.user_id,
                    taken_user_name=user_by_id.get(report.user_id, ""),
                    taken_reason_id=taken_reason_id,
                    taken_reason_name=taken_reason_by_id.get(taken_reason_id) if taken_reason_id is not None else None,
                )
            )

    for uid, existing in debt_rows_by_uid.items():
        total_taken = taken_sum.get(uid, 0.0)
        if total_taken <= DEBT_AMOUNT_EPS:
            continue
        events = taken_events_by_uid.get(uid, [])
        if not events:
            continue
        first = events[0]
        existing.take_events = events
        existing.taken_report_id = first.report_id
        existing.taken_at = first.taken_at
        existing.taken_user_id = first.taken_user_id
        existing.taken_user_name = first.taken_user_name or None
        existing.taken_amount = total_taken
        existing.taken_reason_id = first.taken_reason_id
        existing.taken_reason_name = first.taken_reason_name
        debt_amt = existing.debt_amount or 0
        if total_taken + DEBT_AMOUNT_EPS >= debt_amt:
            existing.status = "taken"
        else:
            existing.status = "open"

    return sorted(
        debt_rows_by_uid.values(),
        key=lambda x: (
            0 if x.status == "open" else 1,
            -(x.debt_submitted_at or x.debt_created_at or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
            x.debt_report_id,
        ),
    )


@router.get("/debts/summary", response_model=DebtSummaryResponse)
def get_debts_summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Сводка по долгам:
    - у кого какой долг (строки из dolg_details),
    - кто забрал долг и когда (по linked_debt_row_uid в vzyala_details).
    """
    return DebtSummaryResponse(rows=_compute_debts_summary_rows(db))


@router.get("/debts/my-summary", response_model=DebtSummaryResponse)
def get_my_debts_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Сводка по долгам только для текущего пользователя (консультант видит свои строки)."""
    rows = _compute_debts_summary_rows(db)
    return DebtSummaryResponse(rows=[r for r in rows if r.debt_user_id == user.id])


@router.post("/debts/manual", response_model=ManualDebtResponse)
def create_manual_employee_debt(
    data: ManualDebtCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """Внести долг сотруднику вне сменного отчёта (мотивация и т.п.); дальше зачитывается через «Взято»."""
    if data.amount <= DEBT_AMOUNT_EPS:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")
    u = db.query(User).options(joinedload(User.groups)).filter(User.id == data.user_id).first()
    if not u:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    _validate_report_author_user_id(db, data.user_id)
    if data.debt_reason_id is not None:
        dr = db.query(DebtReason).filter(DebtReason.id == data.debt_reason_id).first()
        if not dr:
            raise HTTPException(status_code=400, detail="Неизвестная причина долга")
    if data.warehouse_id is not None:
        wh = db.query(Warehouse).filter(Warehouse.id == data.warehouse_id).first()
        if not wh:
            raise HTTPException(status_code=400, detail="Неизвестная точка")
    uid = str(uuid4())
    m = ManualEmployeeDebt(
        user_id=data.user_id,
        amount=data.amount,
        debt_reason_id=data.debt_reason_id,
        warehouse_id=data.warehouse_id,
        report_month=(data.report_month or "").strip() or None,
        order_number=(data.order_number or "").strip() or "",
        note=(data.note or "").strip() or None,
        debt_row_uid=uid,
        created_by_user_id=admin_user.id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return ManualDebtResponse(
        id=m.id,
        user_id=m.user_id,
        amount=float(m.amount),
        debt_row_uid=m.debt_row_uid,
        debt_reason_id=m.debt_reason_id,
        warehouse_id=m.warehouse_id,
        report_month=m.report_month,
        order_number=str(m.order_number or ""),
        note=m.note,
        created_at=m.created_at,
    )


@router.patch("/debts/manual/{manual_id}")
def patch_manual_employee_debt(
    manual_id: int,
    data: ManualDebtUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Корректировка ручной записи долга. Сумма не может быть меньше уже зачтённого в «Взято»."""
    m = db.query(ManualEmployeeDebt).filter(ManualEmployeeDebt.id == manual_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    taken = _sum_taken_amounts_for_debt_uid(db, m.debt_row_uid, None)
    payload = data.model_dump(exclude_unset=True)
    if "amount" in payload:
        amt = float(payload["amount"])
        if amt + DEBT_AMOUNT_EPS < taken:
            raise HTTPException(
                status_code=400,
                detail="Сумма долга не может быть меньше уже зачтённого по «Взято».",
            )
        if amt <= DEBT_AMOUNT_EPS:
            if taken > DEBT_AMOUNT_EPS:
                raise HTTPException(
                    status_code=400,
                    detail="Нельзя обнулить долг: по нему уже есть зачёт в «Взято». Сначала скорректируйте сумму до уровня зачтённого или используйте «Погасить полностью».",
                )
            db.delete(m)
            db.commit()
            return Response(status_code=204)
        m.amount = amt
    if "debt_reason_id" in payload:
        drid = payload["debt_reason_id"]
        if drid is not None:
            dr = db.query(DebtReason).filter(DebtReason.id == drid).first()
            if not dr:
                raise HTTPException(status_code=400, detail="Неизвестная причина долга")
        m.debt_reason_id = drid
    if "warehouse_id" in payload:
        wid = payload["warehouse_id"]
        if wid is not None:
            wh = db.query(Warehouse).filter(Warehouse.id == wid).first()
            if not wh:
                raise HTTPException(status_code=400, detail="Неизвестная точка")
        m.warehouse_id = wid
    if "report_month" in payload:
        rm = payload["report_month"]
        m.report_month = (str(rm).strip() if rm is not None else "") or None
    if "order_number" in payload:
        on = payload["order_number"]
        m.order_number = str(on or "").strip() or ""
    if "note" in payload:
        n = payload["note"]
        m.note = (str(n).strip() if n is not None else "") or None
    db.commit()
    db.refresh(m)
    return ManualDebtResponse(
        id=m.id,
        user_id=m.user_id,
        amount=float(m.amount),
        debt_row_uid=m.debt_row_uid,
        debt_reason_id=m.debt_reason_id,
        warehouse_id=m.warehouse_id,
        report_month=m.report_month,
        order_number=str(m.order_number or ""),
        note=m.note,
        created_at=m.created_at,
    )


@router.post("/debts/manual/{manual_id}/settle")
def settle_manual_employee_debt(
    manual_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Погасить долг полностью: сумма записи приводится к сумме уже зачтённой в «Взято» (остаток 0).
    Если зачётов не было — запись удаляется (списание долга).
    """
    m = db.query(ManualEmployeeDebt).filter(ManualEmployeeDebt.id == manual_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    taken = _sum_taken_amounts_for_debt_uid(db, m.debt_row_uid, None)
    if taken <= DEBT_AMOUNT_EPS:
        db.delete(m)
        db.commit()
        return Response(status_code=204)
    m.amount = taken
    db.commit()
    db.refresh(m)
    return ManualDebtResponse(
        id=m.id,
        user_id=m.user_id,
        amount=float(m.amount),
        debt_row_uid=m.debt_row_uid,
        debt_reason_id=m.debt_reason_id,
        warehouse_id=m.warehouse_id,
        report_month=m.report_month,
        order_number=str(m.order_number or ""),
        note=m.note,
        created_at=m.created_at,
    )


@router.post("/debts/manual/{manual_id}/withhold", response_model=ManualWithholdingItem, status_code=201)
def withhold_manual_employee_debt(
    manual_id: int,
    data: ManualDebtWithholdBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """
    Удержать сумму по ручной записи долга: создаёт открытое ручное удержание.
    Баланс сотрудника уменьшается и может уйти в минус. Долг при этом не гасится.
    """
    m = (
        db.query(ManualEmployeeDebt)
        .options(joinedload(ManualEmployeeDebt.debt_reason_rel), joinedload(ManualEmployeeDebt.warehouse))
        .filter(ManualEmployeeDebt.id == manual_id)
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    taken = _sum_taken_amounts_for_debt_uid(db, m.debt_row_uid, None)
    remaining = max(0.0, float(m.amount or 0) - taken)
    if data.amount is not None:
        amt = float(data.amount)
    else:
        amt = remaining
    if amt <= DEBT_AMOUNT_EPS:
        raise HTTPException(status_code=400, detail="Укажите сумму удержания больше нуля")

    reason_default = None
    if m.debt_reason_rel is not None and (m.debt_reason_rel.name or "").strip():
        reason_default = m.debt_reason_rel.name.strip()
    reason = (data.reason or "").strip() or reason_default
    note_parts: list[str] = []
    if (data.note or "").strip():
        note_parts.append(data.note.strip())
    elif (m.note or "").strip():
        note_parts.append(m.note.strip())
    note_parts.append(f"По долгу №{m.id}")
    note = " · ".join(note_parts)

    obj = ManualWithholding(
        user_id=int(m.user_id),
        amount=amt,
        warehouse_id=int(m.warehouse_id) if m.warehouse_id is not None else None,
        report_month=(m.report_month or "").strip() or None,
        reason=reason,
        note=note,
        recorded_by_user_id=current_user.id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    user = db.query(User).filter(User.id == obj.user_id).first()
    user_name = (user.last_name or user.first_name or user.username) if user else f"ID {obj.user_id}"
    rec_name = current_user.last_name or current_user.first_name or current_user.username
    wh_name = m.warehouse.name if m.warehouse is not None else None
    return ManualWithholdingItem(
        id=obj.id,
        created_at=obj.created_at,
        user_id=obj.user_id,
        user_name=user_name,
        amount=float(obj.amount or 0),
        warehouse_id=obj.warehouse_id,
        warehouse_name=wh_name,
        report_month=obj.report_month,
        reason=obj.reason,
        note=obj.note,
        recorded_by_user_id=obj.recorded_by_user_id,
        recorded_by_name=rec_name,
        closed=bool(getattr(obj, "closed", False)),
        closed_at=getattr(obj, "closed_at", None),
        closed_by_user_id=getattr(obj, "closed_by_user_id", None),
        closed_by_name=None,
    )


def _append_linked_debt_take_to_report(
    report: DailyReport,
    dolg_row: dict,
    debt_row_uid: str,
    amount: float,
) -> None:
    """Добавить в отчёт строку «Взято» с привязкой к долгу (закрытие остатка администратором)."""
    vz_rows = list(_safe_vzyala_details_rows(getattr(report, "vzyala_details", None)))
    vz_rows.append(
        {
            "order_number": str(dolg_row.get("order_number") or ""),
            "amount": round(amount, 2),
            "taken_reason_id": TAKE_DEBT_REASON_VIRTUAL_ID,
            "taken_source_id": None,
            "order_percent": dolg_row.get("order_percent")
            if isinstance(dolg_row.get("order_percent"), (int, float))
            else None,
            "report_month": dolg_row.get("report_month"),
            "warehouse_id": dolg_row.get("warehouse_id")
            if isinstance(dolg_row.get("warehouse_id"), int)
            else None,
            "linked_debt_row_uid": debt_row_uid,
            "linked_debt_report_id": report.id,
        }
    )
    report.vzyala_details = vz_rows
    total = _vzyala_amount_for_report(report)
    report.vzyala = total if total > DEBT_AMOUNT_EPS else None


@router.post("/debts/report-item/close", status_code=204)
def close_report_debt_item(
    debt_row_uid: str = Query(..., description="debt_row_uid строки из dolg_details отчёта"),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """
    Закрыть долг из сменного отчёта: непогашенный остаток переносится в «Взято» этого отчёта,
    строка долга помечается закрытой и исчезает из активной сводки.
    """
    uid = str(debt_row_uid or "").strip()
    if uid.startswith("1c-log-"):
        raise HTTPException(status_code=400, detail="Для долгов 1С используйте удаление строки 1С")
    if db.query(ManualEmployeeDebt).filter(ManualEmployeeDebt.debt_row_uid == uid).first():
        raise HTTPException(status_code=400, detail="Для ручных долгов используйте погашение или удаление")

    report, rows, idx = _find_report_dolg_row_by_uid(db, uid)
    row = rows[idx]
    if _is_debt_row_admin_closed(row):
        return Response(status_code=204)

    amount_raw = row.get("amount")
    try:
        original = float(amount_raw) if amount_raw is not None else None
    except (TypeError, ValueError):
        original = None
    if original is None or original <= DEBT_AMOUNT_EPS:
        raise HTTPException(status_code=400, detail="Сумма долга в отчёте не указана")

    taken_by_uid = _build_taken_amounts_by_debt_uid(db, None)
    taken = taken_by_uid.get(uid, 0.0)
    remaining = original - taken
    if remaining > DEBT_AMOUNT_EPS:
        _append_linked_debt_take_to_report(report, row, uid, remaining)

    row = dict(row)
    row["admin_closed"] = True
    row["closed_at"] = datetime.now(timezone.utc).isoformat()
    row["closed_by_user_id"] = admin_user.id
    rows[idx] = row
    report.dolg_details = rows
    db.commit()
    return Response(status_code=204)


@router.delete("/debts/manual/{manual_id}", status_code=204)
def delete_manual_employee_debt(
    manual_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    m = db.query(ManualEmployeeDebt).filter(ManualEmployeeDebt.id == manual_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    taken = _sum_taken_amounts_for_debt_uid(db, m.debt_row_uid, None)
    if taken > DEBT_AMOUNT_EPS:
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить запись: по этому долгу уже есть зачёт в блоке «Взято».",
        )
    db.delete(m)
    db.commit()
    return None


def _remove_one_c_bonus_item_from_log(db: Session, log_id: int, index: int) -> None:
    """Убрать одну строку bonus_arr, не трогая остальные (индексы и uid 1c-log-{id}-{i} сохраняются)."""
    lg = db.query(Order1cExchangeLog).filter(Order1cExchangeLog.id == log_id).first()
    if not lg:
        raise HTTPException(status_code=404, detail="Запись обмена 1С не найдена")
    raw = (lg.body_text or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="Пустое тело записи 1С")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Некорректный JSON записи 1С") from e
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Некорректный формат записи 1С")
    bonus_arr = payload.get("bonus_arr")
    if not isinstance(bonus_arr, list) or index < 0 or index >= len(bonus_arr):
        raise HTTPException(status_code=404, detail="Строка bonus_arr не найдена")
    row = bonus_arr[index]
    if row is None or (isinstance(row, dict) and row.get("_removed_from_debts")):
        raise HTTPException(status_code=404, detail="Строка уже удалена из сводки")
    bonus_arr[index] = None
    payload["bonus_arr"] = bonus_arr
    lg.body_text = json.dumps(payload, ensure_ascii=False)
    lg.json_parse_ok = True


def _get_one_c_bonus_row_mutable(
    db: Session, debt_row_uid: str
) -> tuple[Order1cExchangeLog, dict, list, int, dict]:
    """Загрузить лог 1С и активную строку bonus_arr для правки."""
    parsed = _parse_one_c_debt_uid(debt_row_uid)
    if parsed is None:
        raise HTTPException(status_code=400, detail="Некорректный идентификатор строки 1С")
    log_id, index = parsed
    lg = db.query(Order1cExchangeLog).filter(Order1cExchangeLog.id == log_id).first()
    if not lg:
        raise HTTPException(status_code=404, detail="Запись обмена 1С не найдена")
    raw = (lg.body_text or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="Пустое тело записи 1С")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Некорректный JSON записи 1С") from e
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Некорректный формат записи 1С")
    bonus_arr = payload.get("bonus_arr")
    if not isinstance(bonus_arr, list) or index < 0 or index >= len(bonus_arr):
        raise HTTPException(status_code=404, detail="Строка bonus_arr не найдена")
    row = bonus_arr[index]
    if row is None or not isinstance(row, dict) or row.get("_removed_from_debts"):
        raise HTTPException(status_code=404, detail="Строка уже удалена из сводки")
    return lg, payload, bonus_arr, index, row


def _persist_one_c_bonus_payload(lg: Order1cExchangeLog, payload: dict) -> None:
    lg.body_text = json.dumps(payload, ensure_ascii=False)
    lg.json_parse_ok = True


@router.patch("/debts/one-c-item")
def patch_one_c_debt_item(
    data: OneCDebtItemUpdate,
    debt_row_uid: str = Query(..., description="uid строки долга, например 1c-log-12-0"),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Корректировка строки долга из 1С. Сумма не может быть меньше уже зачтённого в «Взято»."""
    uid = str(debt_row_uid or "").strip()
    lg, payload, bonus_arr, index, row = _get_one_c_bonus_row_mutable(db, uid)
    taken = _sum_taken_amounts_for_debt_uid(db, uid, None)
    fields = data.model_dump(exclude_unset=True)

    if "amount" in fields:
        amt = float(fields["amount"])
        if amt + DEBT_AMOUNT_EPS < taken:
            raise HTTPException(
                status_code=400,
                detail="Сумма долга не может быть меньше уже зачтённого по «Взято».",
            )
        if amt <= DEBT_AMOUNT_EPS:
            if taken > DEBT_AMOUNT_EPS:
                raise HTTPException(
                    status_code=400,
                    detail="Нельзя обнулить долг: по нему уже есть зачёт в «Взято». Сначала скорректируйте сумму до уровня зачтённого или используйте «Погасить полностью».",
                )
            bonus_arr[index] = None
            payload["bonus_arr"] = bonus_arr
            _persist_one_c_bonus_payload(lg, payload)
            db.commit()
            return Response(status_code=204)
        row["sum"] = round(amt, 2)

    if "order_number" in fields:
        row["order_number"] = str(fields["order_number"] or "").strip()

    if "note" in fields:
        note = fields["note"]
        row["comment"] = (str(note).strip() if note is not None else "") or ""

    if "report_month" in fields:
        rm = fields["report_month"]
        text = (str(rm).strip() if rm is not None else "") or ""
        if text:
            if re.match(r"^\d{2}\.\d{2}\.\d{4}$", text):
                row["operation_date"] = f"{text} 0:00:00"
            else:
                row["operation_date"] = text

    if "warehouse_id" in fields:
        wid = fields["warehouse_id"]
        if wid is None:
            row["trade_point"] = ""
        else:
            wh = db.query(Warehouse).filter(Warehouse.id == wid).first()
            if not wh:
                raise HTTPException(status_code=400, detail="Неизвестная точка")
            row["trade_point"] = str(wh.name or "").strip()

    bonus_arr[index] = row
    payload["bonus_arr"] = bonus_arr
    _persist_one_c_bonus_payload(lg, payload)
    db.commit()
    return {
        "debt_row_uid": uid,
        "amount": float(row.get("sum") or 0),
        "order_number": str(row.get("order_number") or ""),
        "note": str(row.get("comment") or "") or None,
        "report_month": _format_one_c_operation_date(str(row.get("operation_date") or "")) or None,
        "trade_point": str(row.get("trade_point") or "") or None,
    }


@router.post("/debts/one-c-item/settle", status_code=204)
def settle_one_c_debt_item(
    debt_row_uid: str = Query(..., description="uid строки долга, например 1c-log-12-0"),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Погасить долг 1С полностью: сумма приводится к зачтённому в «Взято» (остаток 0).
    Если зачётов не было — строка удаляется из сводки.
    """
    uid = str(debt_row_uid or "").strip()
    lg, payload, bonus_arr, index, row = _get_one_c_bonus_row_mutable(db, uid)
    taken = _sum_taken_amounts_for_debt_uid(db, uid, None)
    if taken <= DEBT_AMOUNT_EPS:
        bonus_arr[index] = None
        payload["bonus_arr"] = bonus_arr
        _persist_one_c_bonus_payload(lg, payload)
        db.commit()
        return Response(status_code=204)
    row["sum"] = round(taken, 2)
    bonus_arr[index] = row
    payload["bonus_arr"] = bonus_arr
    _persist_one_c_bonus_payload(lg, payload)
    db.commit()
    return Response(status_code=204)


@router.delete("/debts/one-c-item", status_code=204)
def delete_one_c_debt_item(
    debt_row_uid: str = Query(..., description="uid строки долга, например 1c-log-12-0"),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Удалить одну строку долга из bonus_arr записи 1С (не весь лог обмена)."""
    parsed = _parse_one_c_debt_uid(debt_row_uid)
    if parsed is None:
        raise HTTPException(status_code=400, detail="Некорректный идентификатор строки 1С")
    log_id, index = parsed
    taken = _sum_taken_amounts_for_debt_uid(db, debt_row_uid.strip(), None)
    if taken > DEBT_AMOUNT_EPS:
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить строку: по этому долгу уже есть зачёт в блоке «Взято».",
        )
    _remove_one_c_bonus_item_from_log(db, log_id, index)
    db.commit()
    return None


@router.delete("/debts/one-c/{log_id}", status_code=204)
def delete_one_c_debt_log(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Удалить весь лог обмена 1С (все строки bonus_arr). Для одной строки — DELETE /debts/one-c-item."""
    row = db.query(Order1cExchangeLog).filter(Order1cExchangeLog.id == log_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Запись обмена 1С не найдена")
    db.delete(row)
    db.commit()
    return None


def _compute_taken_summary_rows(db: Session) -> list[TakenSummaryRow]:
    """Все строки блока «Взято» по отправленным отчётам (для админ-сводки и личного вида консультанта)."""
    user_by_id = {x.id: x.username for x in db.query(User).all()}
    warehouse_by_id = {x.id: x.name for x in db.query(Warehouse).all()}
    reports = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.warehouse))
        .filter(DailyReport.is_draft.is_(False))
        .order_by(func.coalesce(DailyReport.submitted_at, DailyReport.created_at).desc(), DailyReport.id.desc())
        .all()
    )

    linked_uids: set[str] = set()
    for report in reports:
        for row in _safe_vzyala_details_rows(getattr(report, "vzyala_details", None)):
            uid = str(row.get("linked_debt_row_uid") or "").strip()
            if uid:
                linked_uids.add(uid)

    ctx = _load_vzyala_display_context(db, only_debt_uids=linked_uids)
    taken_reason_by_id = ctx.taken_reason_by_id
    balance_before = _cc_pool_balance_before_by_report_id(db, reports)

    out: list[TakenSummaryRow] = []
    for report in reports:
        vz_rows = _safe_vzyala_details_rows(getattr(report, "vzyala_details", None))
        if not vz_rows:
            continue
        cc_pool_remaining = [max(0.0, float(balance_before.get(report.id, 0.0)))]
        for i, row in enumerate(vz_rows):
            raw_amt = row.get("amount")
            try:
                amt = float(raw_amt) if raw_amt is not None else None
            except (TypeError, ValueError):
                amt = None
            if amt is None or amt <= DEBT_AMOUNT_EPS:
                continue
            taken_reason_id = row.get("taken_reason_id") if isinstance(row.get("taken_reason_id"), int) else None
            taken_source_id = row.get("taken_source_id") if isinstance(row.get("taken_source_id"), int) else None
            row_wid = row.get("warehouse_id") if isinstance(row.get("warehouse_id"), int) else None
            wid, wh_name = _resolve_row_warehouse_display(
                row_warehouse_id=row_wid,
                report=report,
                warehouse_by_id=warehouse_by_id,
            )
            linked = str(row.get("linked_debt_row_uid") or "").strip()
            lrid = row.get("linked_debt_report_id")
            linked_report_id: int | None = None
            if lrid is not None and str(lrid).strip() != "":
                try:
                    linked_report_id = int(lrid)
                except (TypeError, ValueError):
                    linked_report_id = None
            if linked:
                debt = ctx.debt_by_uid.get(linked, {})
                drn = (debt.get("debt_reason_name") or "").strip() or None
                reason_name = drn or TAKE_DEBT_REASON_LABEL
                debt_source_label, debt_source_kind = _linked_debt_source_label(
                    linked, debt, linked_report_id=linked_report_id
                )
                debt_reason_name = drn
            elif taken_reason_id == TAKE_DEBT_REASON_VIRTUAL_ID:
                reason_name = TAKE_DEBT_REASON_LABEL
                debt_source_label, debt_source_kind = None, None
                debt_reason_name = None
            else:
                reason_name = (
                    taken_reason_by_id.get(taken_reason_id) if taken_reason_id is not None else None
                )
                debt_source_label, debt_source_kind = None, None
                debt_reason_name = None
            source_name = _resolve_vzyala_taken_source_name(row, ctx, cc_pool_remaining)
            rm = row.get("report_month")
            report_month = str(rm).strip() if rm is not None else None
            onum = str(row.get("order_number") or "")
            out.append(
                TakenSummaryRow(
                    row_key=f"{report.id}-{i}",
                    report_id=report.id,
                    report_created_at=report.created_at,
                    report_submitted_at=getattr(report, "submitted_at", None),
                    user_id=report.user_id,
                    user_name=user_by_id.get(report.user_id, ""),
                    amount=amt,
                    taken_reason_id=taken_reason_id,
                    taken_reason_name=reason_name,
                    taken_source_id=taken_source_id,
                    taken_source_name=source_name,
                    order_number=onum,
                    report_month=report_month,
                    warehouse_id=wid,
                    warehouse_name=wh_name,
                    linked_debt_row_uid=linked or None,
                    linked_debt_report_id=linked_report_id,
                    is_linked_debt_take=bool(linked),
                    debt_source_label=debt_source_label,
                    debt_source_kind=debt_source_kind,
                    debt_reason_name=debt_reason_name,
                )
            )
    return out


@router.get("/taken/summary", response_model=TakenSummaryResponse)
def get_taken_summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Все строки блока «Взято» по отправленным отчётам (в т.ч. зачёт долга)."""
    return TakenSummaryResponse(rows=_compute_taken_summary_rows(db))


@router.get("/taken/my-summary", response_model=TakenSummaryResponse)
def get_my_taken_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Строки «Взято» только из отчётов текущего пользователя."""
    rows = _compute_taken_summary_rows(db)
    return TakenSummaryResponse(rows=[r for r in rows if r.user_id == user.id])


@router.get("/withholding/summary", response_model=ManualWithholdingResponse)
def withholding_summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    rows_db = (
        db.query(ManualWithholding)
        .order_by(ManualWithholding.created_at.desc(), ManualWithholding.id.desc())
        .all()
    )
    user_ids = (
        {r.user_id for r in rows_db if r.user_id}
        | {r.recorded_by_user_id for r in rows_db if r.recorded_by_user_id}
        | {getattr(r, "closed_by_user_id", None) for r in rows_db if getattr(r, "closed_by_user_id", None)}
    )
    wh_ids = {r.warehouse_id for r in rows_db if r.warehouse_id}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(list(user_ids))).all()} if user_ids else {}
    whs = {w.id: w.name for w in db.query(Warehouse).filter(Warehouse.id.in_(list(wh_ids))).all()} if wh_ids else {}

    out: list[ManualWithholdingItem] = []
    for r in rows_db:
        usr = users.get(r.user_id)
        rec = users.get(r.recorded_by_user_id) if r.recorded_by_user_id else None
        clo = users.get(getattr(r, "closed_by_user_id", None)) if getattr(r, "closed_by_user_id", None) else None
        user_name = (usr.last_name or usr.first_name or usr.username) if usr else f"ID {r.user_id}"
        recorded_by_name = (rec.last_name or rec.first_name or rec.username) if rec else None
        out.append(
            ManualWithholdingItem(
                id=r.id,
                created_at=r.created_at,
                user_id=r.user_id,
                user_name=user_name,
                amount=float(r.amount or 0),
                warehouse_id=r.warehouse_id,
                warehouse_name=whs.get(r.warehouse_id) if r.warehouse_id else None,
                report_month=r.report_month,
                reason=r.reason,
                note=r.note,
                recorded_by_user_id=r.recorded_by_user_id,
                recorded_by_name=recorded_by_name,
                closed=bool(getattr(r, "closed", False)),
                closed_at=getattr(r, "closed_at", None),
                closed_by_user_id=getattr(r, "closed_by_user_id", None),
                closed_by_name=(clo.last_name or clo.first_name or clo.username) if clo else None,
            )
        )
    return ManualWithholdingResponse(rows=out)


@router.post("/withholding/manual", response_model=ManualWithholdingItem, status_code=201)
def create_withholding_manual(
    data: ManualWithholdingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    user = db.query(User).filter(User.id == int(data.user_id), User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=400, detail="Сотрудник не найден или неактивен")
    wh_name = None
    if data.warehouse_id is not None:
        wh = db.query(Warehouse).filter(Warehouse.id == int(data.warehouse_id)).first()
        if not wh:
            raise HTTPException(status_code=400, detail="Точка не найдена")
        wh_name = wh.name
    obj = ManualWithholding(
        user_id=int(data.user_id),
        amount=float(data.amount),
        warehouse_id=int(data.warehouse_id) if data.warehouse_id is not None else None,
        report_month=(data.report_month or "").strip() or None,
        reason=(data.reason or "").strip() or None,
        note=(data.note or "").strip() or None,
        recorded_by_user_id=current_user.id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    user_name = user.last_name or user.first_name or user.username
    rec_name = current_user.last_name or current_user.first_name or current_user.username
    return ManualWithholdingItem(
        id=obj.id,
        created_at=obj.created_at,
        user_id=obj.user_id,
        user_name=user_name,
        amount=float(obj.amount or 0),
        warehouse_id=obj.warehouse_id,
        warehouse_name=wh_name,
        report_month=obj.report_month,
        reason=obj.reason,
        note=obj.note,
        recorded_by_user_id=obj.recorded_by_user_id,
        recorded_by_name=rec_name,
        closed=bool(getattr(obj, "closed", False)),
        closed_at=getattr(obj, "closed_at", None),
        closed_by_user_id=getattr(obj, "closed_by_user_id", None),
        closed_by_name=None,
    )


@router.patch("/withholding/manual/{item_id}", response_model=ManualWithholdingItem)
def update_withholding_manual(
    item_id: int,
    data: ManualWithholdingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    obj = db.query(ManualWithholding).filter(ManualWithholding.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Запись удержания не найдена")

    if data.user_id is not None:
        user = db.query(User).filter(User.id == int(data.user_id), User.is_active == True).first()
        if not user:
            raise HTTPException(status_code=400, detail="Сотрудник не найден или неактивен")
        obj.user_id = int(data.user_id)
    else:
        user = db.query(User).filter(User.id == int(obj.user_id)).first()

    if data.amount is not None:
        obj.amount = float(data.amount)

    if data.warehouse_id is not None:
        if int(data.warehouse_id) <= 0:
            obj.warehouse_id = None
        else:
            wh = db.query(Warehouse).filter(Warehouse.id == int(data.warehouse_id)).first()
            if not wh:
                raise HTTPException(status_code=400, detail="Точка не найдена")
            obj.warehouse_id = int(data.warehouse_id)
    # Если warehouse_id не передали — оставляем как было.

    if data.report_month is not None:
        obj.report_month = (data.report_month or "").strip() or None
    if data.reason is not None:
        obj.reason = (data.reason or "").strip() or None
    if data.note is not None:
        obj.note = (data.note or "").strip() or None

    db.add(obj)
    db.commit()
    db.refresh(obj)

    wh_name = None
    if obj.warehouse_id:
        wh = db.query(Warehouse).filter(Warehouse.id == int(obj.warehouse_id)).first()
        wh_name = wh.name if wh else None
    user_name = (user.last_name or user.first_name or user.username) if user else f"ID {obj.user_id}"
    rec_name = current_user.last_name or current_user.first_name or current_user.username
    return ManualWithholdingItem(
        id=obj.id,
        created_at=obj.created_at,
        user_id=obj.user_id,
        user_name=user_name,
        amount=float(obj.amount or 0),
        warehouse_id=obj.warehouse_id,
        warehouse_name=wh_name,
        report_month=obj.report_month,
        reason=obj.reason,
        note=obj.note,
        recorded_by_user_id=obj.recorded_by_user_id,
        recorded_by_name=rec_name,
        closed=bool(getattr(obj, "closed", False)),
        closed_at=getattr(obj, "closed_at", None),
        closed_by_user_id=getattr(obj, "closed_by_user_id", None),
        closed_by_name=None,
    )


@router.post("/withholding/manual/{item_id}/close", response_model=ManualWithholdingItem)
def close_withholding_manual(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    obj = db.query(ManualWithholding).filter(ManualWithholding.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Запись удержания не найдена")
    obj.closed = True
    obj.closed_at = datetime.now(timezone.utc)
    obj.closed_by_user_id = current_user.id
    db.add(obj)
    db.commit()
    db.refresh(obj)

    usr = db.query(User).filter(User.id == int(obj.user_id)).first()
    wh = db.query(Warehouse).filter(Warehouse.id == int(obj.warehouse_id)).first() if obj.warehouse_id else None
    user_name = (usr.last_name or usr.first_name or usr.username) if usr else f"ID {obj.user_id}"
    rec_name = current_user.last_name or current_user.first_name or current_user.username
    return ManualWithholdingItem(
        id=obj.id,
        created_at=obj.created_at,
        user_id=obj.user_id,
        user_name=user_name,
        amount=float(obj.amount or 0),
        warehouse_id=obj.warehouse_id,
        warehouse_name=wh.name if wh else None,
        report_month=obj.report_month,
        reason=obj.reason,
        note=obj.note,
        recorded_by_user_id=obj.recorded_by_user_id,
        recorded_by_name=rec_name,
        closed=True,
        closed_at=obj.closed_at,
        closed_by_user_id=obj.closed_by_user_id,
        closed_by_name=rec_name,
    )


@router.post("/withholding/manual/{item_id}/reopen", response_model=ManualWithholdingItem)
def reopen_withholding_manual(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    obj = db.query(ManualWithholding).filter(ManualWithholding.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Запись удержания не найдена")
    obj.closed = False
    obj.closed_at = None
    obj.closed_by_user_id = None
    db.add(obj)
    db.commit()
    db.refresh(obj)

    usr = db.query(User).filter(User.id == int(obj.user_id)).first()
    wh = db.query(Warehouse).filter(Warehouse.id == int(obj.warehouse_id)).first() if obj.warehouse_id else None
    user_name = (usr.last_name or usr.first_name or usr.username) if usr else f"ID {obj.user_id}"
    rec_name = current_user.last_name or current_user.first_name or current_user.username
    return ManualWithholdingItem(
        id=obj.id,
        created_at=obj.created_at,
        user_id=obj.user_id,
        user_name=user_name,
        amount=float(obj.amount or 0),
        warehouse_id=obj.warehouse_id,
        warehouse_name=wh.name if wh else None,
        report_month=obj.report_month,
        reason=obj.reason,
        note=obj.note,
        recorded_by_user_id=obj.recorded_by_user_id,
        recorded_by_name=rec_name,
        closed=False,
        closed_at=None,
        closed_by_user_id=None,
        closed_by_name=None,
    )


@router.delete("/withholding/manual/{item_id}", status_code=204)
def delete_withholding_manual(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    obj = db.query(ManualWithholding).filter(ManualWithholding.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Запись удержания не найдена")
    db.delete(obj)
    db.commit()
    return None


def _employee_ledger_sort_key(line: EmployeeLedgerLine) -> tuple:
    t = line.at
    if t is None:
        ts = 0.0
    else:
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        ts = t.timestamp()
    kind_order = {"debt_manual": 0, "debt_report": 1, "taken": 2}.get(line.kind, 9)
    return (ts, line.report_id or 0, kind_order, line.manual_debt_id or 0)


@router.get("/employee-salary-balance", response_model=EmployeeSalaryBalanceResponse)
def get_employee_salary_balance(
    user_id: int = Query(..., description="ID консультанта (автор отчётов)"),
    exclude_report_id: int | None = Query(
        None, description="Исключить отчёт при подсчёте «Взято» (редактирование — учёт строк формы отдельно)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Баланс: выплаты из ЦК минус «Взято» и открытые удержания.
    В минус баланс уходит только из-за удержаний (не из-за «Взято»).
    """
    if not is_admin(current_user) and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Нет доступа к балансу этого сотрудника")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return _employee_salary_balance(db, user_id, exclude_report_id=exclude_report_id)


@router.get("/debts/employee-ledger", response_model=EmployeeLedgerResponse)
def get_employee_debt_ledger(
    user_id: int = Query(..., description="ID консультанта (автор отчётов)"),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Хронология долгов и «Взято» по одному сотруднику + сводные суммы."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    uname = (u.username or "").strip() or f"ID {user_id}"
    remaining = _remaining_debt_total_for_user(db, user_id)
    vzy_all, vzy_linked = _vzyala_totals_for_user(db, user_id)

    lines: list[EmployeeLedgerLine] = []

    for m in (
        db.query(ManualEmployeeDebt)
        .options(joinedload(ManualEmployeeDebt.debt_reason_rel))
        .filter(ManualEmployeeDebt.user_id == user_id)
        .order_by(ManualEmployeeDebt.created_at.asc(), ManualEmployeeDebt.id.asc())
        .all()
    ):
        note_txt = f": {m.note}" if (m.note or "").strip() else ""
        drn = None
        if getattr(m, "debt_reason_rel", None) is not None:
            drn = (m.debt_reason_rel.name or "").strip() or None
        desc_parts = [f"Долг внесён вручную{note_txt} (запись №{m.id})"]
        if drn:
            desc_parts.append(drn)
        lines.append(
            EmployeeLedgerLine(
                at=m.created_at,
                kind="debt_manual",
                report_id=None,
                manual_debt_id=m.id,
                amount=float(m.amount),
                description=" · ".join(desc_parts),
                debt_reason_name=drn,
                debt_source_label=("Ручной долг" + (f" · {drn}" if drn else "") + note_txt),
                debt_source_kind="manual",
            )
        )

    reports = (
        db.query(DailyReport)
        .filter(DailyReport.user_id == user_id, DailyReport.is_draft.is_(False))
        .order_by(DailyReport.created_at.asc(), DailyReport.id.asc())
        .all()
    )
    debt_reason_by_id = {x.id: x.name for x in db.query(DebtReason).all()}
    taken_reason_by_id = {x.id: x.name for x in db.query(TakenReason).all()}
    taken_reason_by_id[TAKE_DEBT_REASON_VIRTUAL_ID] = TAKE_DEBT_REASON_LABEL

    linked_uids: set[str] = set()
    for report in reports:
        for row in _safe_vzyala_details_rows(getattr(report, "vzyala_details", None)):
            uid = str(row.get("linked_debt_row_uid") or "").strip()
            if uid:
                linked_uids.add(uid)
    ctx = _load_vzyala_display_context(db, only_debt_uids=linked_uids)
    balance_before = _cc_pool_balance_before_by_report_id(db, reports)

    for report in reports:
        ts = getattr(report, "submitted_at", None) or report.created_at
        dg_rows = _safe_dolg_details_rows(getattr(report, "dolg_details", None))
        for row in dg_rows:
            if _is_debt_row_admin_closed(row):
                continue
            raw = row.get("amount")
            try:
                amt = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                amt = None
            if amt is None or amt <= DEBT_AMOUNT_EPS:
                continue
            drid = row.get("debt_reason_id") if isinstance(row.get("debt_reason_id"), int) else None
            rn = debt_reason_by_id.get(drid) if drid is not None else None
            ordn = str(row.get("order_number") or "")
            desc = f"Долг в отчёте №{report.id}"
            if rn:
                desc += f" · {rn}"
            if ordn:
                desc += f" · заказ {ordn}"
            lines.append(
                EmployeeLedgerLine(
                    at=ts,
                    kind="debt_report",
                    report_id=report.id,
                    manual_debt_id=None,
                    amount=amt,
                    description=desc,
                    debt_reason_name=rn,
                    debt_source_label=desc,
                    debt_source_kind="report",
                )
            )

        vz_rows = _safe_vzyala_details_rows(getattr(report, "vzyala_details", None))
        if not vz_rows:
            continue
        cc_pool_remaining = [max(0.0, float(balance_before.get(report.id, 0.0)))]
        for row in vz_rows:
            raw = row.get("amount")
            try:
                amt = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                amt = None
            if amt is None or amt <= DEBT_AMOUNT_EPS:
                continue
            trid = row.get("taken_reason_id") if isinstance(row.get("taken_reason_id"), int) else None
            linked = str(row.get("linked_debt_row_uid") or "").strip()
            lrid = row.get("linked_debt_report_id")
            linked_report_id: int | None = None
            if lrid is not None and str(lrid).strip() != "":
                try:
                    linked_report_id = int(lrid)
                except (TypeError, ValueError):
                    linked_report_id = None

            debt_reason_name: str | None = None
            debt_source_label: str | None = None
            debt_source_kind: str | None = None
            if linked:
                debt = ctx.debt_by_uid.get(linked, {})
                debt_reason_name = (debt.get("debt_reason_name") or "").strip() or None
                taken_reason_name = debt_reason_name or TAKE_DEBT_REASON_LABEL
                debt_source_label, debt_source_kind = _linked_debt_source_label(
                    linked, debt, linked_report_id=linked_report_id
                )
                desc = f"Взято — зачёт долга · отчёт №{report.id}"
                if debt_reason_name:
                    desc += f" · {debt_reason_name}"
            else:
                if trid == TAKE_DEBT_REASON_VIRTUAL_ID:
                    taken_reason_name = TAKE_DEBT_REASON_LABEL
                else:
                    taken_reason_name = taken_reason_by_id.get(trid) if trid is not None else None
                desc = f"Взято ({taken_reason_name or 'строка зарплаты'}) · отчёт №{report.id}"

            taken_source_name = _resolve_vzyala_taken_source_name(row, ctx, cc_pool_remaining)
            lines.append(
                EmployeeLedgerLine(
                    at=ts,
                    kind="taken",
                    report_id=report.id,
                    manual_debt_id=None,
                    amount=amt,
                    description=desc,
                    taken_reason_name=taken_reason_name,
                    taken_source_name=taken_source_name,
                    debt_source_label=debt_source_label,
                    debt_source_kind=debt_source_kind,
                    debt_reason_name=debt_reason_name,
                    is_linked_debt_take=bool(linked),
                    linked_debt_report_id=linked_report_id,
                )
            )

    lines.sort(key=_employee_ledger_sort_key)

    return EmployeeLedgerResponse(
        user_id=user_id,
        user_name=uname,
        remaining_debt_total=remaining,
        vzyala_total=vzy_all,
        vzyala_linked_debt_total=vzy_linked,
        lines=lines,
    )


@router.post("", response_model=DailyReportResponse, status_code=201)
def create_report(
    data: DailyReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отправить отчёт. Доступно только группе «Консультанты»."""
    if not _is_consultant(current_user):
        raise HTTPException(status_code=403, detail="Доступно только для группы «Консультанты»")

    if not data.is_draft:
        req_keys = _load_required_report_keys()
        if req_keys:
            try:
                validate_report_required_fields(data, req_keys)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

    existing_draft = (
        db.query(DailyReport)
        .filter(DailyReport.user_id == current_user.id, DailyReport.is_draft.is_(True))
        .order_by(DailyReport.created_at.desc())
        .first()
    )

    if not data.is_draft:
        _validate_vzyala_linked_debts(
            db,
            data,
            exclude_report_id=existing_draft.id if existing_draft is not None else None,
        )
        _validate_vzyala_cash_against_ost(db, current_user.id, data)
        try:
            validate_revenue_breakdown(data)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # Черновик не гасит удержания; при первой отправке prev пустой.
    prev_withholding_details = []
    if existing_draft is not None:
        report = existing_draft
        was_submitted = not bool(getattr(report, "is_draft", False))
        if was_submitted:
            prev_withholding_details = _safe_withholding_details_rows(getattr(report, "withholding_details", None))
        _apply_daily_report_fields(report, data)
    else:
        report = DailyReport(user_id=current_user.id)
        _apply_daily_report_fields(report, data)
        db.add(report)

    # Время фактической отправки: при переходе из черновика created_at остаётся временем создания черновика
    if not report.is_draft and getattr(report, "submitted_at", None) is None:
        report.submitted_at = datetime.now(timezone.utc)

    db.flush()
    # Расчётный остаток всегда с сервера (как в форме), чтобы список не расходился с карточкой.
    report.ost = _computed_report_ost(
        data, db=db, user_id=report.user_id, exclude_report_id=report.id if not data.is_draft else None
    )
    if not report.is_draft:
        _apply_withholding_details_delta(
            db,
            current_user.id,
            getattr(data, "withholding_details", None) or [],
            prev_withholding_details,
            closed_by_user_id=current_user.id,
            report_id=report.id,
        )

    db.commit()
    db.refresh(report)
    wh_name = ""
    if report.warehouse_id:
        wh = db.query(Warehouse).filter(Warehouse.id == report.warehouse_id).first()
        if wh:
            wh_name = wh.name
    return _report_to_response(report, wh_name, current_user.username)


@router.get("/draft", response_model=Optional[DailyReportResponse])
def get_my_draft(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Получить текущий черновик отчёта пользователя."""
    if not _is_consultant(current_user):
        raise HTTPException(status_code=403, detail="Доступно только для группы «Консультанты»")

    draft = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.warehouse), joinedload(DailyReport.user))
        .filter(DailyReport.user_id == current_user.id, DailyReport.is_draft.is_(True))
        .order_by(DailyReport.created_at.desc())
        .first()
    )
    if draft is None:
        return None
    return _report_to_response(draft)


_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _report_moscow_date_expr():
    """Календарный день отчёта в Europe/Moscow (как на фронте reportBusinessDayYmd)."""
    ts = func.coalesce(DailyReport.submitted_at, DailyReport.created_at)
    return func.date(func.timezone("Europe/Moscow", ts))


def _apply_report_date_range_filter(q, date_from: str | None, date_to: str | None):
    if not date_from or not date_to:
        return q
    if not _YMD_RE.match(date_from) or not _YMD_RE.match(date_to):
        return q
    d_from = date_type.fromisoformat(date_from)
    d_to = date_type.fromisoformat(date_to)
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    moscow_date = _report_moscow_date_expr()
    return q.filter(moscow_date >= d_from, moscow_date <= d_to)


def _expense_seller_display(u: User | None) -> str:
    """ФИО или логин автора сменного отчёта (продавец)."""
    if u is None:
        return "—"
    parts = [u.last_name, u.first_name]
    s = " ".join(p.strip() for p in parts if p and str(p).strip())
    return s or (u.username or "").strip() or "—"


def _report_calendar_date_js(r: DailyReport, timezone_offset_minutes: int) -> date_type | None:
    """Календарный день отчёта как в списке отчётов: сначала момент отправки, иначе дата создания (черновик/старые записи)."""
    dt = r.submitted_at or r.created_at
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc_naive = dt.astimezone(timezone.utc).replace(tzinfo=None)
    local_naive = utc_naive - timedelta(minutes=timezone_offset_minutes)
    return local_naive.date()


def _parse_optional_warehouse_id_param(raw: str | None) -> int | None:
    """Пустая строка в query (?warehouse_id=) иначе даёт 422 при int | None в FastAPI."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный warehouse_id")


@router.get("/expenses-summary", response_model=ExpenseSummaryResponse)
@router.get("/summary/expenses", response_model=ExpenseSummaryResponse)
def expenses_summary(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    warehouse_id: str | None = Query(None, description="Точка (склад); без параметра — все точки"),
    timezone_offset_minutes: int = Query(
        -180,
        ge=-840,
        le=840,
        description="Date.getTimezoneOffset() в браузере (для совпадения дат с таблицей отчётов)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сводка расходов по статьям справочника за период; те же правила доступа, что у списка отчётов."""
    warehouse_id_int = _parse_optional_warehouse_id_param(warehouse_id)
    if not _YMD_RE.match(date_from) or not _YMD_RE.match(date_to):
        raise HTTPException(status_code=400, detail="Некорректный формат даты (ожидается YYYY-MM-DD)")
    d_from = date_type.fromisoformat(date_from)
    d_to = date_type.fromisoformat(date_to)
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    q = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.warehouse), joinedload(DailyReport.user))
        .filter(DailyReport.is_draft.is_(False))
    )
    if not is_admin(current_user) and not is_manager(current_user):
        q = q.filter(DailyReport.user_id == current_user.id)
    if warehouse_id_int is not None:
        q = q.filter(DailyReport.warehouse_id == warehouse_id_int)

    reports = q.all()

    articles = db.query(ExpenseArticle).order_by(ExpenseArticle.name).all()
    id_to_name: dict[int, str] = {a.id: a.name for a in articles}

    totals: dict[int, float] = defaultdict(float)
    detail_rows: list[ExpenseDetailRow] = []
    for r in reports:
        ds = _report_calendar_date_js(r, timezone_offset_minutes)
        if ds is None or ds < d_from or ds > d_to:
            continue
        if not r.has_expenses:
            continue
        wh_name = ""
        if r.warehouse is not None:
            wh_name = (r.warehouse.name or "").strip()
        if not wh_name:
            wh_name = f"Точка #{r.warehouse_id}" if r.warehouse_id else "—"
        seller = _expense_seller_display(r.user)

        for row in _safe_expenses_rows(r.expenses):
            eid = row.get("expense_article_id")
            if eid is None:
                continue
            try:
                eid_i = int(eid)
            except (TypeError, ValueError):
                continue
            try:
                amt = float(row.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            totals[eid_i] += amt
            art_name = id_to_name.get(eid_i, f"Неизвестная статья (id {eid_i})")
            detail_rows.append(
                ExpenseDetailRow(
                    expense_article_id=eid_i,
                    expense_article_name=art_name,
                    amount=round(amt, 2),
                    warehouse_name=wh_name,
                    report_date=ds.isoformat(),
                    seller_name=seller,
                )
            )

    detail_rows.sort(
        key=lambda x: (
            x.report_date,
            x.warehouse_name.lower(),
            x.seller_name.lower(),
            x.expense_article_name.lower(),
        )
    )
    known_ids = {a.id for a in articles}
    rows_out: list[ExpenseSummaryRow] = [
        ExpenseSummaryRow(
            expense_article_id=a.id,
            expense_article_name=a.name,
            total_amount=round(totals.get(a.id, 0.0), 2),
        )
        for a in articles
    ]
    for eid, total in sorted(totals.items(), key=lambda x: x[0]):
        if eid not in known_ids:
            rows_out.append(
                ExpenseSummaryRow(
                    expense_article_id=eid,
                    expense_article_name=f"Неизвестная статья (id {eid})",
                    total_amount=round(total, 2),
                )
            )

    grand = round(sum(totals.values()), 2)
    return ExpenseSummaryResponse(
        date_from=d_from.isoformat(),
        date_to=d_to.isoformat(),
        rows=rows_out,
        grand_total=grand,
        detail_rows=detail_rows,
    )


@router.get("/summary/encashment", response_model=EncashmentSummaryResponse)
def encashment_summary(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    warehouse_id: str | None = Query(None, description="Точка (склад); без параметра — все точки"),
    timezone_offset_minutes: int = Query(
        -180,
        ge=-840,
        le=840,
        description="Date.getTimezoneOffset() в браузере (для совпадения дат с таблицей отчётов)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сводка инкассации (нал / безнал) по точкам за период; те же правила доступа, что у списка отчётов."""
    warehouse_id_int = _parse_optional_warehouse_id_param(warehouse_id)
    if not _YMD_RE.match(date_from) or not _YMD_RE.match(date_to):
        raise HTTPException(status_code=400, detail="Некорректный формат даты (ожидается YYYY-MM-DD)")
    d_from = date_type.fromisoformat(date_from)
    d_to = date_type.fromisoformat(date_to)
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    q = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.warehouse), joinedload(DailyReport.user))
        .filter(DailyReport.is_draft.is_(False))
    )
    if not is_admin(current_user) and not is_manager(current_user):
        q = q.filter(DailyReport.user_id == current_user.id)
    if warehouse_id_int is not None:
        q = q.filter(DailyReport.warehouse_id == warehouse_id_int)

    reports = q.all()

    for r in reports:
        ds = _report_calendar_date_js(r, timezone_offset_minutes)
        if ds is None or ds < d_from or ds > d_to:
            continue
        if not r.has_encashment or r.warehouse_id is None:
            continue
    grouped: dict[int, dict] = {}
    for r in reports:
        ds = _report_calendar_date_js(r, timezone_offset_minutes)
        if ds is None or ds < d_from or ds > d_to:
            continue
        if not r.has_encashment or r.warehouse_id is None:
            continue
        wid = r.warehouse_id
        wh_name = (r.warehouse.name or "").strip() if r.warehouse is not None else ""
        nal = round(float(r.encashment_nal or 0), 2)
        bn = round(float(r.encashment_bn or 0), 2)
        seller = _expense_seller_display(r.user)
        bucket = grouped.get(wid)
        if bucket is None:
            bucket = {
                "warehouse_id": wid,
                "warehouse_name": wh_name if wh_name else f"Точка #{wid}",
                "total_nal": 0.0,
                "total_bn": 0.0,
                "report_dates": set(),
                "seller_names": set(),
                "report_items": [],
            }
            grouped[wid] = bucket
        bucket["total_nal"] += nal
        bucket["total_bn"] += bn
        bucket["report_dates"].add(ds.isoformat())
        if seller:
            bucket["seller_names"].add(seller)
        bucket["report_items"].append(
            EncashmentReportItem(
                report_id=int(r.id),
                report_date=ds.isoformat(),
                seller_name=seller,
                nal=nal,
                bn=bn,
                total=round(nal + bn, 2),
            )
        )

    rows_out: list[EncashmentSummaryRow] = []
    for item in grouped.values():
        report_items = sorted(
            item["report_items"],
            key=lambda x: (x.report_date, x.report_id),
        )
        rows_out.append(
            EncashmentSummaryRow(
                report_id=report_items[0].report_id if len(report_items) == 1 else None,
                warehouse_id=item["warehouse_id"],
                warehouse_name=item["warehouse_name"],
                total_nal=round(float(item["total_nal"]), 2),
                total_bn=round(float(item["total_bn"]), 2),
                total=round(float(item["total_nal"]) + float(item["total_bn"]), 2),
                report_dates=sorted(item["report_dates"]),
                seller_names=sorted(item["seller_names"]),
                report_items=report_items,
            )
        )

    rows_out.sort(
        key=lambda x: (
            x.report_dates[0] if x.report_dates else "9999-99-99",
            x.warehouse_name.casefold(),
            x.warehouse_id,
        )
    )

    receipts_map: dict[int, EncashmentReceipt] = {}
    if rows_out:
        wids = [r.warehouse_id for r in rows_out]
        recs = (
            db.query(EncashmentReceipt)
            .options(joinedload(EncashmentReceipt.received_by))
            .filter(
                EncashmentReceipt.period_from == d_from,
                EncashmentReceipt.period_to == d_to,
                EncashmentReceipt.warehouse_id.in_(wids),
            )
            .all()
        )
        for rec in recs:
            receipts_map[rec.warehouse_id] = rec

    def _encashment_receiver_name(u: User | None) -> str | None:
        if u is None:
            return None
        parts = [u.last_name, u.first_name]
        s = " ".join(p.strip() for p in parts if p and str(p).strip())
        return s or u.username

    rows_enriched: list[EncashmentSummaryRow] = []
    for r in rows_out:
        rec = receipts_map.get(r.warehouse_id)
        rows_enriched.append(
            EncashmentSummaryRow(
                report_id=r.report_id,
                warehouse_id=r.warehouse_id,
                warehouse_name=r.warehouse_name,
                total_nal=r.total_nal,
                total_bn=r.total_bn,
                total=r.total,
                report_dates=r.report_dates,
                seller_names=r.seller_names,
                received=rec is not None,
                received_at=rec.received_at.isoformat() if rec and rec.received_at else None,
                received_by_name=_encashment_receiver_name(rec.received_by) if rec else None,
            )
        )

    g_nal = round(sum(r.total_nal for r in rows_enriched), 2)
    g_bn = round(sum(r.total_bn for r in rows_enriched), 2)
    g_all = round(g_nal + g_bn, 2)
    return EncashmentSummaryResponse(
        date_from=d_from.isoformat(),
        date_to=d_to.isoformat(),
        rows=rows_enriched,
        grand_total_nal=g_nal,
        grand_total_bn=g_bn,
        grand_total=g_all,
    )


def _require_admin_or_manager_encashment(user: User) -> None:
    if not is_admin(user) and not is_manager(user):
        raise HTTPException(status_code=403, detail="Доступ только для администратора или менеджера")


@router.post("/encashment/received", status_code=201)
def mark_encashment_received(
    data: EncashmentReceiptMarkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отметить инкассацию по точке за период как полученную (повторное нажатие обновляет дату и автора)."""
    _require_admin_or_manager_encashment(current_user)
    if not _YMD_RE.match(data.date_from) or not _YMD_RE.match(data.date_to):
        raise HTTPException(status_code=400, detail="Некорректный формат даты (ожидается YYYY-MM-DD)")
    d_from = date_type.fromisoformat(data.date_from)
    d_to = date_type.fromisoformat(data.date_to)
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    wh = db.query(Warehouse).filter(Warehouse.id == data.warehouse_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Точка не найдена")
    existing = (
        db.query(EncashmentReceipt)
        .filter(
            EncashmentReceipt.warehouse_id == data.warehouse_id,
            EncashmentReceipt.period_from == d_from,
            EncashmentReceipt.period_to == d_to,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing:
        existing.received_at = now
        existing.received_by_user_id = current_user.id
    else:
        db.add(
            EncashmentReceipt(
                warehouse_id=data.warehouse_id,
                period_from=d_from,
                period_to=d_to,
                received_at=now,
                received_by_user_id=current_user.id,
            )
        )
    db.commit()
    return {"ok": True}


@router.delete("/encashment/received", status_code=204)
def unmark_encashment_received(
    warehouse_id: int = Query(..., description="ID точки"),
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Снять отметку «получено»."""
    _require_admin_or_manager_encashment(current_user)
    if not _YMD_RE.match(date_from) or not _YMD_RE.match(date_to):
        raise HTTPException(status_code=400, detail="Некорректный формат даты (ожидается YYYY-MM-DD)")
    d_from = date_type.fromisoformat(date_from)
    d_to = date_type.fromisoformat(date_to)
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    obj = (
        db.query(EncashmentReceipt)
        .filter(
            EncashmentReceipt.warehouse_id == warehouse_id,
            EncashmentReceipt.period_from == d_from,
            EncashmentReceipt.period_to == d_to,
        )
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Отметка не найдена")
    db.delete(obj)
    db.commit()
    return None


def _ost_for_next_shift_utro(r: DailyReport | None) -> float | None:
    """Значение для подстановки «утро» на следующую смену: приоритет у ost_fact, иначе расчётный ost."""
    if not r:
        return None
    of = getattr(r, "ost_fact", None)
    if of is not None:
        return float(of)
    o = getattr(r, "ost", None)
    return float(o) if o is not None else None


@router.get("/warehouse/{warehouse_id}/last-ost", response_model=WarehouseLastOstResponse)
def get_warehouse_last_ost(
    warehouse_id: int,
    before_report_id: int | None = Query(
        None,
        description="Предыдущий сменный отчёт перед этим id (остаток на конец предыдущей смены = «утро должно» в карточке при редактировании).",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Для формы отчёта: подтянуть остаток для «утро» с последнего отчёта по складу.

    Используется ost_fact, если заполнен, иначе расчётный ost.
    Без before_report_id — с самого свежего отчёта (новая смена).
    С before_report_id — отчёт, который в хронологии идёт сразу перед указанным (как в таблице /reports).
    """
    if not _is_consultant(current_user) and not is_admin(current_user) and not is_manager(current_user):
        raise HTTPException(status_code=403, detail="Доступно только для консультантов")

    if before_report_id is not None:
        cur = db.query(DailyReport).filter(DailyReport.id == before_report_id).first()
        if not cur:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        if cur.warehouse_id != warehouse_id:
            raise HTTPException(status_code=400, detail="Указанный отчёт относится к другой точке")
        if cur.is_draft:
            raise HTTPException(status_code=400, detail="Черновик недопустим")
        cur_t = getattr(cur, "submitted_at", None) or cur.created_at
        if cur_t is None:
            raise HTTPException(status_code=400, detail="У отчёта нет даты отправки/создания")
        tcol = func.coalesce(DailyReport.submitted_at, DailyReport.created_at)
        prev = (
            db.query(DailyReport)
            .filter(
                DailyReport.warehouse_id == warehouse_id,
                DailyReport.is_draft.is_(False),
                or_(
                    tcol < cur_t,
                    and_(tcol == cur_t, DailyReport.id < before_report_id),
                ),
            )
            .order_by(tcol.desc(), DailyReport.id.desc())
            .first()
        )
        last_at = None
        if prev:
            last_at = getattr(prev, "submitted_at", None) or prev.created_at
        return WarehouseLastOstResponse(
            warehouse_id=warehouse_id,
            ost=_ost_for_next_shift_utro(prev),
            last_report_created_at=last_at,
        )

    last = (
        db.query(DailyReport)
        .filter(DailyReport.warehouse_id == warehouse_id, DailyReport.is_draft.is_(False))
        .order_by(func.coalesce(DailyReport.submitted_at, DailyReport.created_at).desc())
        .first()
    )
    last_at = None
    if last:
        last_at = getattr(last, "submitted_at", None) or last.created_at
    return WarehouseLastOstResponse(
        warehouse_id=warehouse_id,
        ost=_ost_for_next_shift_utro(last),
        last_report_created_at=last_at,
    )


@router.get("/consultants", response_model=list[ConsultantItem])
def list_consultants_for_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список консультантов для формы отчёта (доступен консультантам)."""
    if not _is_consultant(current_user) and not is_admin(current_user) and not is_manager(current_user):
        raise HTTPException(status_code=403, detail="Доступно только консультантам")

    group = db.query(Group).filter(Group.name == CONSULTANTS_GROUP_NAME).first()
    if not group:
        return []

    users = (
        db.query(User)
        .join(User.groups)
        .filter(Group.id == group.id)
        .filter(User.is_active.is_(True))
        .all()
    )

    def consultant_fio_or_username(u: User) -> str:
        parts = [
            (u.last_name or "").strip(),
            (u.first_name or "").strip(),
            (u.patronymic or "").strip(),
        ]
        fio = " ".join(p for p in parts if p)
        return fio or (u.username or "").strip()

    items = [{"id": u.id, "last_name": consultant_fio_or_username(u)} for u in users if consultant_fio_or_username(u)]
    items.sort(key=lambda x: x["last_name"].lower())
    return items


@router.get("/{report_id}", response_model=DailyReportResponse)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_or_reportnik_user),
):
    """Один отчёт для просмотра (админ/отчетники). Изменение — только для админа (PATCH)."""
    r = (
        db.query(DailyReport)
        .options(joinedload(DailyReport.user), joinedload(DailyReport.warehouse))
        .filter(DailyReport.id == report_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    if r.is_draft:
        raise HTTPException(status_code=404, detail="Черновик недоступен")
    ctx = _load_vzyala_display_context(db)
    return _report_to_response(r, vzyala_display_ctx=ctx, db=db)


@router.patch("/{report_id}", response_model=DailyReportResponse)
def update_report(
    report_id: int,
    data: DailyReportAdminPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Изменить отправленный отчёт (только администратор)."""
    report = db.query(DailyReport).filter(DailyReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    if report.is_draft:
        raise HTTPException(status_code=400, detail="Нельзя редактировать черновик этим способом")
    payload = data.model_copy(update={"is_draft": False})
    _validate_vzyala_linked_debts(db, payload, exclude_report_id=report_id)
    _validate_vzyala_cash_against_ost(db, report.user_id, payload, exclude_report_id=report_id)
    try:
        validate_revenue_breakdown(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    prev_withholding_details = _safe_withholding_details_rows(getattr(report, "withholding_details", None))
    _apply_daily_report_fields(report, payload)
    if data.created_at is not None:
        report.created_at = data.created_at
    if data.submitted_at is not None:
        report.submitted_at = data.submitted_at
    if "user_id" in data.model_fields_set:
        if data.user_id is None or data.user_id <= 0:
            raise HTTPException(status_code=400, detail="Укажите пользователя-консультанта (отправителя отчёта)")
        report.user_id = _validate_report_author_user_id(db, data.user_id)
    db.flush()
    report.ost = _computed_report_ost(
        payload, db=db, user_id=report.user_id, exclude_report_id=report.id
    )
    _apply_withholding_details_delta(
        db,
        report.user_id,
        getattr(payload, "withholding_details", None) or [],
        prev_withholding_details,
        closed_by_user_id=current_user.id,
        report_id=report.id,
    )
    db.commit()
    db.refresh(report)
    wh_name = ""
    if report.warehouse_id:
        wh = db.query(Warehouse).filter(Warehouse.id == report.warehouse_id).first()
        if wh:
            wh_name = wh.name
    user = db.query(User).filter(User.id == report.user_id).first()
    u_name = user.username if user else ""
    ctx = _load_vzyala_display_context(db)
    return _report_to_response(report, wh_name, u_name, vzyala_display_ctx=ctx, db=db)


@router.delete("/{report_id}", status_code=204)
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Удалить отчёт (только администратор)."""
    report = db.query(DailyReport).filter(DailyReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    db.delete(report)
    db.commit()
    return None


@router.get("", response_model=list[DailyReportResponse])
def list_reports(
    date_from: str | None = Query(None, description="YYYY-MM-DD, день отчёта (Europe/Moscow)"),
    date_to: str | None = Query(None, description="YYYY-MM-DD, день отчёта (Europe/Moscow)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список отчётов. Консультант видит только свои, администратор и менеджер — все."""
    q = db.query(DailyReport).options(
        joinedload(DailyReport.user),
        joinedload(DailyReport.warehouse),
    ).order_by(func.coalesce(DailyReport.submitted_at, DailyReport.created_at).desc())
    q = q.filter(DailyReport.is_draft.is_(False))
    if not is_admin(current_user) and not is_manager(current_user) and not is_reportnik(current_user):
        q = q.filter(DailyReport.user_id == current_user.id)
    q = _apply_report_date_range_filter(q, date_from, date_to)
    reports = q.all()
    ctx = _load_vzyala_display_context(db)
    return [_report_to_response(r, vzyala_display_ctx=ctx, db=None) for r in reports]
