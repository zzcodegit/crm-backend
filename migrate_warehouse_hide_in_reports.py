"""
Колонка hide_in_reports у warehouses — не показывать точку в списке отчётов.
Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_warehouse_hide_in_reports.py
"""
from sqlalchemy import text
from database import engine


def add_column(table: str, column: str, type_: str):
    try:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {type_}"))
            conn.commit()
            print(f"  + {table}.{column}")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            print(f"  (уже есть) {table}.{column}")
        else:
            raise


print("warehouses.hide_in_reports:")
add_column("warehouses", "hide_in_reports", "BOOLEAN NOT NULL DEFAULT FALSE")
print("Готово.")
