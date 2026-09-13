"""
Добавляет submitted_at — время отправки отчёта (отдельно от created_at черновика).
Запуск: из корня backend: . venv/bin/activate && python migrate_daily_reports_submitted_at.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(
            text(
                """
                ALTER TABLE daily_reports
                ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMP WITH TIME ZONE;
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE daily_reports
                SET submitted_at = created_at
                WHERE is_draft = FALSE AND submitted_at IS NULL;
                """
            )
        )
        conn.commit()
        print("OK: daily_reports.submitted_at")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
