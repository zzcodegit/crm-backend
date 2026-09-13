"""
Однократный backfill: sort_index = 500 только у групп с начальным значением 0
(после добавления колонки sort_index). Не трогает пользовательскую сортировку.

Запуск: из корня backend: . venv/bin/activate && python migrate_pricelist_groups_default_500.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        result = conn.execute(
            text(
                "UPDATE pricelist_groups SET sort_index = 500 "
                "WHERE sort_index = 0"
            )
        )
        conn.commit()
        updated = result.rowcount if result.rowcount is not None else 0
        print(f"OK: sort_index=500 проставлен группам с sort_index=0 (обновлено: {updated})")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
