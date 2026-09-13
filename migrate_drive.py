"""
Таблица drive_items для раздела «Общий диск».
Идемпотентно: CREATE TABLE IF NOT EXISTS, индексы.
Запуск из каталога backend: python migrate_drive.py
"""

from sqlalchemy import text

from database import engine


DDL = [
    """
    CREATE TABLE IF NOT EXISTS drive_items (
        id SERIAL PRIMARY KEY,
        parent_id INTEGER REFERENCES drive_items(id) ON DELETE CASCADE,
        is_folder BOOLEAN NOT NULL DEFAULT TRUE,
        name VARCHAR(512) NOT NULL,
        owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        file_url VARCHAR(1024),
        mime_type VARCHAR(256),
        size_bytes INTEGER,
        shared_user_ids JSONB,
        shared_group_ids JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_drive_items_parent_id ON drive_items(parent_id)",
    "CREATE INDEX IF NOT EXISTS ix_drive_items_owner_user_id ON drive_items(owner_user_id)",
    "ALTER TABLE drive_items ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE drive_items ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL",
    "ALTER TABLE drive_items ADD COLUMN IF NOT EXISTS deleted_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_drive_items_is_deleted ON drive_items(is_deleted)",
    "ALTER TABLE drive_items ADD COLUMN IF NOT EXISTS folder_icon VARCHAR(1024) NULL",
    "ALTER TABLE drive_items ADD COLUMN IF NOT EXISTS public_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE drive_items ADD COLUMN IF NOT EXISTS public_token VARCHAR(64) NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_drive_items_public_token ON drive_items(public_token) WHERE public_token IS NOT NULL",
]


def main() -> None:
    with engine.begin() as conn:
        for i, sql in enumerate(DDL):
            conn.execute(text(sql))
            print(f"OK: drive DDL step {i + 1}/{len(DDL)}")
    print("Done: drive_items")


if __name__ == "__main__":
    main()

