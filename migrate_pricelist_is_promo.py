"""
Добавляет в таблицу pricelist_items колонку is_promo (акция).
Запуск: из корня backend: . venv/bin/activate && python migrate_pricelist_is_promo.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS is_promo BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.commit()
        print("OK: is_promo")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
