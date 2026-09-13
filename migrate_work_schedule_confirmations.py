"""Таблица work_schedule_confirmations — подтверждения графика консультантами."""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS work_schedule_confirmations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                week_start VARCHAR(10) NOT NULL,
                confirmed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_work_schedule_conf_user_week UNIQUE (user_id, week_start)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_work_schedule_confirmations_week_start
            ON work_schedule_confirmations (week_start)
            """
        )
    )
    conn.commit()
    print("OK: work_schedule_confirmations")
