"""Мета обращений в поддержку: закрытие админом (скрытие из списка)."""
from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_bot_thread_meta (
                    user_id INTEGER PRIMARY KEY
                        REFERENCES users(id) ON DELETE CASCADE,
                    closed_at TIMESTAMPTZ,
                    closed_by_user_id INTEGER
                        REFERENCES users(id) ON DELETE SET NULL
                )
                """
            )
        )
    print("OK: chat_bot_thread_meta")


if __name__ == "__main__":
    main()
