"""
Таблица central_cash_payouts — выплаты из центральной кассы.
create_all() на проде не создаёт новые таблицы, если приложение не трогало метаданные;
на всякий случай дублируем явным DDL.

Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_central_cash_payouts.py
"""
from database import engine
from sqlalchemy import text

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS central_cash_payouts (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_to_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount NUMERIC(15, 2) NOT NULL,
    note TEXT,
    recorded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
)
"""

CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_central_cash_payouts_paid_to_user_id "
    "ON central_cash_payouts (paid_to_user_id)"
)


def main() -> None:
    with engine.connect() as conn:
        try:
            conn.execute(text(CREATE_TABLE))
            conn.execute(text(CREATE_INDEX))
            conn.commit()
            print("OK: central_cash_payouts")
        except Exception as e:
            print(f"Error: {e}")
            raise
    print("Done.")


if __name__ == "__main__":
    main()
