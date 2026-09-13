"""
Создаёт тестовый заказ для проверки раздела Заказы.
Запуск: python seed_test_order.py
"""
from datetime import date
from decimal import Decimal
from database import engine, SessionLocal, Base
from models import Order, OrderItem

Base.metadata.create_all(bind=engine)
db = SessionLocal()

order = Order(
    warehouse="Склад №1",
    consultant="Иванова М.И.",
    date=date.today(),
    readiness_date=date(2025, 3, 1),
    client="Петров Сергей",
    phone="+7 (999) 123-45-67",
    order_number="ORD-001",
    total=Decimal("15900.00"),
    od_sph="-2.00",
    od_cyl="-0.50",
    od_axis="90",
    od_pd="32",
    od_add_deg="+1.50",
    od_height="22",
    os_sph="-2.25",
    os_cyl="-0.75",
    os_axis="85",
    os_pd="32",
    os_add_deg="+1.50",
    os_height="22",
    print_info="Линзы с антибликовым покрытием. Доставка до 5 рабочих дней.",
    comment="Позвонить за день до готовности.",
    status="new",
)
db.add(order)
db.flush()

items = [
    OrderItem(order_id=order.id, line_number=1, nomenclature="Оправа металлическая Classic", quantity=1, price=Decimal("4500.00"), sum=Decimal("4500.00")),
    OrderItem(order_id=order.id, line_number=2, nomenclature="Линзы однофокальные CR-39", quantity=1, price=Decimal("3400.00"), sum=Decimal("3400.00")),
    OrderItem(order_id=order.id, line_number=3, nomenclature="Покрытие антибликовое", quantity=1, price=Decimal("8000.00"), sum=Decimal("8000.00")),
]
for it in items:
    db.add(it)

db.commit()
db.refresh(order)
print(f"Тестовый заказ создан: id={order.id}, № {order.order_number}, клиент {order.client}")
db.close()
