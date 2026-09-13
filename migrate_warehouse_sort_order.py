from sqlalchemy import text

from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE warehouses
                ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_warehouses_sort_order ON warehouses(sort_order);"))
    print("OK: warehouses.sort_order")


if __name__ == "__main__":
    main()

