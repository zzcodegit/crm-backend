#!/usr/bin/env python3
import sys

sys.path.insert(0, "/home/crm-backend")
from database import SessionLocal
from mutual_settlement_1c import (
    find_existing_mutual_doc_years,
    validate_bonus_arr_mutual_settlements,
)

db = SessionLocal()
existing = find_existing_mutual_doc_years(db)
print(f"existing mutual (year, doc_num): {len(existing)}")
print("has 2026/11697:", (2026, 11697) in existing)

DOC = "Взаимозачет задолженности 00ЦБ-011697 от 09.09.2026 15:13:23"

# same doc + different sum → skip (first wins)
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
print("same doc+year different sum:", ok, err, "skip=", skip, "expected skip=True")

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

# brand new doc → create
payload_new = {
    "bonus_arr": [
        {
            "record_type": "Заказ",
            "operation_date": "13.09.2026 0:00:00",
            "consultant": "Test",
            "trade_point": "Test",
            "doc": "Взаимозачет задолженности 00ЦБ-999997 от 13.09.2026 12:00:00",
            "order_number": "1",
            "percent": 10,
            "sum": 100,
        }
    ]
}
ok3, err3, skip3 = validate_bonus_arr_mutual_settlements(db, payload_new)
print("new doc:", ok3, err3, "skip=", skip3, "expected skip=False")

db.close()
