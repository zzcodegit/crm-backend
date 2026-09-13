"""
Добавляет в таблицу pricelist_groups колонку sort_index для порядка отображения.
Запуск: из корня backend: . venv/bin/activate && python migrate_pricelist_groups_sort_index.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE pricelist_groups ADD COLUMN IF NOT EXISTS sort_index INTEGER NOT NULL DEFAULT 0"))
        conn.commit()
        print("OK: sort_index")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
