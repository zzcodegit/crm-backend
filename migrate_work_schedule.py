"""Таблицы work_schedule_drafts и work_schedule_published."""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS work_schedule_drafts (
                id SERIAL PRIMARY KEY,
                name VARCHAR(256) NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS work_schedule_published (
                id INTEGER PRIMARY KEY,
                payload JSONB NOT NULL,
                published_at TIMESTAMPTZ DEFAULT NOW(),
                published_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
    )
    conn.commit()
    print("OK: work_schedule_drafts, work_schedule_published")
