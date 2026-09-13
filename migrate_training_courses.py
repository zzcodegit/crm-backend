"""
Таблицы курсов обучения (training_courses, training_user_course_progress).
Идемпотентно: CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.
Запуск из каталога backend: python migrate_training_courses.py
"""
from sqlalchemy import text

from database import engine

DDL = [
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
    """,
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
    """,
    "CREATE INDEX IF NOT EXISTS ix_training_progress_user ON training_user_course_progress(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_training_progress_course ON training_user_course_progress(course_id)",
]


def main() -> None:
    with engine.begin() as conn:
        for i, sql in enumerate(DDL):
            conn.execute(text(sql))
            print(f"OK: step {i + 1}/{len(DDL)}")
    print("Done: training_courses, training_user_course_progress")


if __name__ == "__main__":
    main()
