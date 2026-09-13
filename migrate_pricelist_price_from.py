"""
Добавляет price_from (цена «от N ₽») в pricelist_items и pricelist_rx_items.
Запуск: python migrate_pricelist_price_from.py
"""
from database import engine
from sqlalchemy import text

DDL = [
    "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS price_from BOOLEAN DEFAULT FALSE NOT NULL",
    "ALTER TABLE pricelist_rx_items ADD COLUMN IF NOT EXISTS price_from BOOLEAN DEFAULT FALSE NOT NULL",
]


def main() -> None:
    with engine.begin() as conn:
        for sql in DDL:
            conn.execute(text(sql))
            print(f"OK: {sql[:60]}...")
    print("Done: price_from")


if __name__ == "__main__":
    main()
