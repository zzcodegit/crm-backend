"""Добавляет is_channel в group_chat_dialogs (информационные каналы)."""
from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE group_chat_dialogs "
                "ADD COLUMN IF NOT EXISTS is_channel BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
    print("OK: group_chat_dialogs.is_channel")


if __name__ == "__main__":
    main()
