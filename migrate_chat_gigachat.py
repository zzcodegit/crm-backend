"""Диалог с GigaChat: тред сообщений по пользователям."""
from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE chat_messages
                ADD COLUMN IF NOT EXISTS gigachat_thread_user_id INTEGER
                REFERENCES users(id) ON DELETE CASCADE
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_messages_gigachat_thread_user_id "
                "ON chat_messages(gigachat_thread_user_id)"
            )
        )
    print("migrate_chat_gigachat: ok")


if __name__ == "__main__":
    main()

