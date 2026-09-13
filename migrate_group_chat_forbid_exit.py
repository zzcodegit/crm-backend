"""Добавляет forbid_exit в group_chat_dialogs (запрет выхода консультантов из группы)."""
from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE group_chat_dialogs "
                "ADD COLUMN IF NOT EXISTS forbid_exit BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
    print("OK: group_chat_dialogs.forbid_exit")


if __name__ == "__main__":
    main()
