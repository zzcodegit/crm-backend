"""
Добавляет balance_effective_date — дата пополнения баланса ЦК у сотрудника.
Для существующих записей: календарный день created_at в Europe/Moscow.

Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_central_cash_balance_effective_date.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(
            text(
                """
                ALTER TABLE central_cash_payouts
                ADD COLUMN IF NOT EXISTS balance_effective_date DATE;
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE central_cash_payouts
                SET balance_effective_date = (created_at AT TIME ZONE 'Europe/Moscow')::date
                WHERE balance_effective_date IS NULL;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE central_cash_payouts
                ALTER COLUMN balance_effective_date SET NOT NULL;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_central_cash_payouts_balance_effective_date
                ON central_cash_payouts (balance_effective_date);
                """
            )
        )
        conn.commit()
        print("OK: central_cash_payouts.balance_effective_date")
    except Exception as e:
        print(f"Error: {e}")
        raise
