"""
Добавляет колонку manager_id в warehouses (менеджер склада).
Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_warehouse_manager.py
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


print("Warehouses manager_id:")
add_column("warehouses", "manager_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
print("Готово.")
