"""
Создаёт таблицы pricelist_rx_groups и pricelist_rx_items (каталог RX отдельно от склада).
Идемпотентно: CREATE TABLE IF NOT EXISTS.
Запуск из корня backend: python migrate_pricelist_rx.py
"""
from database import engine
from sqlalchemy import text

DDL = [
    """
    CREATE TABLE IF NOT EXISTS pricelist_rx_groups (
        id SERIAL PRIMARY KEY,
        name VARCHAR(128) NOT NULL UNIQUE,
        sort_index INTEGER NOT NULL DEFAULT 500,
        display_properties_in_list BOOLEAN NOT NULL DEFAULT TRUE,
        display_as_tiles BOOLEAN NOT NULL DEFAULT FALSE,
        tiles_per_page INTEGER NOT NULL DEFAULT 4
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pricelist_rx_items (
        id SERIAL PRIMARY KEY,
        manufacturer_id INTEGER REFERENCES manufacturers(id) ON DELETE SET NULL,
        lens_name VARCHAR(256) NOT NULL,
        description TEXT,
        full_description TEXT,
        barcode VARCHAR(128),
        barcodes JSONB,
        photo_url VARCHAR(512),
        photo_urls JSONB,
        sph VARCHAR(512),
        cyl VARCHAR(512),
        step VARCHAR(256),
        diameters VARCHAR(256),
        price NUMERIC(12, 2) NOT NULL,
        is_promo BOOLEAN NOT NULL DEFAULT FALSE,
        uv_protection BOOLEAN NOT NULL DEFAULT FALSE,
        material TEXT,
        lens_id INTEGER,
        "group" VARCHAR(128) NOT NULL,
        coefficient VARCHAR(32),
        feature_ids JSONB,
        feature_colors JSONB,
        custom_values JSONB,
        hide_detail_link BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,
]


def main() -> None:
    with engine.begin() as conn:
        for i, sql in enumerate(DDL):
            conn.execute(text(sql))
            print(f"OK: DDL step {i + 1}")
    print("Done: pricelist_rx_*")


if __name__ == "__main__":
    main()
