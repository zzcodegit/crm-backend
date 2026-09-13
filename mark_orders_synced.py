from datetime import datetime

from database import SessionLocal
from models import Order


def mark_orders_synced(order_numbers: list[str]) -> None:
    """Помечает заказы как уже переданные в 1С (synced_to_1c_at ставится в текущее время)."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        (
            db.query(Order)
            .filter(Order.order_number.in_(order_numbers))
            .update({Order.synced_to_1c_at: now}, synchronize_session="fetch")
        )
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    # Список номеров заказов, которые нужно убрать из /api/order/accepted
    target_numbers = ["ORD-001"]
    mark_orders_synced(target_numbers)
    print(f"Отмечены как синхронизированные заказы: {', '.join(target_numbers)}")

