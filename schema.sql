-- Справочная схема (таблицы создаются автоматически через SQLAlchemy create_all).
-- Миграции не используются; при первом запуске создаются users, groups, user_groups.

-- users (уже была)
-- id, username, hashed_password, is_active, created_at

-- groups
-- id SERIAL PRIMARY KEY, name VARCHAR(128) UNIQUE NOT NULL, created_at TIMESTAMPTZ

-- user_groups (связь многие-ко-многим)
-- user_id INT REFERENCES users(id) ON DELETE CASCADE,
-- group_id INT REFERENCES groups(id) ON DELETE CASCADE,
-- PRIMARY KEY (user_id, group_id)
