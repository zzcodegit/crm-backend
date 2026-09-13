"""
Добавляет в таблицу manufacturers колонку catalog_pdf_url.
Запуск: из корня backend: python migrate_manufacturer_catalog_pdf.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE manufacturers ADD COLUMN IF NOT EXISTS catalog_pdf_url VARCHAR(512)"))
    conn.commit()
    print("OK: catalog_pdf_url")
print("Done.")
