"""
Инкассация в отчёте: has_encashment, encashment_nal, encashment_bn.
Запуск: . venv/bin/activate && python migrate_daily_reports_encashment.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS has_encashment BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS encashment_nal NUMERIC(15,2)"))
        conn.execute(text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS encashment_bn NUMERIC(15,2)"))
        conn.commit()
        print("OK: daily_reports encashment columns")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
