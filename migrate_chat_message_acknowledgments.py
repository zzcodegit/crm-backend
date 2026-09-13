"""Добавляет ack_required в chat_messages и таблицу chat_message_acknowledgments."""
from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE chat_messages "
                "ADD COLUMN IF NOT EXISTS ack_required BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_message_acknowledgments (
                  id SERIAL PRIMARY KEY,
                  message_id INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
                  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_message_user_ack'
                  ) THEN
                    CREATE UNIQUE INDEX idx_message_user_ack
                      ON chat_message_acknowledgments(message_id, user_id);
                  END IF;
                END
                $$;
                """
            )
        )
    print("OK: chat_messages.ack_required, chat_message_acknowledgments")


if __name__ == "__main__":
    main()
