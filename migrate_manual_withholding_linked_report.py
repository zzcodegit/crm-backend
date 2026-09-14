"""
Добавляет linked_report_id — отчёт, выбранный админом в форме удержания («Забрано в отчёте»).

Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_manual_withholding_linked_report.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(
            text(
                """
                ALTER TABLE manual_withholdings
                ADD COLUMN IF NOT EXISTS linked_report_id INTEGER
                REFERENCES daily_reports(id) ON DELETE SET NULL
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_manual_withholdings_linked_report_id
                ON manual_withholdings (linked_report_id)
                """
            )
        )
        conn.commit()
        print("OK: manual_withholdings.linked_report_id")
    except Exception as e:
        print(f"Error: {e}")
        raise
