"""Добавляет стандартные коэффициенты, если их ещё нет."""
from database import SessionLocal
from models import Coefficient

DEFAULTS = ["1.5", "1.6", "1.67", "1.74"]

def main():
    db = SessionLocal()
    try:
        for name in DEFAULTS:
            if db.query(Coefficient).filter(Coefficient.name == name).first():
                continue
            db.add(Coefficient(name=name))
        db.commit()
        print("OK: coefficients")
    finally:
        db.close()

if __name__ == "__main__":
    main()
