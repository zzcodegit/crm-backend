"""Папки для организации чатов в списке."""
from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_folders (
                  id SERIAL PRIMARY KEY,
                  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  name VARCHAR(64) NOT NULL,
                  position INTEGER NOT NULL DEFAULT 0,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_folder_items (
                  id SERIAL PRIMARY KEY,
                  folder_id INTEGER NOT NULL REFERENCES chat_folders(id) ON DELETE CASCADE,
                  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  chat_type VARCHAR(16) NOT NULL,
                  private_dialog_id INTEGER REFERENCES private_dialogs(id) ON DELETE CASCADE,
                  group_dialog_id INTEGER REFERENCES group_chat_dialogs(id) ON DELETE CASCADE,
                  position INTEGER NOT NULL DEFAULT 0,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_folders_user_id ON chat_folders(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_folder_items_folder_id ON chat_folder_items(folder_id)"))
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_chat_folder_item_unique'
                  ) THEN
                    CREATE UNIQUE INDEX idx_chat_folder_item_unique
                      ON chat_folder_items(folder_id, chat_type, private_dialog_id, group_dialog_id);
                  END IF;
                END
                $$;
                """
            )
        )
    print("OK: chat_folders, chat_folder_items")


if __name__ == "__main__":
    main()
