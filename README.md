# CRM Backend

## Установка

```bash
cd crm-backend
python -m venv venv
source venv/bin/activate   # Linux/Mac
# или venv\Scripts\activate на Windows
pip install -r requirements.txt
```

## PostgreSQL

Создайте БД и пользователя (если ещё нет):

```sql
CREATE USER postgres WITH PASSWORD 'postgres';
CREATE DATABASE crm OWNER postgres;
```

Или измените `database_url` в `.env` или в `config.py`.

## Запуск

```bash
# Создать таблицы и пользователя admin
python seed_admin.py

# Запуск сервера
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API: http://localhost:8000  
Документация: http://localhost:8000/docs

Логин: **admin**  
Пароль: **Dsaik098x_**
