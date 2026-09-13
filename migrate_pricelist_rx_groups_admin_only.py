"""
Добавляет admin_only в pricelist_rx_groups; для группы «Администратор» включает флаг
и проставляет admin_only у всех позиций этой группы.
Запуск: python migrate_pricelist_rx_groups_admin_only.py
"""
from database import engine
from sqlalchemy import text

with engine.begin() as conn:
    conn.execute(
        text(
            "ALTER TABLE pricelist_rx_groups "
            "ADD COLUMN IF NOT EXISTS admin_only BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    conn.execute(
        text(
            "UPDATE pricelist_rx_groups SET admin_only = TRUE "
            "WHERE TRIM(name) = 'Администратор'"
        )
    )
    conn.execute(
        text(
            "UPDATE pricelist_rx_items SET admin_only = TRUE "
            "WHERE TRIM(\"group\") = 'Администратор'"
        )
    )
print("OK: pricelist_rx_groups.admin_only + группа «Администратор»")
