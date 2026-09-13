#!/usr/bin/env python3
import sys

sys.path.insert(0, "/home/crm-backend")
from database import SessionLocal
from mutual_settlement_1c import (
    find_existing_mutual_dup_keys,
    validate_bonus_arr_mutual_settlements,
)

db = SessionLocal()
existing = find_existing_mutual_dup_keys(db)
print(f"existing mutual keys (type, year, doc, consultant): {len(existing)}")

DOC = "Взаимозачет задолженности 00ЦБ-011697 от 09.09.2026 15:13:23"
KEY_MOZ = ("Заказ", 2026, 11697, "Мозговая Юлия")
print("has Mozgovaya 11697/2026:", KEY_MOZ in existing)

# same type+doc+year+consultant + different sum → skip
payload_diff_sum = {
    "bonus_arr": [
        {
            "record_type": "Заказ",
            "operation_date": "09.09.2026 0:00:00",
            "consultant": "Мозговая Юлия ",
            "trade_point": "Олимпийская деревня",
            "doc": DOC,
            "order_number": "307",
            "percent": 10,
            "sum": 1,
        }
    ]
}
ok, err, skip = validate_bonus_arr_mutual_settlements(db, payload_diff_sum)
print("same key different sum:", ok, err, "skip=", skip, "expected skip=True")

# same doc+year+type, OTHER consultant → create
payload_other_cons = {
    "bonus_arr": [
        {
            "record_type": "Заказ",
            "operation_date": "09.09.2026 0:00:00",
            "consultant": "Тестовый Консультант",
            "trade_point": "Олимпийская деревня",
            "doc": DOC,
            "order_number": "307",
            "percent": 10,
            "sum": 3930,
        }
    ]
}
ok_c, err_c, skip_c = validate_bonus_arr_mutual_settlements(db, payload_other_cons)
print("same doc other consultant:", ok_c, err_c, "skip=", skip_c, "expected skip=False")

# same number, other year → create
payload_other_year = {
    "bonus_arr": [
        {
            "record_type": "Заказ",
            "operation_date": "09.09.2025 0:00:00",
            "consultant": "Мозговая Юлия ",
            "trade_point": "Олимпийская деревня",
            "doc": "Взаимозачет задолженности 00ЦБ-011697 от 09.09.2025 15:13:23",
            "order_number": "307",
            "percent": 10,
            "sum": 3930,
        }
    ]
}
ok2, err2, skip2 = validate_bonus_arr_mutual_settlements(db, payload_other_year)
print("same doc_num other year:", ok2, err2, "skip=", skip2, "expected skip=False")

# two consultants in one payload — if both new relative to a fresh doc, not all-dup
payload_two = {
    "bonus_arr": [
        {
            "record_type": "Заказ",
            "operation_date": "13.09.2026 0:00:00",
            "consultant": "Шмыткова Мария",
            "trade_point": "Test",
            "doc": "Взаимозачет задолженности 00ЦБ-999991 от 13.09.2026 12:00:00",
            "order_number": "1",
            "sum": 100,
        },
        {
            "record_type": "Заказ",
            "operation_date": "13.09.2026 0:00:00",
            "consultant": "Катламина Татьяна",
            "trade_point": "Test",
            "doc": "Взаимозачет задолженности 00ЦБ-999991 от 13.09.2026 12:00:00",
            "order_number": "1",
            "sum": 100,
        },
    ]
}
ok3, err3, skip3 = validate_bonus_arr_mutual_settlements(db, payload_two)
print("two consultants new doc:", ok3, err3, "skip=", skip3, "expected skip=False")

db.close()
