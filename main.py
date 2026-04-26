import json
import logging
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text as sa_text
from pathlib import Path
from sqlalchemy import func as sa_func
from pydantic import BaseModel

from database import get_db, engine, Base
from models import Group, User
from schemas import Token, UserLogin, MeResponse, SetupPasswordRequest
from auth import verify_password, get_password_hash, create_access_token, decode_token
from routers import users as users_router
from routers import groups as groups_router
from routers import orders as orders_router
from routers import references as references_router
from routers import upload as upload_router
from routers import reports as reports_router
from routers import central_cash as central_cash_router
from routers import work_schedule as work_schedule_router
from routers import chat as chat_router
from routers import portal_tasks as portal_tasks_router
from routers import supply_tickets as supply_tickets_router
from routers import training as training_router
from routers import normative_acts as normative_acts_router
from routers import drive as drive_router
from routers import offline_export as offline_export_router
from routers.orders import create_order_from_1c, _order_to_response
from deps import get_current_user, get_admin_user, get_impersonator_username, is_admin, is_manager, is_consultant
from report_required_validation import ALLOWED_REPORT_REQUIRED_KEYS
from reports_table_columns import (
    ALLOWED_REPORT_TABLE_COLUMN_KEYS,
    CANONICAL_REPORT_TABLE_COLUMNS_ADMIN,
    normalize_report_table_columns,
)
from chat_service import add_user_joined_general_chat_message, ensure_general_chat_member

app = FastAPI(title="CRM API")
GROUP_PERMISSIONS_FILE = Path("/home/crm-backend/logs/group_page_permissions.json")
REPORT_REQUIRED_FIELDS_FILE = Path("/home/crm-backend/logs/report_required_fields.json")
REPORTS_TABLE_COLUMNS_DEFAULT_FILE = Path("/home/crm-backend/logs/reports_table_columns_default.json")
USER_REPORTS_TABLE_COLUMNS_FILE = Path("/home/crm-backend/logs/user_reports_table_columns.json")
SIDEBAR_VIDEO_SETTINGS_FILE = Path("/home/crm-backend/logs/sidebar_video_settings.json")
SIDEBAR_MENU_ORDER_SETTINGS_FILE = Path("/home/crm-backend/logs/sidebar_menu_order_settings.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://83.222.27.232",
        "https://mosoptika-study.ru",
        "http://mosoptika-study.ru",
        "https://www.mosoptika-study.ru",
        "http://www.mosoptika-study.ru",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    # --- Chat group schema back-compat ---
    # New field `chat_messages.group_dialog_id` + group tables.
    # `create_all()` does not alter existing tables, so we add the missing column here.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    """
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'chat_messages'
                          AND column_name = 'group_dialog_id'
                      ) THEN
                        ALTER TABLE chat_messages ADD COLUMN group_dialog_id INTEGER NULL;
                      END IF;
                    END
                    $$;
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints tc
                        WHERE tc.constraint_name = 'chat_messages_group_dialog_id_fkey'
                      ) THEN
                        ALTER TABLE chat_messages
                          ADD CONSTRAINT chat_messages_group_dialog_id_fkey
                          FOREIGN KEY (group_dialog_id)
                          REFERENCES group_chat_dialogs(id)
                          ON DELETE CASCADE;
                      END IF;
                    END
                    $$;
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'chat_messages'
                          AND column_name = 'reply_to_message_id'
                      ) THEN
                        ALTER TABLE chat_messages ADD COLUMN reply_to_message_id INTEGER NULL;
                      END IF;
                    END
                    $$;
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints tc
                        WHERE tc.constraint_name = 'chat_messages_reply_to_message_id_fkey'
                      ) THEN
                        ALTER TABLE chat_messages
                          ADD CONSTRAINT chat_messages_reply_to_message_id_fkey
                          FOREIGN KEY (reply_to_message_id)
                          REFERENCES chat_messages(id)
                          ON DELETE SET NULL;
                      END IF;
                    END
                    $$;
                    """
                )
            )
    except Exception:
        # If ALTER fails (permissions/DB already has everything), we don't block startup.
        pass
    # Для простого dev-режима добавляем колонку без миграций,
    # чтобы можно было показывать "последний вход" в таблице пользователей.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ"
                )
            )
    except Exception:
        # Если БД уже имеет нужную колонку или ALTER недоступен — не падаем.
        pass

    # Возвраты по чекам (доп. поля в форме) — храним в JSONB без отдельных миграций.
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS returns_details JSONB"))
    except Exception:
        pass

    # Normative acts tables/columns.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE normative_acts ADD COLUMN IF NOT EXISTS section VARCHAR(128) DEFAULT 'Общее' NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE normative_acts ADD COLUMN IF NOT EXISTS preview_image_url VARCHAR(512)"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE normative_acts ADD COLUMN IF NOT EXISTS visible_user_ids JSONB"
                )
            )
            conn.execute(
                sa_text(
                    "UPDATE normative_acts SET section='Общее' WHERE section IS NULL OR btrim(section)=''"
                )
            )
            conn.execute(sa_text("ALTER TABLE normative_acts ADD COLUMN IF NOT EXISTS attachment_url VARCHAR(512)"))
            conn.execute(sa_text("ALTER TABLE normative_acts ADD COLUMN IF NOT EXISTS attachment_filename VARCHAR(256)"))
    except Exception:
        pass

    # Черновики отчёта (draft).
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS is_draft BOOLEAN DEFAULT FALSE NOT NULL"))
    except Exception:
        pass

    # Pricelist: дополнительные параметры (UV-защита, материал)
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS uv_protection BOOLEAN DEFAULT FALSE NOT NULL"))
    except Exception:
        pass

    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS material TEXT"))
    except Exception:
        pass

    # При удалении производителя оставляем позиции прайслиста, обнуляя ссылку на производителя.
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE pricelist_items ALTER COLUMN manufacturer_id DROP NOT NULL"))
            conn.execute(
                sa_text(
                    """
                    DO $$
                    BEGIN
                      IF EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints tc
                        WHERE tc.constraint_name = 'pricelist_items_manufacturer_id_fkey'
                      ) THEN
                        ALTER TABLE pricelist_items
                          DROP CONSTRAINT pricelist_items_manufacturer_id_fkey;
                      END IF;
                      ALTER TABLE pricelist_items
                        ADD CONSTRAINT pricelist_items_manufacturer_id_fkey
                        FOREIGN KEY (manufacturer_id)
                        REFERENCES manufacturers(id)
                        ON DELETE SET NULL;
                    END
                    $$;
                    """
                )
            )
    except Exception:
        pass

    # Настройки отображения поставщиков на странице каталога линз.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE manufacturers ADD COLUMN IF NOT EXISTS show_in_lens_catalog BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE manufacturers ADD COLUMN IF NOT EXISTS open_pdf_in_lens_catalog BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE manufacturers ADD COLUMN IF NOT EXISTS show_country_in_lens_catalog BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE manufacturers ADD COLUMN IF NOT EXISTS show_description_in_lens_catalog BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
    except Exception:
        pass

    # Дополнительные пользовательские поля карточки прайслиста.
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS custom_values JSONB"))
            conn.execute(
                sa_text(
                    "ALTER TABLE custom_field_definitions ADD COLUMN IF NOT EXISTS show_in_warehouse BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE custom_field_definitions ADD COLUMN IF NOT EXISTS show_in_rx BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE custom_field_definitions ADD COLUMN IF NOT EXISTS show_in_mkl BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS pricelist_publication_jobs (
                        id SERIAL PRIMARY KEY,
                        catalog VARCHAR(16) NOT NULL,
                        action VARCHAR(16) NOT NULL DEFAULT 'upsert',
                        target_item_id INTEGER,
                        payload_json JSONB NOT NULL,
                        publish_at TIMESTAMPTZ NOT NULL,
                        status VARCHAR(16) NOT NULL DEFAULT 'pending',
                        created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        applied_at TIMESTAMPTZ,
                        error_text TEXT
                    )
                    """
                )
            )
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_pricelist_publication_jobs_status ON pricelist_publication_jobs(status)"))
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_pricelist_publication_jobs_publish_at ON pricelist_publication_jobs(publish_at)"))
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_pricelist_publication_jobs_catalog ON pricelist_publication_jobs(catalog)"))
            conn.execute(sa_text("ALTER TABLE pricelist_publication_jobs ADD COLUMN IF NOT EXISTS batch_code VARCHAR(64)"))
            conn.execute(sa_text("ALTER TABLE pricelist_publication_jobs ADD COLUMN IF NOT EXISTS batch_name VARCHAR(255)"))
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_pricelist_publication_jobs_batch_code ON pricelist_publication_jobs(batch_code)"))
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS web_push_subscriptions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        endpoint VARCHAR(1024) NOT NULL UNIQUE,
                        p256dh VARCHAR(512) NOT NULL,
                        auth VARCHAR(512) NOT NULL,
                        platform VARCHAR(32) NOT NULL DEFAULT 'web',
                        user_agent VARCHAR(1024),
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_web_push_subscriptions_user_id ON web_push_subscriptions(user_id)"))
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_web_push_subscriptions_endpoint ON web_push_subscriptions(endpoint)"))
    except Exception:
        pass

    # Прайслист: флаг скрытия перехода в карточку товара из списка.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS hide_detail_link BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
    except Exception:
        pass

    # Прайслист: флаг включения калькулятора транспозиции в карточке товара.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS enable_transposition_calc BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_rx_items ADD COLUMN IF NOT EXISTS enable_transposition_calc BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
    except Exception:
        pass

    # Прайслист: скрыть фото в карточке товара (файлы остаются, не показываются на публичной странице).
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS hide_photo BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_rx_items ADD COLUMN IF NOT EXISTS hide_photo BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
    except Exception:
        pass

    # Прайслист: цена «от N» (префикс в UI).
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS price_from BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_rx_items ADD COLUMN IF NOT EXISTS price_from BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
    except Exception:
        pass

    # Пользователи: телефон и дата рождения.
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(64)"))
            conn.execute(sa_text("ALTER TABLE users ADD COLUMN IF NOT EXISTS birth_date DATE"))
            conn.execute(sa_text("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(1024)"))
    except Exception:
        pass

    # Групповые чаты: изображение группы.
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE group_chat_dialogs ADD COLUMN IF NOT EXISTS image_url VARCHAR(1024)"))
    except Exception:
        pass

    # Отчёты: детализация «долг» в зарплатном блоке.
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS dolg_details JSONB"))
    except Exception:
        pass

    # Отчёты: остаток наличных факт (подстановка «утро» на следующую смену из last-ost).
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE daily_reports ADD COLUMN IF NOT EXISTS ost_fact NUMERIC(15, 2)"))
    except Exception:
        pass

    # Склады: связь с организацией из справочника.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL"
                )
            )
    except Exception:
        pass

    # Справочники «Взято за что», «Откуда взято» и «Долг за что».
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS taken_reasons (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(256) NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS taken_sources (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(256) NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS debt_reasons (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(256) NOT NULL
                    )
                    """
                )
            )
    except Exception:
        pass

    # Прайслист: индекс сортировки позиции внутри группы.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_items ADD COLUMN IF NOT EXISTS sort_index INTEGER DEFAULT 500 NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_rx_items ADD COLUMN IF NOT EXISTS sort_index INTEGER DEFAULT 500 NOT NULL"
                )
            )
    except Exception:
        pass

    # Группы прайслиста: флаг отображения блока свойств (SPH/CYL/Шаг/Ø) в списке.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_groups ADD COLUMN IF NOT EXISTS display_properties_in_list BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
    except Exception:
        pass

    # Группы прайслиста: режим плитки и число карточек на странице.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_groups ADD COLUMN IF NOT EXISTS display_as_tiles BOOLEAN DEFAULT FALSE NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE pricelist_groups ADD COLUMN IF NOT EXISTS tiles_per_page INTEGER DEFAULT 4 NOT NULL"
                )
            )
    except Exception:
        pass

    # Отметки «инкассация получена» по точке и периоду (отчёт /reports/encashment).
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS encashment_receipts (
                        id SERIAL PRIMARY KEY,
                        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
                        period_from DATE NOT NULL,
                        period_to DATE NOT NULL,
                        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        received_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        CONSTRAINT uq_encashment_receipt_wh_period UNIQUE (warehouse_id, period_from, period_to)
                    )
                    """
                )
            )
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_encashment_receipts_wh ON encashment_receipts(warehouse_id)"))
    except Exception:
        pass

    # Ручные удержания по пользователям (отдельный модуль /reports/withholding).
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS manual_withholdings (
                        id SERIAL PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        amount NUMERIC(15,2) NOT NULL,
                        warehouse_id INTEGER REFERENCES warehouses(id) ON DELETE SET NULL,
                        report_month VARCHAR(32),
                        reason VARCHAR(256),
                        note TEXT,
                        recorded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
                    )
                    """
                )
            )
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_manual_withholdings_user_id ON manual_withholdings(user_id)"))
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_manual_withholdings_warehouse_id ON manual_withholdings(warehouse_id)"))
    except Exception:
        pass

    # Пользователи: отключение push/бейджа чата.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_notifications_enabled BOOLEAN DEFAULT TRUE NOT NULL"
                )
            )
            conn.execute(sa_text("UPDATE users SET chat_notifications_enabled = TRUE WHERE chat_notifications_enabled IS NULL"))
    except Exception:
        pass

    # Варианты для кастомных полей: снимаем ограничение длины значения.
    try:
        with engine.begin() as conn:
            conn.execute(sa_text("ALTER TABLE custom_field_options ALTER COLUMN value TYPE TEXT"))
    except Exception:
        pass

    # Supply tickets: статус заявки (open/closed) для фильтрации и архива.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE supply_tickets ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'open' NOT NULL"
                )
            )
            conn.execute(sa_text("UPDATE supply_tickets SET status='open' WHERE status IS NULL OR status=''"))
    except Exception:
        pass

    # Chat message reads table
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_message_reads (
                      id SERIAL PRIMARY KEY,
                      message_id INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
                      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                      read_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1
                        FROM pg_indexes
                        WHERE indexname = 'idx_message_user_read'
                      ) THEN
                        CREATE UNIQUE INDEX idx_message_user_read ON chat_message_reads(message_id, user_id);
                      END IF;
                    END
                    $$;
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1
                        FROM pg_indexes
                        WHERE indexname = 'idx_chat_message_reads_message_id'
                      ) THEN
                        CREATE INDEX idx_chat_message_reads_message_id ON chat_message_reads(message_id);
                      END IF;
                    END
                    $$;
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1
                        FROM pg_indexes
                        WHERE indexname = 'idx_chat_message_reads_user_id'
                      ) THEN
                        CREATE INDEX idx_chat_message_reads_user_id ON chat_message_reads(user_id);
                      END IF;
                    END
                    $$;
                    """
                )
            )
    except Exception:
        pass

    # Training articles: разделы и картинка анонса.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE training_articles ADD COLUMN IF NOT EXISTS section VARCHAR(128) DEFAULT 'Общее' NOT NULL"
                )
            )
            conn.execute(
                sa_text(
                    "ALTER TABLE training_articles ADD COLUMN IF NOT EXISTS preview_image_url VARCHAR(512)"
                )
            )
            conn.execute(
                sa_text(
                    "UPDATE training_articles SET section='Общее' WHERE section IS NULL OR btrim(section)=''"
                )
            )
    except Exception:
        pass

    # Задачник: ответственный и дедлайн.
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "ALTER TABLE portal_tasks ADD COLUMN IF NOT EXISTS assignee_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL"
                )
            )
            conn.execute(sa_text("ALTER TABLE portal_tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ"))
    except Exception:
        pass

    # Курсы обучения (конструктор, прогресс).
    try:
        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS training_courses (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(256) NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        preview_image_url VARCHAR(512),
                        is_published BOOLEAN NOT NULL DEFAULT FALSE,
                        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            conn.execute(
                sa_text(
                    """
                    CREATE TABLE IF NOT EXISTS training_user_course_progress (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        course_id INTEGER NOT NULL REFERENCES training_courses(id) ON DELETE CASCADE,
                        progress JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_training_progress_user_course UNIQUE (user_id, course_id)
                    )
                    """
                )
            )
            conn.execute(
                sa_text(
                    "CREATE INDEX IF NOT EXISTS ix_training_progress_user ON training_user_course_progress(user_id)"
                )
            )
            conn.execute(
                sa_text(
                    "CREATE INDEX IF NOT EXISTS ix_training_progress_course ON training_user_course_progress(course_id)"
                )
            )
    except Exception:
        pass


@app.post("/api/auth/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    # Логин должен быть нечувствительным к регистру (в т.ч. для приглашённых).
    # Нормализуем пробелы и сравниваем в lower-case.
    username_norm = " ".join((data.username or "").split())
    user = (
        db.query(User)
        .filter(sa_func.lower(User.username) == sa_func.lower(username_norm))
        .first()
    )
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь деактивирован")

    # Пустой пароль = проверка "приглашённый пользователь, пароль ещё не задан"
    if not data.password or not data.password.strip():
        if not user.hashed_password:
            raise HTTPException(status_code=428, detail="PASSWORD_SETUP_REQUIRED")
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    # Если участника ещё нет в общем чате — добавляем.
    # Важно: если администратор "вышел", не реактивируем при логине.
    ensure_general_chat_member(db, user, desired_is_active=True, only_create=True)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    token = create_access_token(data={"sub": user.username})
    return Token(access_token=token)


@app.post("/api/auth/setup-password", response_model=Token)
def setup_password(data: SetupPasswordRequest, db: Session = Depends(get_db)):
    # Также делаем lookup по username нечувствительно к регистру.
    username_norm = " ".join((data.username or "").split())
    user = (
        db.query(User)
        .filter(sa_func.lower(User.username) == sa_func.lower(username_norm))
        .first()
    )
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if user.hashed_password:
        raise HTTPException(status_code=400, detail="Пароль уже задан")

    user.hashed_password = get_password_hash(data.password)
    db.commit()
    db.refresh(user)

    # Активация аккаунта -> системное сообщение в общий чат.
    # При этом участник в общем чате должен быть активен.
    ensure_general_chat_member(db, user, desired_is_active=True, only_create=False)
    add_user_joined_general_chat_message(db, user=user)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(data={"sub": user.username})
    return Token(access_token=token)


class MyProfileUpdateBody(BaseModel):
    avatar_url: str | None = None


@app.patch("/api/auth/me/profile", response_model=MeResponse)
def update_my_profile(
    data: MyProfileUpdateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    impersonator_username: str | None = Depends(get_impersonator_username),
):
    current_user.avatar_url = (data.avatar_url or "").strip() or None
    db.commit()
    db.refresh(current_user)
    result = MeResponse.model_validate(current_user)
    result.is_admin = is_admin(current_user)
    result.is_manager = is_manager(current_user)
    result.is_consultant = is_consultant(current_user)
    if result.is_admin:
        result.role = "admin"
    elif result.is_manager:
        result.role = "manager"
    elif result.is_consultant:
        result.role = "consultant"
    else:
        result.role = "user"
    result.impersonator_username = impersonator_username
    return result


@app.get("/api/auth/me", response_model=MeResponse)
def me(
    current_user: User = Depends(get_current_user),
    impersonator_username: str | None = Depends(get_impersonator_username),
):
    data = MeResponse.model_validate(current_user)
    data.is_admin = is_admin(current_user)
    data.is_manager = is_manager(current_user)
    data.is_consultant = is_consultant(current_user)
    if data.is_admin:
        data.role = "admin"
    elif data.is_manager:
        data.role = "manager"
    elif data.is_consultant:
        data.role = "consultant"
    else:
        data.role = "user"
    data.impersonator_username = impersonator_username
    return data


@app.post("/api/auth/impersonate/{user_id}", response_model=Token)
def impersonate_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Выдать токен от имени другого пользователя (только администратор). В JWT: sub=цель, imp=логин админа."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя авторизоваться под собой")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if not target.is_active:
        raise HTTPException(status_code=400, detail="Пользователь деактивирован")
    token = create_access_token(data={"sub": target.username, "imp": admin.username})
    return Token(access_token=token)


@app.post("/api/auth/stop-impersonation", response_model=Token)
def stop_impersonation(request: Request, db: Session = Depends(get_db)):
    """Вернуть токен администратора (только если текущий токен выдан через impersonate)."""
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    token_str = auth_header[7:].strip()
    payload = decode_token(token_str)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Неверный токен")
    imp = payload.get("imp")
    if not imp or str(imp).strip() == "":
        raise HTTPException(status_code=400, detail="Режим входа под пользователем не активен")
    admin = db.query(User).filter(User.username == str(imp).strip()).first()
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail="Администратор не найден")
    if not is_admin(admin):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    token = create_access_token(data={"sub": admin.username})
    return Token(access_token=token)


class GroupPermissionsPayload(BaseModel):
    permissions: dict[str, list[str]] = {}


@app.get("/api/settings/group-permissions", response_model=GroupPermissionsPayload)
def get_group_permissions(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        normalized: dict[str, list[str]] = {}
        if not GROUP_PERMISSIONS_FILE.exists():
            data = {}
        else:
            data = json.loads(GROUP_PERMISSIONS_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}

        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, list):
                normalized[key] = [v for v in value if isinstance(v, str)]

        # Group "Прайс" must never have access to chat.
        price_groups = (
            db.query(Group)
            .filter(sa_func.lower(Group.name).in_(["прайс", "price"]))
            .all()
        )
        for group in price_groups:
            group_key = str(group.id)
            denied = normalized.get(group_key, [])
            if "chat" not in denied:
                denied.append("chat")
            normalized[group_key] = denied

        return GroupPermissionsPayload(permissions=normalized)
    except Exception:
        return GroupPermissionsPayload(permissions={})


@app.put("/api/settings/group-permissions", response_model=GroupPermissionsPayload)
def update_group_permissions(payload: GroupPermissionsPayload, current_user: User = Depends(get_current_user)):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    normalized: dict[str, list[str]] = {}
    for key, value in payload.permissions.items():
        if not isinstance(key, str) or not isinstance(value, list):
            continue
        normalized[key] = [v for v in value if isinstance(v, str)]
    GROUP_PERMISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GROUP_PERMISSIONS_FILE.write_text(json.dumps(normalized, ensure_ascii=False), encoding="utf-8")
    return GroupPermissionsPayload(permissions=normalized)


class ReportRequiredFieldsPayload(BaseModel):
    required: list[str] = []


@app.get("/api/settings/report-required-fields", response_model=ReportRequiredFieldsPayload)
def get_report_required_fields(_: User = Depends(get_current_user)):
    """Список обязательных полей отчёта (для формы и проверки на сервере)."""
    if not REPORT_REQUIRED_FIELDS_FILE.exists():
        return ReportRequiredFieldsPayload(required=[])
    try:
        data = json.loads(REPORT_REQUIRED_FIELDS_FILE.read_text(encoding="utf-8"))
        req = data.get("required", [])
        if not isinstance(req, list):
            return ReportRequiredFieldsPayload(required=[])
        clean = [x for x in req if isinstance(x, str) and x in ALLOWED_REPORT_REQUIRED_KEYS]
        return ReportRequiredFieldsPayload(required=clean)
    except Exception:
        return ReportRequiredFieldsPayload(required=[])


@app.put("/api/settings/report-required-fields", response_model=ReportRequiredFieldsPayload)
def update_report_required_fields(
    payload: ReportRequiredFieldsPayload,
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    clean = [x for x in payload.required if isinstance(x, str) and x in ALLOWED_REPORT_REQUIRED_KEYS]
    REPORT_REQUIRED_FIELDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_REQUIRED_FIELDS_FILE.write_text(
        json.dumps({"required": clean}, ensure_ascii=False),
        encoding="utf-8",
    )
    return ReportRequiredFieldsPayload(required=clean)


def _load_reports_default_columns_raw() -> list[str] | None:
    if not REPORTS_TABLE_COLUMNS_DEFAULT_FILE.exists():
        return None
    try:
        data = json.loads(REPORTS_TABLE_COLUMNS_DEFAULT_FILE.read_text(encoding="utf-8"))
        cols = data.get("columns", [])
        if not isinstance(cols, list):
            return None
        return [x for x in cols if isinstance(x, str) and x in ALLOWED_REPORT_TABLE_COLUMN_KEYS]
    except Exception:
        return None


def _load_user_reports_columns_map() -> dict[str, list[str]]:
    if not USER_REPORTS_TABLE_COLUMNS_FILE.exists():
        return {}
    try:
        data = json.loads(USER_REPORTS_TABLE_COLUMNS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: dict[str, list[str]] = {}
        for uid, cols in data.items():
            if not isinstance(uid, str) or not isinstance(cols, list):
                continue
            out[uid] = [x for x in cols if isinstance(x, str) and x in ALLOWED_REPORT_TABLE_COLUMN_KEYS]
        return out
    except Exception:
        return {}


def _save_user_reports_columns_map(m: dict[str, list[str]]) -> None:
    USER_REPORTS_TABLE_COLUMNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_REPORTS_TABLE_COLUMNS_FILE.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


class ReportsTableColumnsPayload(BaseModel):
    columns: list[str] = []


class ReportsTableColumnsResponse(BaseModel):
    default_columns: list[str]
    mine_columns: list[str] | None = None


class SidebarVideoSettingsPayload(BaseModel):
    video_url: str | None = None
    visible_group_ids: list[int] = []


class SidebarMenuOrderSettingsPayload(BaseModel):
    order: list[str] = []


@app.get("/api/settings/reports-table-columns", response_model=ReportsTableColumnsResponse)
def get_reports_table_columns(current_user: User = Depends(get_current_user)):
    """Общий порядок столбцов и персональный (если задан)."""
    admin = is_admin(current_user)
    raw_default = _load_reports_default_columns_raw()
    base_default = raw_default if raw_default else CANONICAL_REPORT_TABLE_COLUMNS_ADMIN
    default_columns = normalize_report_table_columns(base_default, for_admin=admin)

    umap = _load_user_reports_columns_map()
    mine_raw = umap.get(str(current_user.id))
    mine_columns: list[str] | None = None
    if mine_raw is not None:
        mine_columns = normalize_report_table_columns(mine_raw, for_admin=admin)

    return ReportsTableColumnsResponse(default_columns=default_columns, mine_columns=mine_columns)


@app.put("/api/settings/reports-table-columns/default", response_model=ReportsTableColumnsPayload)
def put_reports_table_columns_default(
    payload: ReportsTableColumnsPayload,
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    clean = normalize_report_table_columns(payload.columns, for_admin=True)
    REPORTS_TABLE_COLUMNS_DEFAULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORTS_TABLE_COLUMNS_DEFAULT_FILE.write_text(
        json.dumps({"columns": clean}, ensure_ascii=False),
        encoding="utf-8",
    )
    return ReportsTableColumnsPayload(columns=clean)


@app.put("/api/settings/reports-table-columns/mine", response_model=ReportsTableColumnsPayload)
def put_reports_table_columns_mine(
    payload: ReportsTableColumnsPayload,
    current_user: User = Depends(get_current_user),
):
    admin = is_admin(current_user)
    clean = normalize_report_table_columns(payload.columns, for_admin=admin)
    umap = _load_user_reports_columns_map()
    umap[str(current_user.id)] = clean
    _save_user_reports_columns_map(umap)
    return ReportsTableColumnsPayload(columns=clean)


@app.delete("/api/settings/reports-table-columns/mine")
def delete_reports_table_columns_mine(current_user: User = Depends(get_current_user)):
    umap = _load_user_reports_columns_map()
    uid = str(current_user.id)
    if uid in umap:
        del umap[uid]
        _save_user_reports_columns_map(umap)
    return {"ok": True}


@app.get("/api/settings/sidebar-video", response_model=SidebarVideoSettingsPayload)
def get_sidebar_video_settings(_: User = Depends(get_current_user)):
    if not SIDEBAR_VIDEO_SETTINGS_FILE.exists():
        return SidebarVideoSettingsPayload(video_url=None, visible_group_ids=[])
    try:
        data = json.loads(SIDEBAR_VIDEO_SETTINGS_FILE.read_text(encoding="utf-8"))
        video_url_raw = data.get("video_url")
        groups_raw = data.get("visible_group_ids", [])
        video_url = str(video_url_raw).strip() if isinstance(video_url_raw, str) and video_url_raw.strip() else None
        visible_group_ids = []
        if isinstance(groups_raw, list):
            for v in groups_raw:
                try:
                    iv = int(v)
                except Exception:
                    continue
                if iv > 0 and iv not in visible_group_ids:
                    visible_group_ids.append(iv)
        return SidebarVideoSettingsPayload(video_url=video_url, visible_group_ids=visible_group_ids)
    except Exception:
        return SidebarVideoSettingsPayload(video_url=None, visible_group_ids=[])


@app.put("/api/settings/sidebar-video", response_model=SidebarVideoSettingsPayload)
def put_sidebar_video_settings(
    payload: SidebarVideoSettingsPayload,
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    video_url = (payload.video_url or "").strip() or None
    visible_group_ids: list[int] = []
    for v in payload.visible_group_ids:
        try:
            iv = int(v)
        except Exception:
            continue
        if iv > 0 and iv not in visible_group_ids:
            visible_group_ids.append(iv)
    SIDEBAR_VIDEO_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIDEBAR_VIDEO_SETTINGS_FILE.write_text(
        json.dumps({"video_url": video_url, "visible_group_ids": visible_group_ids}, ensure_ascii=False),
        encoding="utf-8",
    )
    return SidebarVideoSettingsPayload(video_url=video_url, visible_group_ids=visible_group_ids)


@app.get("/api/settings/sidebar-menu-order", response_model=SidebarMenuOrderSettingsPayload)
def get_sidebar_menu_order_settings(_: User = Depends(get_current_user)):
    if not SIDEBAR_MENU_ORDER_SETTINGS_FILE.exists():
        return SidebarMenuOrderSettingsPayload(order=[])
    try:
        data = json.loads(SIDEBAR_MENU_ORDER_SETTINGS_FILE.read_text(encoding="utf-8"))
        raw = data.get("order", [])
        if not isinstance(raw, list):
            return SidebarMenuOrderSettingsPayload(order=[])
        order: list[str] = []
        for v in raw:
            if not isinstance(v, str):
                continue
            key = v.strip()
            if not key or key in order:
                continue
            order.append(key)
        return SidebarMenuOrderSettingsPayload(order=order)
    except Exception:
        return SidebarMenuOrderSettingsPayload(order=[])


@app.put("/api/settings/sidebar-menu-order", response_model=SidebarMenuOrderSettingsPayload)
def put_sidebar_menu_order_settings(
    payload: SidebarMenuOrderSettingsPayload,
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    order: list[str] = []
    for v in payload.order:
        if not isinstance(v, str):
            continue
        key = v.strip()
        if not key or key in order:
            continue
        order.append(key)
    SIDEBAR_MENU_ORDER_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIDEBAR_MENU_ORDER_SETTINGS_FILE.write_text(
        json.dumps({"order": order}, ensure_ascii=False),
        encoding="utf-8",
    )
    return SidebarMenuOrderSettingsPayload(order=order)


# Лог входящих тел от 1С (POST /api/order/ и алиасов) — для отладки
ORDER_1C_LOG = Path("/home/crm-backend/logs/order_1c_body.log")


@app.post("/api/order/")
@app.post("/api/order/1c-intake/")
async def order_from_1c(request: Request, db: Session = Depends(get_db)):
    """Приём заказов из 1С: парсинг JSON, запись в БД, логирование тела."""
    body = await request.body()
    client = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "").strip().split(",")[0].strip() or client
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    ORDER_1C_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ORDER_1C_LOG, "a", encoding="utf-8") as f:
        f.write(
            f"\n--- {ts} | path={request.url.path} | client={forwarded} | content-type={request.headers.get('content-type', '')} | len={len(body)} ---\n"
        )
        try:
            f.write(body.decode("utf-8"))
        except UnicodeDecodeError:
            f.write(body.hex())
        f.write("\n")

    try:
        raw = body.decode("utf-8")
        payload = json.loads(raw)
    except Exception as e:
        return {"received": False, "error": f"Invalid JSON: {e!s}"}

    if not isinstance(payload, dict):
        return {"received": False, "error": "Body must be a JSON object"}

    try:
        order = create_order_from_1c(db, payload)
        return {"received": True, "order_id": order.id, "order": _order_to_response(order)}
    except Exception as e:
        return {"received": False, "error": str(e)}


@app.get("/api/order/")
async def order_from_1c_get():
    """Проверка доступности эндпоинта для 1С."""
    return {"status": "ok", "message": "POST с телом заказа на этот URL"}


@app.get("/api/order/1c-intake/")
async def order_from_1c_get_alias():
    """Проверка доступности алиаса эндпоинта для 1С."""
    return {"status": "ok", "message": "POST с телом заказа на этот URL"}


@app.get("/api/order/accepted")
def order_accepted_feed(db: Session = Depends(get_db)):
    """Страница JSON для 1С: список заказов, которые 1С ещё не забирала.
    1С опрашивает раз в минуту.

    Формат ответа (упрощённый, без обёртки):
    [
        {"order_number": "48", "warehouse": "Войковская  (Ленинградское шоссе д.8, к3)"},
        {"order_number": "130", "warehouse": "Амундсена  (ул. Амундсена д.14)"},
        {"order_number": "75", "warehouse": "Кузьминки (Волгоградский пр., д.94, к1)"},
        {"order_number": "164", "warehouse": "Варшавская"}
    ]

    То есть для каждого элемента отдельно есть ключ с номером заказа и ключ с названием магазина.
    """
    from models import Order
    orders = (
        db.query(Order)
        .filter(Order.status == "accepted", Order.synced_to_1c_at.is_(None))
        .order_by(Order.created_at.asc())
        .all()
    )
    result_orders = []
    for o in orders:
        num = o.order_number or str(o.id)
        if not num:
            continue
        result_orders.append(
            {
                "order_number": num,
                "warehouse": o.warehouse or (o.warehouse_rel.name if getattr(o, "warehouse_rel", None) else None),
            }
        )
    # Возвращаем сразу массив объектов без обёртки:
    # [{"order_number": "...", "warehouse": "..."}, ...]
    return result_orders


ACK_LOG = Path("/home/crm-backend/logs/order_ack.log")
ACK_BODY_LOG = Path("/home/crm-backend/logs/order_ack_body.log")
_ack_logger = None


def _get_ack_logger():
    global _ack_logger
    if _ack_logger is None:
        ACK_LOG.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("order_ack")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            h = logging.FileHandler(ACK_LOG, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
            logger.addHandler(h)
        _ack_logger = logger
    return _ack_logger


@app.post("/api/order/ack")
@app.post("/api/order/ack/")
@app.post("/api/order/accepted/ask")
@app.post("/api/order/accepted/ask/")
async def order_ack_from_1c(request: Request, db: Session = Depends(get_db)):
    """1С отправляет сюда номера заказов, которые забрала. После этого они не показываются в /api/order/accepted."""
    from datetime import datetime as dt
    from models import Order
    client = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "").strip().split(",")[0].strip() or client
    log = _get_ack_logger()
    # Лог сырого тела — чтобы видеть, что именно присылает 1С
    try:
        body_bytes = await request.body()
        ts = dt.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        ACK_BODY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ACK_BODY_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n--- {ts} | client={forwarded} | path={request.url.path} | content-type={request.headers.get('content-type', '')} | len={len(body_bytes)} ---\n"
            )
            try:
                f.write(body_bytes.decode("utf-8"))
            except UnicodeDecodeError:
                f.write(body_bytes.hex())
            f.write("\n")
    except Exception as e:
        log.warning(f"ack_body_log | client={forwarded} | error={e!s}")
    def _extract_order_numbers_from_raw(raw: str) -> list[str]:
        # Пытаемся вытащить все строковые токены из сырого тела.
        # Это позволяет пережить "невалидный JSON" вида: {"order_numbers":[{"75"},{"164"}]}
        # (1С иногда присылает такое).
        import re

        tokens = re.findall(r"\"([^\"]+)\"", raw)
        tokens = [t.strip() for t in tokens if t and t.strip()]
        tokens = [t for t in tokens if t != "order_numbers"]
        if tokens:
            return tokens

        # Фолбэк: вытащить похожие на номера токены без кавычек.
        # Берём только разумные символы, чтобы не ловить мусор.
        tokens2 = re.findall(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", raw)
        tokens2 = [t for t in tokens2 if t != "order_numbers"]
        return tokens2

    body = None
    try:
        body = await request.json()
    except Exception as e:
        # Не валимся: попробуем распарсить номера из сырого тела
        try:
            raw = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        extracted = _extract_order_numbers_from_raw(raw)
        if extracted:
            log.warning(
                f"ack | client={forwarded} | invalid_json_fallback | extracted={extracted} | error={e!s}"
            )
            body = {"order_numbers": extracted}
        else:
            log.warning(f"ack | client={forwarded} | invalid_json | error={e!s}")
            return {"order_numbers": [], "error": "Invalid JSON"}
    if body is None:
        log.warning(f"ack | client={forwarded} | body_null")
        return {"order_numbers": []}

    def _normalize_items(payload) -> list[dict]:
        """Список элементов вида {"order_number": str, "warehouse": Optional[str]}."""
        items = []

        def push(num, wh):
            num = (str(num) if num is not None else "").strip()
            if not num:
                return
            wh = (str(wh).strip() if wh is not None else None)
            if wh == "":
                wh = None
            items.append({"order_number": num, "warehouse": wh})

        def consume_list(lst):
            for x in lst:
                if isinstance(x, dict):
                    push(
                        x.get("order_number") or x.get("order") or x.get("id"),
                        x.get("warehouse") or x.get("shop") or x.get("store"),
                    )
                else:
                    push(x, None)

        if isinstance(payload, list):
            consume_list(payload)
        elif isinstance(payload, dict):
            # Возможные форматы от 1С:
            # - {"order_numbers": ["48","130"]}
            # - {"order_numbers": [{"order_number":"48","warehouse":"..."}, ...]}
            # - {"orders": [{"order_number":"48","warehouse":"..."}, ...]}
            if isinstance(payload.get("orders"), list):
                consume_list(payload["orders"])
            elif isinstance(payload.get("order_numbers"), list):
                consume_list(payload["order_numbers"])
            else:
                if "order_number" in payload or "warehouse" in payload:
                    push(
                        payload.get("order_number") or payload.get("order") or payload.get("id"),
                        payload.get("warehouse") or payload.get("shop") or payload.get("store"),
                    )
        return items

    items = _normalize_items(body)
    if not items:
        log.info(f"ack | client={forwarded} | empty_items")
        return {"order_numbers": []}
    try:
        from sqlalchemy import or_

        now = dt.utcnow()
        updated_total = 0

        # Обновляем по (номер+склад), если склад передан
        for it in items:
            num = it["order_number"]
            wh = it["warehouse"]
            if not wh:
                continue
            q = db.query(Order).filter(
                Order.status == "accepted",
                Order.synced_to_1c_at.is_(None),
                Order.order_number == num,
                or_(
                    Order.warehouse == wh,
                    Order.warehouse_rel.has(name=wh),
                ),
            )
            updated_total += q.update({Order.synced_to_1c_at: now}, synchronize_session="fetch")

        # Фолбэк: если склад не пришёл — обновляем только по номеру
        nums_only = [it["order_number"] for it in items if not it["warehouse"]]
        if nums_only:
            updated_total += (
                db.query(Order)
                .filter(
                    Order.status == "accepted",
                    Order.synced_to_1c_at.is_(None),
                    Order.order_number.in_(nums_only),
                )
                .update({Order.synced_to_1c_at: now}, synchronize_session="fetch")
            )

        db.commit()
        order_numbers = [it["order_number"] for it in items]
        log.info(f"ack | client={forwarded} | updated={updated_total} | items={items}")
        return {"order_numbers": order_numbers}
    except Exception as e:
        db.rollback()
        order_numbers = [it["order_number"] for it in items]
        log.error(f"ack | client={forwarded} | error={e!s} | items={items}")
        return {"order_numbers": order_numbers, "error": str(e)}


app.include_router(users_router.router)
app.include_router(groups_router.router)
app.include_router(orders_router.router)
app.include_router(references_router.router)
app.include_router(chat_router.router)
app.include_router(portal_tasks_router.router)
app.include_router(supply_tickets_router.router)
app.include_router(training_router.router)
app.include_router(drive_router.router)
app.include_router(normative_acts_router.router)
app.include_router(upload_router.router)
app.include_router(reports_router.router)
app.include_router(central_cash_router.router)
app.include_router(work_schedule_router.router)
app.include_router(offline_export_router.router)

# Раздача загруженных файлов
UPLOAD_DIR = Path("/home/crm-backend/uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
