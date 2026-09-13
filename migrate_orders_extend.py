"""
Добавляет новые колонки в orders и order_items (если их ещё нет).
Запуск: python migrate_orders_extend.py
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
            pass
        else:
            raise

# Таблицы справочников для заказов (если ещё нет)
def ensure_table_order_statuses():
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS order_statuses (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(128) NOT NULL
                )
            """))
            conn.commit()
            print("  + table order_statuses")
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise

def ensure_table_priorities():
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS priorities (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(128) NOT NULL
                )
            """))
            conn.commit()
            print("  + table priorities")
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise

print("Справочники заказов:")
ensure_table_order_statuses()
ensure_table_priorities()

# Новые колонки orders (те что ещё не были в первой версии)
orders_new = [
    ("order_status_id", "INTEGER REFERENCES order_statuses(id) ON DELETE SET NULL"),
    ("priority_id", "INTEGER REFERENCES priorities(id) ON DELETE SET NULL"),
    ("consultant_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
    ("client_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
    ("age", "INTEGER"),
    ("sms", "BOOLEAN DEFAULT FALSE"),
    ("call", "VARCHAR(128)"),
    ("prepayment", "NUMERIC(15,2)"),
    ("card", "BOOLEAN DEFAULT FALSE"),
    ("cash", "BOOLEAN DEFAULT FALSE"),
    ("extra_payment", "NUMERIC(15,2)"),
    ("for_what", "VARCHAR(512)"),
    ("frame_article", "VARCHAR(128)"),
    ("promotion", "BOOLEAN DEFAULT FALSE"),
    ("prescription_order", "BOOLEAN DEFAULT FALSE"),
    ("child_order", "BOOLEAN DEFAULT FALSE"),
    ("no_lenses", "BOOLEAN DEFAULT FALSE"),
    ("client_frame_lenses", "BOOLEAN DEFAULT FALSE"),
    ("case_included", "BOOLEAN DEFAULT FALSE"),
    ("from_client_words", "BOOLEAN DEFAULT FALSE"),
    ("doctor_prescription", "BOOLEAN DEFAULT FALSE"),
    ("doctor_name", "VARCHAR(256)"),
    ("clinic", "VARCHAR(256)"),
    ("by_client_glasses", "BOOLEAN DEFAULT FALSE"),
    ("demo_mo", "BOOLEAN DEFAULT FALSE"),
    ("price_includes_vat", "BOOLEAN DEFAULT FALSE"),
    ("organization_id", "INTEGER REFERENCES organizations(id) ON DELETE SET NULL"),
    ("department_id", "INTEGER REFERENCES departments(id) ON DELETE SET NULL"),
    ("warehouse_id", "INTEGER REFERENCES warehouses(id) ON DELETE SET NULL"),
    ("author_id", "INTEGER REFERENCES authors(id) ON DELETE SET NULL"),
    ("ship_one_date", "BOOLEAN DEFAULT FALSE"),
    ("ship_date", "DATE"),
]
print("Orders:")
for col, typ in orders_new:
    add_column("orders", col, typ)

# order_items
items_new = [
    ("product_id", "INTEGER REFERENCES products(id) ON DELETE SET NULL"),
    ("characteristic_id", "INTEGER REFERENCES product_characteristics(id) ON DELETE SET NULL"),
    ("percent_manual", "NUMERIC(8,2)"),
    ("sum_manual", "NUMERIC(15,2)"),
    ("vat_rate_id", "INTEGER REFERENCES vat_rates(id) ON DELETE SET NULL"),
]
print("Order items:")
for col, typ in items_new:
    add_column("order_items", col, typ)

print("Готово.")
