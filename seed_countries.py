"""
Скрипт для загрузки списка стран в базу данных
"""
from database import SessionLocal
from models import Country

countries_data = [
    {"name": "Россия", "code": "RU"},
    {"name": "Китай", "code": "CN"},
    {"name": "Япония", "code": "JP"},
    {"name": "Южная Корея", "code": "KR"},
    {"name": "Германия", "code": "DE"},
    {"name": "Франция", "code": "FR"},
    {"name": "Италия", "code": "IT"},
    {"name": "Испания", "code": "ES"},
    {"name": "Великобритания", "code": "GB"},
    {"name": "США", "code": "US"},
    {"name": "Канада", "code": "CA"},
    {"name": "Бразилия", "code": "BR"},
    {"name": "Австралия", "code": "AU"},
    {"name": "Индия", "code": "IN"},
    {"name": "Турция", "code": "TR"},
    {"name": "Польша", "code": "PL"},
    {"name": "Нидерланды", "code": "NL"},
    {"name": "Бельгия", "code": "BE"},
    {"name": "Швейцария", "code": "CH"},
    {"name": "Австрия", "code": "AT"},
    {"name": "Швеция", "code": "SE"},
    {"name": "Норвегия", "code": "NO"},
    {"name": "Финляндия", "code": "FI"},
    {"name": "Дания", "code": "DK"},
    {"name": "Португалия", "code": "PT"},
    {"name": "Греция", "code": "GR"},
    {"name": "Чехия", "code": "CZ"},
    {"name": "Венгрия", "code": "HU"},
    {"name": "Румыния", "code": "RO"},
    {"name": "Болгария", "code": "BG"},
    {"name": "Украина", "code": "UA"},
    {"name": "Беларусь", "code": "BY"},
    {"name": "Казахстан", "code": "KZ"},
    {"name": "Узбекистан", "code": "UZ"},
    {"name": "Азербайджан", "code": "AZ"},
    {"name": "Армения", "code": "AM"},
    {"name": "Грузия", "code": "GE"},
    {"name": "Израиль", "code": "IL"},
    {"name": "ОАЭ", "code": "AE"},
    {"name": "Саудовская Аравия", "code": "SA"},
    {"name": "Египет", "code": "EG"},
    {"name": "ЮАР", "code": "ZA"},
    {"name": "Мексика", "code": "MX"},
    {"name": "Аргентина", "code": "AR"},
    {"name": "Чили", "code": "CL"},
    {"name": "Колумбия", "code": "CO"},
    {"name": "Перу", "code": "PE"},
    {"name": "Венесуэла", "code": "VE"},
    {"name": "Таиланд", "code": "TH"},
    {"name": "Вьетнам", "code": "VN"},
    {"name": "Индонезия", "code": "ID"},
    {"name": "Малайзия", "code": "MY"},
    {"name": "Сингапур", "code": "SG"},
    {"name": "Филиппины", "code": "PH"},
    {"name": "Пакистан", "code": "PK"},
    {"name": "Бангладеш", "code": "BD"},
    {"name": "Иран", "code": "IR"},
    {"name": "Ирак", "code": "IQ"},
    {"name": "Сирия", "code": "SY"},
    {"name": "Ливан", "code": "LB"},
    {"name": "Иордания", "code": "JO"},
    {"name": "Кувейт", "code": "KW"},
    {"name": "Катар", "code": "QA"},
    {"name": "Бахрейн", "code": "BH"},
    {"name": "Оман", "code": "OM"},
    {"name": "Йемен", "code": "YE"},
    {"name": "Афганистан", "code": "AF"},
    {"name": "Непал", "code": "NP"},
    {"name": "Шри-Ланка", "code": "LK"},
    {"name": "Мьянма", "code": "MM"},
    {"name": "Камбоджа", "code": "KH"},
    {"name": "Лаос", "code": "LA"},
    {"name": "Монголия", "code": "MN"},
    {"name": "КНДР", "code": "KP"},
    {"name": "Тайвань", "code": "TW"},
    {"name": "Гонконг", "code": "HK"},
    {"name": "Макао", "code": "MO"},
    {"name": "Новая Зеландия", "code": "NZ"},
]

def seed_countries():
    db = SessionLocal()
    try:
        # Проверяем, есть ли уже страны
        existing_count = db.query(Country).count()
        if existing_count > 0:
            print(f"В базе уже есть {existing_count} стран. Пропускаем загрузку.")
            return
        
        # Добавляем страны
        for country_data in countries_data:
            country = Country(**country_data)
            db.add(country)
        
        db.commit()
        print(f"Успешно загружено {len(countries_data)} стран!")
        
    except Exception as e:
        print(f"Ошибка при загрузке стран: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_countries()
