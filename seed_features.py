#!/usr/bin/env python3
"""Seed features table with sample data"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Feature

DATABASE_URL = "postgresql://postgres:postgres@localhost/crm"

def seed_features():
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Check if features already exist
        existing = db.query(Feature).count()
        if existing > 0:
            print(f"Features table already has {existing} records. Skipping seed.")
            return
        
        features_data = [
            {"name": "Защита от УФ"},
            {"name": "Антибликовое покрытие"},
            {"name": "Гидрофобное покрытие"},
            {"name": "Олеофобное покрытие"},
            {"name": "Рекомендованы для вождения"},
            {"name": "Фотохромные"},
            {"name": "Поляризационные"},
            {"name": "Без покрытия"},
        ]
        
        for data in features_data:
            feature = Feature(**data)
            db.add(feature)
        
        db.commit()
        print(f"Successfully seeded {len(features_data)} features")
        
    except Exception as e:
        print(f"Error seeding features: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_features()
