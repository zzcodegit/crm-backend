from sqlalchemy import text

from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS schedule_color VARCHAR(32);
                """
            )
        )
    print("OK: users.schedule_color")


if __name__ == "__main__":
    main()

