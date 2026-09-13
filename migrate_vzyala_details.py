"""
Добавляет daily_reports.vzyala_details (JSONB).
Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_vzyala_details.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS vzyala_details JSONB"))
    conn.commit()
    print("OK: daily_reports.vzyala_details")
