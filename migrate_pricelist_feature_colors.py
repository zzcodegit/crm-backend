"""
Добавляет в таблицу pricelist_items колонку feature_colors (JSONB) для цвета по особенностям (хамелеоны, рефлекс).
Запуск: из корня backend: . venv/bin/activate && python migrate_pricelist_feature_colors.py
"""
from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS feature_colors JSONB"))
        conn.commit()
        print("OK: feature_colors")
    except Exception as e:
        print(f"Error: {e}")
print("Done.")
