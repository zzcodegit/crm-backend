"""
Создаёт таблицу colors (справочник цветов для особенностей линз).
Запуск: из корня backend: . venv/bin/activate && python migrate_colors.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS colors (
                id SERIAL PRIMARY KEY,
                name VARCHAR(128) UNIQUE NOT NULL
            )
        """))
        conn.commit()
        print("OK: table colors")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
