"""Таблица просмотров статей обучения (training_article_views)."""
from sqlalchemy import text

from database import engine

SQL = [
    """
    CREATE TABLE IF NOT EXISTS training_article_views (
      id SERIAL PRIMARY KEY,
      article_id INTEGER NOT NULL REFERENCES training_articles(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      view_count INTEGER NOT NULL DEFAULT 1,
      first_viewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      last_viewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'uq_training_article_view_user'
      ) THEN
        CREATE UNIQUE INDEX uq_training_article_view_user
          ON training_article_views(article_id, user_id);
      END IF;
    END
    $$;
    """,
]


def main() -> None:
    with engine.begin() as conn:
        for stmt in SQL:
            conn.execute(text(stmt))
    print("OK: training_article_views")


if __name__ == "__main__":
    main()
