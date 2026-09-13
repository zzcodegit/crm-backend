"""Бот поддержки в чате: треды по пользователям."""
from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE chat_messages
                ADD COLUMN IF NOT EXISTS bot_thread_user_id INTEGER
                REFERENCES users(id) ON DELETE CASCADE
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_messages_bot_thread_user_id "
                "ON chat_messages(bot_thread_user_id)"
            )
        )
    print("migrate_chat_bot: ok")


if __name__ == "__main__":
    main()
