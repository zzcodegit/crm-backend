"""Выплаты из центральной кассы сотрудникам (учёт для администратора)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from database import get_db
from deps import get_admin_user
from models import User, CentralCashPayout, TakenSource
from schemas import CentralCashPayoutCreate, CentralCashPayoutUpdate, CentralCashPayoutResponse

router = APIRouter(prefix="/api/central-cash-payouts", tags=["central-cash"])


def _user_display_name(u: User | None) -> str:
    if u is None:
        return ""
    parts = [u.last_name, u.first_name]
    s = " ".join(p.strip() for p in parts if p and str(p).strip())
    return s or (u.username or "").strip() or "—"


def _payout_to_response(r: CentralCashPayout) -> CentralCashPayoutResponse:
    return CentralCashPayoutResponse(
        id=r.id,
        created_at=r.created_at,
        paid_to_user_id=r.paid_to_user_id,
        paid_to_name=_user_display_name(r.paid_to),
        amount=float(r.amount),
        taken_source_id=r.taken_source_id,
        taken_source_name=(r.taken_source.name if getattr(r, "taken_source", None) else None),
        note=r.note,
        recorded_by_user_id=r.recorded_by_user_id,
        recorded_by_name=_user_display_name(r.recorded_by),
    )


def _load_payout(db: Session, payout_id: int) -> CentralCashPayout:
    row = (
        db.query(CentralCashPayout)
        .options(
            joinedload(CentralCashPayout.paid_to),
            joinedload(CentralCashPayout.recorded_by),
            joinedload(CentralCashPayout.taken_source),
        )
        .filter(CentralCashPayout.id == payout_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return row


@router.get("", response_model=list[CentralCashPayoutResponse])
def list_central_cash_payouts(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    rows = (
        db.query(CentralCashPayout)
        .options(
            joinedload(CentralCashPayout.paid_to),
            joinedload(CentralCashPayout.recorded_by),
            joinedload(CentralCashPayout.taken_source),
        )
        .order_by(CentralCashPayout.created_at.desc(), CentralCashPayout.id.desc())
        .all()
    )
    return [_payout_to_response(r) for r in rows]


@router.post("", response_model=CentralCashPayoutResponse, status_code=201)
def create_central_cash_payout(
    data: CentralCashPayoutCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")
    payee = db.query(User).filter(User.id == data.paid_to_user_id).first()
    if not payee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if not payee.is_active:
        raise HTTPException(status_code=400, detail="Нельзя выбрать деактивированного пользователя")
    if data.taken_source_id is not None:
        src = db.query(TakenSource).filter(TakenSource.id == data.taken_source_id).first()
        if not src:
            raise HTTPException(status_code=400, detail="Способ выдачи не найден")
    obj = CentralCashPayout(
        paid_to_user_id=data.paid_to_user_id,
        amount=data.amount,
        taken_source_id=data.taken_source_id,
        note=(data.note or "").strip() or None,
        recorded_by_user_id=current_user.id,
    )
    db.add(obj)
    db.commit()
    return _payout_to_response(_load_payout(db, obj.id))


@router.patch("/{payout_id}", response_model=CentralCashPayoutResponse)
def update_central_cash_payout(
    payout_id: int,
    data: CentralCashPayoutUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    row = db.query(CentralCashPayout).filter(CentralCashPayout.id == payout_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    payload = data.model_dump(exclude_unset=True)
    if "paid_to_user_id" in payload:
        payee = db.query(User).filter(User.id == int(payload["paid_to_user_id"])).first()
        if not payee:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        if not payee.is_active:
            raise HTTPException(status_code=400, detail="Нельзя выбрать деактивированного пользователя")
        row.paid_to_user_id = int(payload["paid_to_user_id"])
    if "amount" in payload:
        amt = float(payload["amount"])
        if amt <= 0:
            raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")
        row.amount = amt
    if "taken_source_id" in payload:
        tsid = payload["taken_source_id"]
        if tsid is not None:
            src = db.query(TakenSource).filter(TakenSource.id == int(tsid)).first()
            if not src:
                raise HTTPException(status_code=400, detail="Способ выдачи не найден")
            row.taken_source_id = int(tsid)
        else:
            row.taken_source_id = None
    if "note" in payload:
        note = payload["note"]
        row.note = (str(note).strip() if note is not None else "") or None
    db.commit()
    return _payout_to_response(_load_payout(db, payout_id))


@router.delete("/{payout_id}", status_code=204)
def delete_central_cash_payout(
    payout_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    row = db.query(CentralCashPayout).filter(CentralCashPayout.id == payout_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(row)
    db.commit()
    return None
