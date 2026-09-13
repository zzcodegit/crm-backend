from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Order,
    OrderItem,
    OrderStatus,
    Priority,
    Organization,
    Department,
    Warehouse,
    Author,
    Product,
    ProductCharacteristic,
    VatRate,
)
from schemas import OrderResponse, OrderCreate, OrderUpdate, OrderItemCreate, OrderItemResponse
from deps import get_current_user, is_admin, is_manager, is_consultant
from models import User, Group

router = APIRouter(prefix="/api/orders", tags=["orders"])

MANAGER_GROUP_NAME = "Менеджер"

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _format_date_as_moscow_datetime(d: date | None) -> str | None:
    """
    БД хранит поля как `date` без времени.
    Чтобы фронт корректно отображал время без смещения (например 03:00 из-за UTC),
    возвращаем datetime-строку в таймзоне Москвы.
    """
    if d is None:
        return None
    dt = datetime.combine(d, time.min).replace(tzinfo=MOSCOW_TZ)
    return dt.isoformat()


def _normalize_name(s: str | None) -> str:
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.strip().split())


def _find_warehouse_manager_id(db: Session, name: str | None) -> int | None:
    """Ищет пользователя-менеджера по ФИО (warehouse_manager из 1С). Сравнивает «Имя Фамилия» и «Фамилия Имя»."""
    n = _normalize_name(name)
    if not n:
        return None
    managers = db.query(User).join(User.groups).filter(Group.name == MANAGER_GROUP_NAME).all()
    n_lower = n.lower()
    for u in managers:
        first = (u.first_name or "").strip()
        last = (u.last_name or "").strip()
        full1 = _normalize_name(first + " " + last)
        full2 = _normalize_name(last + " " + first) if last and first else ""
        if not full1:
            full1 = _normalize_name(u.username or "")
        if full1 and full1.lower() == n_lower:
            return u.id
        if full2 and full2.lower() == n_lower:
            return u.id
    return None


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _parse_1c_date(s: str | None) -> date | None:
    """Парсит дату из 1С вида '20.02.2026 0:00:00'."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    try:
        # DD.MM.YYYY или DD.MM.YYYY 0:00:00
        part = s.split()[0]
        day, month, year = part.split(".")
        return date(int(year), int(month), int(day))
    except (ValueError, TypeError, IndexError):
        return None


def is_1c_bonus_only_payload(payload: dict) -> bool:
    """Только выгрузка bonus_arr (долги/бонусы) — не документ заказа."""
    return isinstance(payload.get("bonus_arr"), list) and not isinstance(payload.get("stocks"), list)


def is_valid_1c_order_payload(payload: dict) -> bool:
    """Проверка, что JSON от 1С — заказ клиента, а не служебный bonus_arr."""
    if not isinstance(payload, dict):
        return False
    if is_1c_bonus_only_payload(payload):
        return False
    stocks = payload.get("stocks")
    if not isinstance(stocks, list) or len(stocks) == 0:
        return False
    return True


def create_order_from_1c(db: Session, payload: dict) -> Order:
    """Создаёт заказ в БД из JSON от 1С. Заполняет справочники (склад, статус). Комментарий только из 1С."""
    stocks = payload.get("stocks") or []
    comment = (payload.get("comment") or "").strip() or None
    print_info = (payload.get("print_info") or "").strip() or None

    warehouse_name = (payload.get("warehouse") or "").strip() or None
    order_status_id = _get_or_create_order_status(db, "Новый")
    warehouse_id = _get_or_create_warehouse(db, warehouse_name) if warehouse_name else None
    warehouse_manager_id = _find_warehouse_manager_id(db, (payload.get("warehouse_manager") or "").strip() or None)

    order = Order(
        status="new",
        order_status_id=order_status_id,
        priority_id=None,
        consultant=(payload.get("consultant") or "").strip() or None,
        order_number=(payload.get("client_number") or "").strip() or None,
        date=date.today(),  # время по серверу, не из документа 1С
        readiness_date=_parse_1c_date(payload.get("ready_date")),
        client=(payload.get("client") or "").strip() or None,
        phone=(payload.get("telnumber") or "").strip() or None,
        total=Decimal(str(payload.get("doc_sum") or 0)),
        warehouse=warehouse_name,
        warehouse_id=warehouse_id,
        warehouse_manager_id=warehouse_manager_id,
        od_sph=(payload.get("od_sph") or "").strip() or None,
        od_cyl=(payload.get("od_cyl") or "").strip() or None,
        od_axis=(payload.get("od_axis") or "").strip() or None,
        od_pd=(payload.get("od_pd") or "").strip() or None,
        od_add_deg=(payload.get("od_add_deg") or "").strip() or None,
        od_height=(payload.get("od_installation_height") or "").strip() or None,
        diametr=(payload.get("diametr") or "").strip() or None,
        os_sph=(payload.get("os_sph") or "").strip() or None,
        os_cyl=(payload.get("os_cyl") or "").strip() or None,
        os_axis=(payload.get("os_axis") or "").strip() or None,
        os_pd=(payload.get("os_pd") or "").strip() or None,
        os_add_deg=(payload.get("os_add_deg") or "").strip() or None,
        os_height=(payload.get("os_installation_height") or "").strip() or None,
        print_info=print_info,
        comment=comment,
    )
    db.add(order)
    db.flush()

    # Заполняем менеджера склада в справочнике warehouses при обмене с 1С
    if warehouse_id and warehouse_manager_id:
        wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        if wh:
            wh.manager_id = warehouse_manager_id

    for i, row in enumerate(stocks):
        line_number = int(row.get("product_string_number") or i + 1)
        nomenclature = (row.get("product") or "").strip() or None
        quantity = Decimal(str(row.get("product_quantity") or 0))
        price = Decimal(str(row.get("product_price") or 0))
        sum_val = Decimal(str(row.get("product_sum") or 0))
        item = OrderItem(
            order_id=order.id,
            line_number=line_number,
            nomenclature=nomenclature,
            quantity=quantity,
            price=price,
            sum=sum_val,
        )
        db.add(item)

    db.commit()
    db.refresh(order)
    return order


def _order_to_response(order: Order) -> OrderResponse:
    """Собирает OrderResponse из Order с подгрузкой имён справочников."""
    os_rel = order.order_status_rel
    pr_rel = order.priority_rel
    org_rel = order.organization_rel
    dep_rel = order.department_rel
    wh_rel = order.warehouse_rel
    auth_rel = order.author_rel

    items_data = []
    for it in order.items:
        items_data.append(
            OrderItemResponse(
                id=it.id,
                order_id=it.order_id,
                line_number=it.line_number or 1,
                product_id=it.product_id,
                characteristic_id=it.characteristic_id,
                nomenclature=it.nomenclature,
                quantity=float(it.quantity or 0),
                price=float(it.price or 0),
                percent_manual=float(it.percent_manual) if it.percent_manual is not None else None,
                sum_manual=float(it.sum_manual) if it.sum_manual is not None else None,
                sum=float(it.sum or 0),
                vat_rate_id=it.vat_rate_id,
                product_name=it.product_rel.name if it.product_rel else None,
                characteristic_name=it.characteristic_rel.name if it.characteristic_rel else None,
                vat_rate_name=it.vat_rate_rel.name if it.vat_rate_rel else None,
            )
        )

    return OrderResponse(
        id=order.id,
        status=order.status,
        order_status_id=order.order_status_id,
        order_status_name=os_rel.name if os_rel else None,
        priority_id=order.priority_id,
        priority_name=pr_rel.name if pr_rel else None,
        consultant_id=order.consultant_id,
        consultant=order.consultant,
        order_number=order.order_number,
        date=_format_date_as_moscow_datetime(order.date),
        readiness_date=_format_date_as_moscow_datetime(order.readiness_date),
        client_id=order.client_id,
        client=order.client,
        age=order.age,
        phone=order.phone,
        sms=order.sms or False,
        call=order.call,
        prepayment=float(order.prepayment) if order.prepayment is not None else None,
        card=order.card or False,
        cash=order.cash or False,
        extra_payment=float(order.extra_payment) if order.extra_payment is not None else None,
        od_sph=order.od_sph,
        od_cyl=order.od_cyl,
        od_axis=order.od_axis,
        od_pd=order.od_pd,
        od_add_deg=order.od_add_deg,
        od_height=order.od_height,
        diametr=order.diametr,
        os_sph=order.os_sph,
        os_cyl=order.os_cyl,
        os_axis=order.os_axis,
        os_pd=order.os_pd,
        os_add_deg=order.os_add_deg,
        os_height=order.os_height,
        for_what=order.for_what,
        frame_article=order.frame_article,
        print_info=order.print_info,
        promotion=order.promotion or False,
        prescription_order=order.prescription_order or False,
        child_order=order.child_order or False,
        no_lenses=order.no_lenses or False,
        client_frame_lenses=order.client_frame_lenses or False,
        case_included=order.case_included or False,
        from_client_words=order.from_client_words or False,
        doctor_prescription=order.doctor_prescription or False,
        doctor_name=order.doctor_name,
        clinic=order.clinic,
        by_client_glasses=order.by_client_glasses or False,
        demo_mo=order.demo_mo or False,
        price_includes_vat=order.price_includes_vat or False,
        organization_id=order.organization_id,
        organization_name=org_rel.name if org_rel else None,
        department_id=order.department_id,
        department_name=dep_rel.name if dep_rel else None,
        warehouse=order.warehouse,
        warehouse_id=order.warehouse_id,
        warehouse_name=wh_rel.name if wh_rel else None,
        author_id=order.author_id,
        author_name=auth_rel.name if auth_rel else None,
        ship_one_date=order.ship_one_date or False,
        ship_date=_format_date_as_moscow_datetime(order.ship_date),
        total=float(order.total or 0),
        comment=order.comment,
        created_at=order.created_at,
        items=items_data,
    )


def _get_or_create_order_status(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    obj = db.query(OrderStatus).filter(OrderStatus.name == name).first()
    if obj:
        return obj.id
    obj = OrderStatus(name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _get_or_create_priority(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    obj = db.query(Priority).filter(Priority.name == name).first()
    if obj:
        return obj.id
    obj = Priority(name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _get_or_create_organization(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    obj = db.query(Organization).filter(Organization.name == name).first()
    if obj:
        return obj.id
    obj = Organization(name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _get_or_create_department(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    obj = db.query(Department).filter(Department.name == name).first()
    if obj:
        return obj.id
    obj = Department(name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _get_or_create_warehouse(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    obj = db.query(Warehouse).filter(Warehouse.name == name).first()
    if obj:
        return obj.id
    obj = Warehouse(name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _get_or_create_author(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    obj = db.query(Author).filter(Author.name == name).first()
    if obj:
        return obj.id
    obj = Author(name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _get_or_create_product(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    obj = db.query(Product).filter(Product.name == name).first()
    if obj:
        return obj.id
    obj = Product(name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _get_or_create_product_characteristic(db: Session, product_id: int, name: str | None) -> int | None:
    if not name or not product_id:
        return None
    obj = db.query(ProductCharacteristic).filter(
        ProductCharacteristic.product_id == product_id,
        ProductCharacteristic.name == name,
    ).first()
    if obj:
        return obj.id
    obj = ProductCharacteristic(product_id=product_id, name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _get_or_create_vat_rate(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    obj = db.query(VatRate).filter(VatRate.name == name).first()
    if obj:
        return obj.id
    obj = VatRate(name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _resolve_order_refs(db: Session, data: OrderCreate | OrderUpdate):
    """Возвращает dict с id для справочников заказа (order_status_id, priority_id, ...)."""
    out = {}
    if getattr(data, "order_status_id", None) is not None:
        out["order_status_id"] = data.order_status_id
    elif getattr(data, "order_status_name", None):
        out["order_status_id"] = _get_or_create_order_status(db, data.order_status_name)

    if getattr(data, "priority_id", None) is not None:
        out["priority_id"] = data.priority_id
    elif getattr(data, "priority_name", None):
        out["priority_id"] = _get_or_create_priority(db, data.priority_name)

    if getattr(data, "organization_id", None) is not None:
        out["organization_id"] = data.organization_id
    elif getattr(data, "organization_name", None):
        out["organization_id"] = _get_or_create_organization(db, data.organization_name)

    if getattr(data, "department_id", None) is not None:
        out["department_id"] = data.department_id
    elif getattr(data, "department_name", None):
        out["department_id"] = _get_or_create_department(db, data.department_name)

    if getattr(data, "warehouse_id", None) is not None:
        out["warehouse_id"] = data.warehouse_id
    elif getattr(data, "warehouse_name", None):
        out["warehouse_id"] = _get_or_create_warehouse(db, data.warehouse_name)

    if getattr(data, "author_id", None) is not None:
        out["author_id"] = data.author_id
    elif getattr(data, "author_name", None):
        out["author_id"] = _get_or_create_author(db, data.author_name)

    return out


LIMIT_ORDERS = 50


@router.get("")
def list_orders(
    status_filter: str | None = Query(None, description="new | accepted | all"),
    limit: int = Query(LIMIT_ORDERS, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Order).order_by(Order.created_at.desc())
    if is_consultant(current_user) and not is_admin(current_user) and not is_manager(current_user):
        q = q.filter(Order.consultant_id == current_user.id)
    elif is_manager(current_user) and not is_admin(current_user):
        q = q.filter(Order.warehouse_manager_id == current_user.id)
    if status_filter == "new":
        q = q.filter(Order.status == "new")
    elif status_filter == "accepted":
        q = q.filter(Order.status == "accepted")
    orders = q.offset(offset).limit(limit + 1).all()
    has_more = len(orders) > limit
    if has_more:
        orders = orders[:limit]
    return {"items": [_order_to_response(o) for o in orders], "has_more": has_more}


@router.post("", response_model=OrderResponse, status_code=201)
def create_order(
    data: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    refs = _resolve_order_refs(db, data)

    order = Order(
        status="new",
        order_status_id=refs.get("order_status_id"),
        priority_id=refs.get("priority_id"),
        consultant_id=getattr(data, "consultant_id", None),
        consultant=data.consultant,
        order_number=data.order_number,
        date=_parse_date(data.date) if isinstance(getattr(data, "date", None), str) else getattr(data, "date", None),
        readiness_date=_parse_date(data.readiness_date) if isinstance(getattr(data, "readiness_date", None), str) else getattr(data, "readiness_date", None),
        client_id=getattr(data, "client_id", None),
        client=data.client,
        age=data.age,
        phone=data.phone,
        sms=data.sms,
        call=data.call,
        prepayment=data.prepayment,
        card=data.card,
        cash=data.cash,
        extra_payment=data.extra_payment,
        od_sph=data.od_sph,
        od_cyl=data.od_cyl,
        od_axis=data.od_axis,
        od_pd=data.od_pd,
        od_add_deg=data.od_add_deg,
        od_height=data.od_height,
        os_sph=data.os_sph,
        os_cyl=data.os_cyl,
        os_axis=data.os_axis,
        os_pd=data.os_pd,
        os_add_deg=data.os_add_deg,
        os_height=data.os_height,
        for_what=data.for_what,
        frame_article=data.frame_article,
        print_info=data.print_info,
        promotion=data.promotion,
        prescription_order=data.prescription_order,
        child_order=data.child_order,
        no_lenses=data.no_lenses,
        client_frame_lenses=data.client_frame_lenses,
        case_included=data.case_included,
        from_client_words=data.from_client_words,
        doctor_prescription=data.doctor_prescription,
        doctor_name=data.doctor_name,
        clinic=data.clinic,
        by_client_glasses=data.by_client_glasses,
        demo_mo=data.demo_mo,
        price_includes_vat=data.price_includes_vat,
        organization_id=refs.get("organization_id"),
        department_id=refs.get("department_id"),
        warehouse=data.warehouse,
        warehouse_id=refs.get("warehouse_id"),
        author_id=refs.get("author_id"),
        ship_one_date=data.ship_one_date,
        ship_date=_parse_date(data.ship_date) if isinstance(getattr(data, "ship_date", None), str) else getattr(data, "ship_date", None),
        total=data.total or 0,
        comment=data.comment,
    )
    db.add(order)
    db.flush()

    for it in data.items:
        product_id = it.product_id
        if product_id is None and it.product_name:
            product_id = _get_or_create_product(db, it.product_name)
        characteristic_id = it.characteristic_id
        if characteristic_id is None and it.characteristic_name and product_id:
            characteristic_id = _get_or_create_product_characteristic(db, product_id, it.characteristic_name)
        vat_rate_id = it.vat_rate_id
        if vat_rate_id is None and it.vat_rate_name:
            vat_rate_id = _get_or_create_vat_rate(db, it.vat_rate_name)

        item = OrderItem(
            order_id=order.id,
            line_number=it.line_number,
            product_id=product_id,
            characteristic_id=characteristic_id,
            nomenclature=it.nomenclature,
            quantity=it.quantity,
            price=it.price,
            percent_manual=it.percent_manual,
            sum_manual=it.sum_manual,
            sum=it.sum,
            vat_rate_id=vat_rate_id,
        )
        db.add(item)

    db.commit()
    db.refresh(order)
    return _order_to_response(order)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if is_consultant(current_user) and not is_admin(current_user) and not is_manager(current_user):
        if order.consultant_id != current_user.id:
            raise HTTPException(status_code=404, detail="Заказ не найден")
    elif is_manager(current_user) and not is_admin(current_user):
        if order.warehouse_manager_id != current_user.id:
            raise HTTPException(status_code=404, detail="Заказ не найден")
    return _order_to_response(order)


@router.patch("/{order_id}/accept", response_model=OrderResponse)
def accept_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if is_consultant(current_user) and not is_admin(current_user) and not is_manager(current_user):
        if order.consultant_id != current_user.id:
            raise HTTPException(status_code=404, detail="Заказ не найден")
    elif is_manager(current_user) and not is_admin(current_user):
        if order.warehouse_manager_id != current_user.id:
            raise HTTPException(status_code=404, detail="Заказ не найден")
    order.status = "accepted"
    db.commit()
    db.refresh(order)
    return _order_to_response(order)


def _apply_order_update(order: Order, data: OrderUpdate, refs: dict):
    """Применяет поля OrderUpdate к order. refs — результат _resolve_order_refs."""
    if data.order_status_name is not None or "order_status_id" in refs:
        order.order_status_id = refs.get("order_status_id")
    if data.priority_name is not None or "priority_id" in refs:
        order.priority_id = refs.get("priority_id")
    if data.consultant is not None:
        order.consultant = data.consultant
    if data.order_number is not None:
        order.order_number = data.order_number
    if data.date is not None:
        order.date = _parse_date(data.date) if isinstance(data.date, str) else data.date
    if data.readiness_date is not None:
        order.readiness_date = _parse_date(data.readiness_date) if isinstance(data.readiness_date, str) else data.readiness_date
    if data.client is not None:
        order.client = data.client
    if data.age is not None:
        order.age = data.age
    if data.phone is not None:
        order.phone = data.phone
    if data.sms is not None:
        order.sms = data.sms
    if data.call is not None:
        order.call = data.call
    if data.prepayment is not None:
        order.prepayment = data.prepayment
    if data.card is not None:
        order.card = data.card
    if data.cash is not None:
        order.cash = data.cash
    if data.extra_payment is not None:
        order.extra_payment = data.extra_payment
    for attr in ["od_sph", "od_cyl", "od_axis", "od_pd", "od_add_deg", "od_height",
                 "os_sph", "os_cyl", "os_axis", "os_pd", "os_add_deg", "os_height",
                 "for_what", "frame_article", "print_info", "promotion", "prescription_order",
                 "child_order", "no_lenses", "client_frame_lenses", "case_included",
                 "from_client_words", "doctor_prescription", "doctor_name", "clinic",
                 "by_client_glasses", "demo_mo", "price_includes_vat",
                 "ship_one_date", "total", "comment"]:
        v = getattr(data, attr, None)
        if v is not None:
            setattr(order, attr, v)
    if data.ship_date is not None:
        order.ship_date = _parse_date(data.ship_date) if isinstance(data.ship_date, str) else data.ship_date
    if data.organization_name is not None or "organization_id" in refs:
        order.organization_id = refs.get("organization_id")
    if data.department_name is not None or "department_id" in refs:
        order.department_id = refs.get("department_id")
    if data.warehouse_name is not None or "warehouse_id" in refs:
        order.warehouse_id = refs.get("warehouse_id")
    if data.warehouse is not None:
        order.warehouse = data.warehouse
    if data.author_name is not None or "author_id" in refs:
        order.author_id = refs.get("author_id")


@router.patch("/{order_id}", response_model=OrderResponse)
def update_order(
    order_id: int,
    data: OrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if is_consultant(current_user) and not is_admin(current_user) and not is_manager(current_user):
        if order.consultant_id != current_user.id:
            raise HTTPException(status_code=404, detail="Заказ не найден")
    elif is_manager(current_user) and not is_admin(current_user):
        if order.warehouse_manager_id != current_user.id:
            raise HTTPException(status_code=404, detail="Заказ не найден")

    refs = _resolve_order_refs(db, data)
    _apply_order_update(order, data, refs)

    if data.items is not None:
        for existing in order.items:
            db.delete(existing)
        for it in data.items:
            product_id = it.product_id
            if product_id is None and it.product_name:
                product_id = _get_or_create_product(db, it.product_name)
            characteristic_id = it.characteristic_id
            if characteristic_id is None and it.characteristic_name and product_id:
                characteristic_id = _get_or_create_product_characteristic(db, product_id, it.characteristic_name)
            vat_rate_id = it.vat_rate_id
            if vat_rate_id is None and it.vat_rate_name:
                vat_rate_id = _get_or_create_vat_rate(db, it.vat_rate_name)

            item = OrderItem(
                order_id=order.id,
                line_number=it.line_number,
                product_id=product_id,
                characteristic_id=characteristic_id,
                nomenclature=it.nomenclature,
                quantity=it.quantity,
                price=it.price,
                percent_manual=it.percent_manual,
                sum_manual=it.sum_manual,
                sum=it.sum,
                vat_rate_id=vat_rate_id,
            )
            db.add(item)

    db.commit()
    db.refresh(order)
    return _order_to_response(order)


@router.delete("/{order_id}", status_code=204)
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if is_consultant(current_user) and not is_admin(current_user) and not is_manager(current_user):
        if order.consultant_id != current_user.id:
            raise HTTPException(status_code=404, detail="Заказ не найден")
    elif is_manager(current_user) and not is_admin(current_user):
        if order.warehouse_manager_id != current_user.id:
            raise HTTPException(status_code=404, detail="Заказ не найден")
    db.delete(order)
    db.commit()
    return None
