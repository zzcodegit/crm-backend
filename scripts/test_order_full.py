#!/usr/bin/env python3
"""
Тест: создание заказа с полным набором полей по именам справочников,
проверка GET и что в справочниках создались записи.

Запуск из корня crm-backend (БД должна быть доступна):

  1) Сначала поднять API в отдельном терминале:
     cd /home/crm-backend && . venv/bin/activate && uvicorn main:app --host 127.0.0.1 --port 8000

  2) Затем запустить тест:
     python scripts/test_order_full.py

  Либо если API уже доступен по другому адресу (например через nginx):
     API_BASE=http://155.212.143.145 python scripts/test_order_full.py
"""
import os
import sys
import urllib.request
import urllib.error
import json

API = os.environ.get("API_BASE", "http://127.0.0.1:8000")
REQUEST_TIMEOUT = 10


def request(method: str, path: str, body: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
            if r.status in (200, 201):
                return json.loads(r.read().decode())
            return None
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}")
        raise
    except (TimeoutError, OSError) as e:
        print(f"\nОшибка соединения с API ({API}): {e}")
        print("Убедитесь, что бэкенд запущен:")
        print("  uvicorn main:app --host 127.0.0.1 --port 8000")
        print("Или укажите URL: API_BASE=http://155.212.143.145 python scripts/test_order_full.py")
        sys.exit(1)
    except Exception as e:
        print(e)
        raise


def main():
    print("1. Логин...")
    login = request("POST", "/api/auth/login", {"username": "admin", "password": "Dsaik098x_"})
    token = login["access_token"]
    print("   OK")

    payload = {
        "order_status_name": "ТестСтатус",
        "priority_name": "ТестПриоритет",
        "consultant": "Консультант Тест",
        "order_number": "T-001",
        "date": "2025-02-15",
        "readiness_date": "2025-02-20",
        "client": "Клиент Тест",
        "age": 30,
        "phone": "+7 999 000-00-00",
        "sms": True,
        "call": "+7 999 000-00-01",
        "prepayment": 100,
        "card": True,
        "cash": False,
        "extra_payment": 50,
        "od_sph": "-1.0",
        "od_cyl": "0",
        "od_axis": "90",
        "od_pd": "32",
        "od_add_deg": "1.0",
        "od_height": "10",
        "os_sph": "-1.0",
        "os_cyl": "0",
        "os_axis": "90",
        "os_pd": "32",
        "os_add_deg": "1.0",
        "os_height": "10",
        "for_what": "Для теста API",
        "frame_article": "ART-TEST",
        "print_info": "Печать тест",
        "promotion": False,
        "prescription_order": True,
        "child_order": False,
        "no_lenses": False,
        "client_frame_lenses": False,
        "case_included": True,
        "from_client_words": False,
        "doctor_prescription": True,
        "doctor_name": "Врач Тест",
        "clinic": "Клиника Тест",
        "by_client_glasses": False,
        "demo_mo": False,
        "price_includes_vat": True,
        "organization_name": "ОргТест",
        "department_name": "ПодрТест",
        "warehouse_name": "СкладТест",
        "author_name": "АвторТест",
        "ship_one_date": True,
        "ship_date": "2025-02-20",
        "total": 1550,
        "comment": "Тест полного заказа",
        "items": [
            {
                "line_number": 1,
                "product_name": "ТоварТест1",
                "characteristic_name": "Хар-ка 1",
                "quantity": 1,
                "price": 1000,
                "percent_manual": 5,
                "sum_manual": 50,
                "sum": 1050,
                "vat_rate_name": "Без НДС",
            },
            {
                "line_number": 2,
                "product_name": "ТоварТест2",
                "quantity": 1,
                "price": 500,
                "sum": 500,
                "vat_rate_name": "Без НДС",
            },
        ],
    }

    print("2. POST /api/orders (полное тело)...")
    created = request("POST", "/api/orders", body=payload, token=token)
    if not created or "id" not in created:
        print("   Ошибка: заказ не создан")
        sys.exit(1)
    oid = created["id"]
    print(f"   Создан заказ id={oid}")

    print("3. GET /api/orders/{id}...")
    got = request("GET", f"/api/orders/{oid}", token=token)
    if not got:
        print("   Ошибка: заказ не получен")
        sys.exit(1)
    print("   OK")

    checks = [
        ("order_status_name", "ТестСтатус", got.get("order_status_name")),
        ("priority_name", "ТестПриоритет", got.get("priority_name")),
        ("organization_name", "ОргТест", got.get("organization_name")),
        ("department_name", "ПодрТест", got.get("department_name")),
        ("warehouse_name", "СкладТест", got.get("warehouse_name")),
        ("author_name", "АвторТест", got.get("author_name")),
        ("order_number", "T-001", got.get("order_number")),
        ("client", "Клиент Тест", got.get("client")),
        ("age", 30, got.get("age")),
        ("sms", True, got.get("sms")),
        ("prepayment", 100, got.get("prepayment")),
        ("card", True, got.get("card")),
        ("extra_payment", 50, got.get("extra_payment")),
        ("for_what", "Для теста API", got.get("for_what")),
        ("frame_article", "ART-TEST", got.get("frame_article")),
        ("doctor_name", "Врач Тест", got.get("doctor_name")),
        ("clinic", "Клиника Тест", got.get("clinic")),
        ("ship_one_date", True, got.get("ship_one_date")),
        ("total", 1550, got.get("total")),
        ("comment", "Тест полного заказа", got.get("comment")),
    ]
    failed = []
    for name, expected, actual in checks:
        if actual != expected:
            failed.append(f"  {name}: ожидалось {expected!r}, получено {actual!r}")
    if failed:
        print("   Проверки полей заказа:")
        for f in failed:
            print(f)
        sys.exit(1)
    print("   Все поля заказа совпадают")

    items = got.get("items") or []
    if len(items) < 2:
        print("   Ошибка: ожидалось минимум 2 позиции")
        sys.exit(1)
    i1 = items[0]
    i2 = items[1]
    item_checks = [
        ("product_name 1", "ТоварТест1", i1.get("product_name")),
        ("characteristic_name 1", "Хар-ка 1", i1.get("characteristic_name")),
        ("vat_rate_name 1", "Без НДС", i1.get("vat_rate_name")),
        ("percent_manual", 5, i1.get("percent_manual")),
        ("sum_manual", 50, i1.get("sum_manual")),
        ("sum 1", 1050, i1.get("sum")),
        ("product_name 2", "ТоварТест2", i2.get("product_name")),
        ("vat_rate_name 2", "Без НДС", i2.get("vat_rate_name")),
        ("sum 2", 500, i2.get("sum")),
    ]
    for name, expected, actual in item_checks:
        if actual != expected:
            failed.append(f"  {name}: ожидалось {expected!r}, получено {actual!r}")
    if failed:
        print("   Проверки позиций:")
        for f in failed:
            print(f)
        sys.exit(1)
    print("   Все поля позиций совпадают")

    print("4. Готово. При получении всех полей везде создаётся нужное (справочники + заказ).")

if __name__ == "__main__":
    main()
