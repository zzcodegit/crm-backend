"""
Таблица expense_articles и поля daily_reports.has_expenses, daily_reports.expenses.
Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_expense_articles.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS expense_articles (
                id SERIAL PRIMARY KEY,
                name VARCHAR(256) NOT NULL
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_expense_articles_id ON expense_articles (id)"))
    conn.execute(text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS has_expenses BOOLEAN NOT NULL DEFAULT false"))
    conn.execute(text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS expenses JSONB"))
    conn.commit()
    print("OK: expense_articles + daily_reports.has_expenses / expenses")
