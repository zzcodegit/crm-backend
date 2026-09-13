"""
Добавляет в таблицу pricelist_items колонки: full_description, barcode, photo_url.
Запуск: из корня backend: python migrate_pricelist_columns.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    for col, sql in [
        ("full_description", "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS full_description TEXT"),
        ("barcode", "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS barcode VARCHAR(128)"),
        ("photo_url", "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS photo_url VARCHAR(512)"),
    ]:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"OK: {col}")
        except Exception as e:
            print(f"Skip/Error {col}: {e}")
print("Done.")
