from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user, is_admin
from models import SupplyTicket, SupplyTicketMessage, User
from schemas import (
    SupplyTicketResponse,
    SupplyTicketCreate,
    SupplyTicketStatusUpdate,
    SupplyTicketMessageResponse,
    SupplyTicketMessageCreate,
)

router = APIRouter(tags=["supply-tickets"])


def _ticket_to_response(ticket: SupplyTicket) -> SupplyTicketResponse:
    return SupplyTicketResponse(
        id=ticket.id,
        warehouse_id=ticket.warehouse_id,
        warehouse_name=ticket.warehouse.name if ticket.warehouse else None,
        request_text=ticket.request_text,
        created_by_user_id=ticket.created_by_user_id,
        created_by_username=ticket.created_by.username if ticket.created_by else None,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _message_to_response(message: SupplyTicketMessage) -> SupplyTicketMessageResponse:
    return SupplyTicketMessageResponse(
        id=message.id,
        ticket_id=message.ticket_id,
        author_user_id=message.author_user_id,
        author_username=message.author.username if message.author else None,
        message=message.message,
        created_at=message.created_at,
    )


def _can_access_ticket(current_user: User, ticket: SupplyTicket) -> bool:
    return is_admin(current_user) or ticket.created_by_user_id == current_user.id


@router.get("/api/supply-tickets")
def list_supply_tickets(
    limit: int = 15,
    offset: int = 0,
    status: str = "open",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(SupplyTicket)
    if not is_admin(current_user):
        q = q.filter(SupplyTicket.created_by_user_id == current_user.id)
    status_normalized = (status or "").strip().lower()
    if status_normalized in {"open", "closed"}:
        q = q.filter(SupplyTicket.status == status_normalized)
    q = q.order_by(SupplyTicket.created_at.desc(), SupplyTicket.id.desc())
    total = q.count()
    rows = q.limit(limit).offset(offset).all()
    return {
        "items": [_ticket_to_response(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/api/supply-tickets", response_model=SupplyTicketResponse, status_code=201)
def create_supply_ticket(data: SupplyTicketCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    text = data.request_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Запрос не может быть пустым")
    ticket = SupplyTicket(
        warehouse_id=data.warehouse_id,
        request_text=text,
        created_by_user_id=current_user.id,
        status="open",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return _ticket_to_response(ticket)


@router.patch("/api/supply-tickets/{ticket_id}/status", response_model=SupplyTicketResponse)
def update_supply_ticket_status(
    ticket_id: int,
    data: SupplyTicketStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = db.query(SupplyTicket).filter(SupplyTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Тикет не найден")
    if not _can_access_ticket(current_user, ticket):
        raise HTTPException(status_code=403, detail="Нет доступа")

    next_status = (data.status or "").strip().lower()
    if next_status not in {"open", "closed"}:
        raise HTTPException(status_code=400, detail="Некорректный статус")

    ticket.status = next_status
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return _ticket_to_response(ticket)


@router.get("/api/supply-tickets/{ticket_id}/messages", response_model=list[SupplyTicketMessageResponse])
def list_supply_ticket_messages(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ticket = db.query(SupplyTicket).filter(SupplyTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Тикет не найден")
    if not _can_access_ticket(current_user, ticket):
        raise HTTPException(status_code=403, detail="Нет доступа")
    msgs = (
        db.query(SupplyTicketMessage)
        .filter(SupplyTicketMessage.ticket_id == ticket_id)
        .order_by(SupplyTicketMessage.created_at.asc(), SupplyTicketMessage.id.asc())
        .all()
    )
    return [_message_to_response(m) for m in msgs]


@router.post("/api/supply-tickets/{ticket_id}/messages", response_model=SupplyTicketMessageResponse, status_code=201)
def create_supply_ticket_message(
    ticket_id: int,
    data: SupplyTicketMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = db.query(SupplyTicket).filter(SupplyTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Тикет не найден")
    if not _can_access_ticket(current_user, ticket):
        raise HTTPException(status_code=403, detail="Нет доступа")
    text = data.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")
    msg = SupplyTicketMessage(ticket_id=ticket_id, author_user_id=current_user.id, message=text)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return _message_to_response(msg)
