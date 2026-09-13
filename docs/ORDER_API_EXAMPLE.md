# API заказа: пример полного тела и ответа

## GET /api/orders/{id}

Возвращает заказ со всеми полями и именами справочников.

**Заголовок:** `Authorization: Bearer <token>`

**Пример ответа (200):**

```json
{
  "id": 1,
  "status": "new",
  "order_status_id": 1,
  "order_status_name": "Новый",
  "priority_id": 1,
  "priority_name": "Обычный",
  "consultant_id": null,
  "consultant": "Иванов И.И.",
  "order_number": "ORD-001",
  "date": "2025-02-15",
  "readiness_date": "2025-02-20",
  "client_id": null,
  "client": "Петров П.П.",
  "age": 35,
  "phone": "+7 999 123-45-67",
  "sms": true,
  "call": "+7 999 111-22-33",
  "prepayment": 500.00,
  "card": true,
  "cash": false,
  "extra_payment": 0,
  "od_sph": "-2.0",
  "od_cyl": "-0.5",
  "od_axis": "90",
  "od_pd": "32",
  "od_add_deg": "1.5",
  "od_height": "12",
  "os_sph": "-2.25",
  "os_cyl": "-0.5",
  "os_axis": "85",
  "os_pd": "32",
  "os_add_deg": "1.5",
  "os_height": "12",
  "for_what": "Для работы за компьютером",
  "frame_article": "ART-123",
  "print_info": "Текст для печати на линзах",
  "promotion": false,
  "prescription_order": true,
  "child_order": false,
  "no_lenses": false,
  "client_frame_lenses": false,
  "case_included": true,
  "from_client_words": false,
  "doctor_prescription": true,
  "doctor_name": "Сидорова М.В.",
  "clinic": "Поликлиника №1",
  "by_client_glasses": false,
  "demo_mo": false,
  "price_includes_vat": true,
  "organization_id": 1,
  "organization_name": "ООО Оптика",
  "department_id": 1,
  "department_name": "Салон на Ленина",
  "warehouse": null,
  "warehouse_id": 1,
  "warehouse_name": "Склад 1",
  "author_id": 1,
  "author_name": "Менеджер",
  "ship_one_date": true,
  "ship_date": "2025-02-20",
  "total": 5500.00,
  "comment": "Позвонить за день до готовности",
  "created_at": "2025-02-15T10:00:00",
  "items": [
    {
      "id": 1,
      "order_id": 1,
      "line_number": 1,
      "product_id": 1,
      "characteristic_id": 1,
      "nomenclature": "Линзы очковые",
      "quantity": 1,
      "price": 3000.00,
      "percent_manual": 10,
      "sum_manual": 300.00,
      "sum": 3300.00,
      "vat_rate_id": 1,
      "product_name": "Линзы очковые",
      "characteristic_name": "Покрытие антиблик",
      "vat_rate_name": "Без НДС"
    },
    {
      "id": 2,
      "order_id": 1,
      "line_number": 2,
      "product_id": 2,
      "characteristic_id": null,
      "nomenclature": "Оправа",
      "quantity": 1,
      "price": 2200.00,
      "percent_manual": null,
      "sum_manual": null,
      "sum": 2200.00,
      "vat_rate_id": 1,
      "product_name": "Оправа",
      "characteristic_name": null,
      "vat_rate_name": "Без НДС"
    }
  ]
}
```

---

## POST /api/orders (создание с именами справочников)

Если передать **имя** справочника вместо id (или вместе с ним), при отсутствии записи она будет создана.

**Заголовок:** `Authorization: Bearer <token>`

**Пример тела со всеми полями:**

```json
{
  "order_status_name": "Новый",
  "priority_name": "Обычный",
  "consultant": "Иванов И.И.",
  "order_number": "ORD-002",
  "date": "2025-02-15",
  "readiness_date": "2025-02-20",
  "client": "Петров П.П.",
  "age": 35,
  "phone": "+7 999 123-45-67",
  "sms": true,
  "call": "+7 999 111-22-33",
  "prepayment": 500,
  "card": true,
  "cash": false,
  "extra_payment": 0,
  "od_sph": "-2.0",
  "od_cyl": "-0.5",
  "od_axis": "90",
  "od_pd": "32",
  "od_add_deg": "1.5",
  "od_height": "12",
  "os_sph": "-2.25",
  "os_cyl": "-0.5",
  "os_axis": "85",
  "os_pd": "32",
  "os_add_deg": "1.5",
  "os_height": "12",
  "for_what": "Для работы за компьютером",
  "frame_article": "ART-123",
  "print_info": "Текст для печати",
  "promotion": false,
  "prescription_order": true,
  "child_order": false,
  "no_lenses": false,
  "client_frame_lenses": false,
  "case_included": true,
  "from_client_words": false,
  "doctor_prescription": true,
  "doctor_name": "Сидорова М.В.",
  "clinic": "Поликлиника №1",
  "by_client_glasses": false,
  "demo_mo": false,
  "price_includes_vat": true,
  "organization_name": "ООО Оптика",
  "department_name": "Салон на Ленина",
  "warehouse_name": "Склад 1",
  "author_name": "Менеджер",
  "ship_one_date": true,
  "ship_date": "2025-02-20",
  "total": 5500,
  "comment": "Комментарий к заказу",
  "items": [
    {
      "line_number": 1,
      "product_name": "Линзы очковые",
      "characteristic_name": "Покрытие антиблик",
      "quantity": 1,
      "price": 3000,
      "percent_manual": 10,
      "sum_manual": 300,
      "sum": 3300,
      "vat_rate_name": "Без НДС"
    },
    {
      "line_number": 2,
      "product_name": "Оправа",
      "quantity": 1,
      "price": 2200,
      "sum": 2200,
      "vat_rate_name": "Без НДС"
    }
  ]
}
```

**Поля заказа (кратко):**

| Поле | Тип | Описание |
|------|-----|----------|
| order_status_name | строка | Статус заказа (справочник) — создаётся при отсутствии |
| priority_name | строка | Приоритет (справочник) |
| consultant / consultant_id | строка / number | Консультант (текст или id пользователя) |
| order_number | строка | Номер заказа |
| date, readiness_date | строка (YYYY-MM-DD) | Дата от, дата готовности |
| client / client_id | строка / number | Клиент |
| age | number | Возраст |
| phone | строка | Телефон |
| sms | bool | СМС (Да/Нет) |
| call | строка | Звонок |
| prepayment, extra_payment | number | Предоплата, доплата |
| card, cash | bool | Картой, наличными |
| od_* / os_* | строка | Параметры OD/OS (SPH, CYL, AXIS, PD, add/deg, УС) |
| for_what | строка | Для чего |
| frame_article | строка | Артикул оправы |
| print_info | строка | Информация для печати |
| promotion, prescription_order, child_order, no_lenses, client_frame_lenses | bool | Флаги |
| case_included, from_client_words, doctor_prescription, by_client_glasses, demo_mo, price_includes_vat | bool | Флаги |
| doctor_name, clinic | строка | Врач, поликлиника |
| organization_name, department_name, warehouse_name, author_name | строка | Справочники (создаются при отсутствии) |
| ship_one_date | bool | Отгружать одной датой |
| ship_date | строка | Дата отгрузки |
| total | number | Сумма |
| comment | строка | Комментарий |
| items | массив | Позиции (см. ниже) |

**Позиция (items[]):**

| Поле | Тип | Описание |
|------|-----|----------|
| line_number | number | Номер строки |
| product_id / product_name | number / строка | Товар (по имени создаётся в справочнике) |
| characteristic_id / characteristic_name | number / строка | Характеристика (привязана к товару; создаётся при наличии product_id/product_name) |
| nomenclature | строка | Текстовое наименование (если нет товара из справочника) |
| quantity, price, sum | number | Количество, цена, сумма |
| percent_manual, sum_manual | number | % руч., сумма руч. |
| vat_rate_id / vat_rate_name | number / строка | Ставка НДС (справочник) |

Ответ **POST** совпадает по структуре с **GET** (полный объект заказа с `id`, `created_at`, `items` с `id`, `order_id` и именами справочников).
