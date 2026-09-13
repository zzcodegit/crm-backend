"""
Добавляет в daily_reports поля: bn_card_reconciliation, bn_z_report, extra_payments, vyhod, percent.
Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_daily_reports_extras.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    for col, typ in [
        ("bn_card_reconciliation", "NUMERIC(15,2)"),
        ("bn_z_report", "NUMERIC(15,2)"),
        ("extra_payments", "JSONB"),
        ("vyhod", "NUMERIC(15,2)"),
        ("percent", "NUMERIC(8,2)"),
        ("vzyala", "NUMERIC(15,2)"),
        ("dolg", "NUMERIC(15,2)"),
    ]:
        conn.execute(text(f"ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS {col} {typ}"))
    conn.commit()
    print("OK: daily_reports extra columns")
