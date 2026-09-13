"""
Добавляет в таблицу pricelist_items колонку barcodes (JSONB) для нескольких штрихкодов.
Запуск: из корня backend: python migrate_pricelist_barcodes.py (или с venv: . venv/bin/activate && python migrate_pricelist_barcodes.py)
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS barcodes JSONB"))
        conn.commit()
        print("OK: barcodes")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
