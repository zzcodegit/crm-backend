"""
Одноразовая миграция: добавить колонки ФИО и telegram_id в таблицу users.
Запуск: python migrate_user_columns.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    for col, typ in [
        ("first_name", "VARCHAR(128)"),
        ("last_name", "VARCHAR(128)"),
        ("patronymic", "VARCHAR(128)"),
        ("telegram_id", "VARCHAR(64)"),
    ]:
        conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {typ}"))
    conn.commit()
    print("OK: user columns")
