"""
Создаёт таблицу pricelist_groups.
Группы по умолчанию добавляются только при первом развёртывании (пустая таблица),
чтобы деплой не восстанавливал удалённые группы.

Запуск: из корня backend: python migrate_pricelist_groups.py
"""
from database import engine
from sqlalchemy import text

DEFAULT_GROUPS = ["Однофокальные", "Прогрессивные", "Торические"]

with engine.connect() as conn:
    conn.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS pricelist_groups (
            id SERIAL PRIMARY KEY,
            name VARCHAR(128) NOT NULL UNIQUE
        )
    """
        )
    )
    conn.commit()
    print("OK: table pricelist_groups")

    count = conn.execute(text("SELECT COUNT(*) FROM pricelist_groups")).scalar() or 0
    if count == 0:
        for name in DEFAULT_GROUPS:
            conn.execute(
                text("INSERT INTO pricelist_groups (name) VALUES (:name) ON CONFLICT (name) DO NOTHING"),
                {"name": name},
            )
            conn.commit()
            print(f"OK: group {name} (начальное заполнение)")
    else:
        print(f"OK: группы по умолчанию не добавлялись (в таблице уже {count} записей)")
print("Done.")
