"""Библиотека обоев чата и поля пользователя."""
from sqlalchemy import text

from database import engine

WALLPAPERS = [
    ("Синий градиент", "/chat-wallpapers/gradient-blue.svg", 10),
    ("Фиолетовый", "/chat-wallpapers/gradient-purple.svg", 20),
    ("Закат", "/chat-wallpapers/gradient-sunset.svg", 30),
    ("Мятный", "/chat-wallpapers/gradient-mint.svg", 40),
    ("Горошек", "/chat-wallpapers/pattern-dots.svg", 50),
    ("Волны", "/chat-wallpapers/pattern-waves.svg", 60),
    ("Геометрия", "/chat-wallpapers/pattern-geometry.svg", 70),
    ("Пузыри", "/chat-wallpapers/pattern-bubbles.svg", 80),
    ("Облака", "/chat-wallpapers/soft-clouds.svg", 90),
    ("Песок", "/chat-wallpapers/warm-sand.svg", 100),
    ("Ночное небо", "/chat-wallpapers/night-sky.svg", 110),
    ("Лёгкий узор", "/chat-wallpapers/light-pattern.svg", 120),
]


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_wallpapers (
                  id SERIAL PRIMARY KEY,
                  title VARCHAR(128) NOT NULL,
                  url VARCHAR(1024) NOT NULL,
                  thumb_url VARCHAR(1024),
                  sort_order INTEGER NOT NULL DEFAULT 0,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_wallpaper_id INTEGER REFERENCES chat_wallpapers(id) ON DELETE SET NULL"
            )
        )
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_wallpaper_url VARCHAR(1024)"))
        count = conn.execute(text("SELECT COUNT(*) FROM chat_wallpapers")).scalar() or 0
        if int(count) == 0:
            for title, url, sort_order in WALLPAPERS:
                conn.execute(
                    text(
                        """
                        INSERT INTO chat_wallpapers (title, url, thumb_url, sort_order, is_active)
                        VALUES (:title, :url, :url, :sort_order, TRUE)
                        """
                    ),
                    {"title": title, "url": url, "sort_order": sort_order},
                )
    print("OK: chat_wallpapers + users.chat_wallpaper_*")


if __name__ == "__main__":
    main()
