"""
Создаёт пользователя admin с паролем Dsaik098x_ и группу «Администратор».
Запуск: python seed_admin.py
"""
import sys
from sqlalchemy import text

from auth import get_password_hash
from database import engine, SessionLocal, Base
from models import Group

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# IMPORTANT: use raw SQL to keep seed script compatible with older DB schemas
# (deploy runs this before migrate_*.py).
admin_id = db.execute(text("SELECT id FROM users WHERE username=:u LIMIT 1"), {"u": "admin"}).scalar()
if not admin_id:
    db.execute(
        text(
            """
            INSERT INTO users (username, hashed_password, is_active)
            VALUES (:u, :hp, true)
            """
        ),
        {"u": "admin", "hp": get_password_hash("Dsaik098x_")},
    )
    db.commit()
    admin_id = db.execute(text("SELECT id FROM users WHERE username=:u LIMIT 1"), {"u": "admin"}).scalar()
    print("Пользователь admin создан. Логин: admin, пароль: Dsaik098x_")
else:
    print("Пользователь admin уже существует.")

admin_group = db.query(Group).filter(Group.name == "Администратор").first()
if not admin_group:
    admin_group = Group(name="Администратор")
    db.add(admin_group)
    db.commit()
    db.refresh(admin_group)
    print("Группа «Администратор» создана.")
else:
    print("Группа «Администратор» уже существует.")

link_exists = db.execute(
    text("SELECT 1 FROM user_groups WHERE user_id=:uid AND group_id=:gid LIMIT 1"),
    {"uid": int(admin_id), "gid": int(admin_group.id)},
).scalar()
if not link_exists:
    db.execute(
        text("INSERT INTO user_groups (user_id, group_id) VALUES (:uid, :gid)"),
        {"uid": int(admin_id), "gid": int(admin_group.id)},
    )
    db.commit()
    print("Пользователь admin добавлен в группу «Администратор».")
else:
    print("admin уже в группе «Администратор».")

manager_group = db.query(Group).filter(Group.name == "Менеджер").first()
if not manager_group:
    manager_group = Group(name="Менеджер")
    db.add(manager_group)
    db.commit()
    print("Группа «Менеджер» создана (для укороченного вида заказов).")
else:
    print("Группа «Менеджер» уже существует.")

consultants_group = db.query(Group).filter(Group.name == "Консультанты").first()
if not consultants_group:
    consultants_group = Group(name="Консультанты")
    db.add(consultants_group)
    db.commit()
    print("Группа «Консультанты» создана (для отправки сменных отчётов).")
else:
    print("Группа «Консультанты» уже существует.")

db.close()
