"""
Добавляет базовые значения в справочники (ставки НДС и т.д.).
Запуск: python seed_refs.py
"""
from database import SessionLocal
from models import VatRate

db = SessionLocal()
for name in ["Без НДС", "5%", "22%"]:
    if not db.query(VatRate).filter(VatRate.name == name).first():
        db.add(VatRate(name=name))
        print(f"Добавлена ставка НДС: {name}")
db.commit()
db.close()
print("Готово.")
