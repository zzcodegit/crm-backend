"""
Удаляет пустые заказы, ошибочно созданные из bonus_arr (1С шлёт долги на /api/order/1c-intake/).
Запуск: python cleanup_ghost_orders.py
"""
from sqlalchemy.orm import joinedload

from database import engine, SessionLocal
from models import Order


def main() -> None:
    db = SessionLocal()
    try:
        candidates = (
            db.query(Order)
            .options(joinedload(Order.items))
            .filter(
                Order.client.is_(None),
                Order.phone.is_(None),
                Order.order_number.is_(None),
                Order.total == 0,
                Order.warehouse.is_(None),
            )
            .all()
        )
        ghosts = [o for o in candidates if not (o.items or [])]
        ids = [o.id for o in ghosts]
        if not ids:
            print("OK: пустых заказов не найдено")
            return
        deleted = (
            db.query(Order)
            .filter(Order.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.commit()
        print(f"OK: удалено пустых заказов: {deleted} (в т.ч. #4108, #4109 при наличии)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
