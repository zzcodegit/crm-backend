"""
admin_only для групп склада и МКЛ + папка «Прайс для админа» во всех трёх прайсах.

Запуск: cd /home/crm-backend && . venv/bin/activate && python migrate_pricelist_admin_folder.py
"""
from database import engine
from sqlalchemy import text

ADMIN_FOLDER = "Прайс для админа"

with engine.connect() as conn:
    try:
        for table in ("pricelist_groups", "pricelist_mkl_groups"):
            conn.execute(
                text(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS admin_only BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )
            )

        # Папка во всех трёх каталогах
        for table in ("pricelist_groups", "pricelist_rx_groups", "pricelist_mkl_groups"):
            conn.execute(
                text(
                    f"""
                    INSERT INTO {table} (name, sort_index, display_properties_in_list, display_as_tiles, tiles_per_page, admin_only)
                    SELECT :name, 9990, TRUE, FALSE, 4, TRUE
                    WHERE NOT EXISTS (
                        SELECT 1 FROM {table} WHERE TRIM(name) = :name
                    )
                    """
                ),
                {"name": ADMIN_FOLDER},
            )
            conn.execute(
                text(
                    f"""
                    UPDATE {table}
                    SET admin_only = TRUE
                    WHERE TRIM(name) = :name
                    """
                ),
                {"name": ADMIN_FOLDER},
            )

        # Карточки уже в этой папке — только для админа
        for items_table in ("pricelist_items", "pricelist_rx_items", "pricelist_mkl_items"):
            conn.execute(
                text(
                    f"""
                    UPDATE {items_table}
                    SET admin_only = TRUE
                    WHERE TRIM("group") = :name
                    """
                ),
                {"name": ADMIN_FOLDER},
            )

        conn.commit()
        print(f"OK: папка «{ADMIN_FOLDER}» в складе / RX / МКЛ (admin_only)")
    except Exception as e:
        print(f"Error: {e}")
        raise
