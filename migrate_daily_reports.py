"""
Создаёт таблицу daily_reports для отчётов консультантов.
Запуск: из корня backend: . venv/bin/activate && python migrate_daily_reports.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                is_draft BOOLEAN NOT NULL DEFAULT FALSE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                warehouse_id INTEGER REFERENCES warehouses(id) ON DELETE SET NULL,
                utro NUMERIC(15,2),
                revenue NUMERIC(15,2),
                nal NUMERIC(15,2),
                bn NUMERIC(15,2),
                zp NUMERIC(15,2),
                ost NUMERIC(15,2),
                has_returns BOOLEAN NOT NULL DEFAULT FALSE,
                return_bn NUMERIC(15,2),
                return_nal NUMERIC(15,2),
                returns_details JSONB, -- [{"date_check": "...", "consultant_last_name": "...", "amount": 123.45}]
                z_report_urls JSONB,
                card_reconciliation_urls JSONB
            )
        """))
        conn.commit()
        print("OK: table daily_reports")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
