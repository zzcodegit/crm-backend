"""
Добавляет в таблицу features колонку colors (JSONB) для нескольких цветов.
Запуск: из корня backend: . venv/bin/activate && python migrate_features_colors.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE features ADD COLUMN IF NOT EXISTS colors JSONB"))
        conn.commit()
        print("OK: colors")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
