"""
Добавляет user1_hidden / user2_hidden в private_dialogs (скрытие личного чата у себя).
Запуск: . venv/bin/activate && python migrate_chat_private_hidden.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE private_dialogs ADD COLUMN IF NOT EXISTS user1_hidden BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE private_dialogs ADD COLUMN IF NOT EXISTS user2_hidden BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.commit()
        print("OK: private_dialogs user1_hidden, user2_hidden")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
