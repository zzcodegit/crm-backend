"""
Колонка opening_hours (JSONB) у warehouses — время работы по дням недели и праздники.
Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_warehouse_opening_hours.py
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


print("warehouses.opening_hours:")
add_column("warehouses", "opening_hours", "JSONB")
print("Готово.")
