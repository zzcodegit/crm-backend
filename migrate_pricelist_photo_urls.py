"""
Добавляет в таблицу pricelist_items колонку photo_urls (JSONB) для нескольких фото.
Запуск: из корня backend: python migrate_pricelist_photo_urls.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS photo_urls JSONB"))
        conn.commit()
        print("OK: photo_urls")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
