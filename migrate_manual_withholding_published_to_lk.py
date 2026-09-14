"""
Добавляет published_to_lk / published_at / published_by_user_id для ручных удержаний.
При первом прогоне все уже существующие записи считаем отправленными в ЛК.
Повторный прогон не трогает черновики (published_to_lk=false при наличии уже опубликованных).

Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_manual_withholding_published_to_lk.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(
            text(
                """
                ALTER TABLE manual_withholdings
                ADD COLUMN IF NOT EXISTS published_to_lk BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE manual_withholdings
                ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE manual_withholdings
                ADD COLUMN IF NOT EXISTS published_by_user_id INTEGER
                REFERENCES users(id) ON DELETE SET NULL
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_manual_withholdings_published_to_lk
                ON manual_withholdings (published_to_lk)
                """
            )
        )
        # Первый прогон: колонка только что появилась → все FALSE. Бэкапим в TRUE.
        # Если уже есть хотя бы одна опубликованная — оставшиеся FALSE это черновики, не трогаем.
        published_count = conn.execute(
            text("SELECT COUNT(*) FROM manual_withholdings WHERE published_to_lk = TRUE")
        ).scalar()
        total = conn.execute(text("SELECT COUNT(*) FROM manual_withholdings")).scalar()
        if int(total or 0) > 0 and int(published_count or 0) == 0:
            conn.execute(
                text(
                    """
                    UPDATE manual_withholdings
                    SET published_to_lk = TRUE,
                        published_at = COALESCE(published_at, created_at)
                    WHERE published_to_lk = FALSE
                    """
                )
            )
            print(f"OK: backfilled {total} existing rows as published_to_lk=TRUE")
        else:
            print(
                f"OK: columns ready (total={total}, already_published={published_count}; no backfill)"
            )
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")
        raise
