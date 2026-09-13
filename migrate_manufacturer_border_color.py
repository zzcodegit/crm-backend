from sqlalchemy import text

from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE manufacturers
                ADD COLUMN IF NOT EXISTS border_color VARCHAR(64);
                """
            )
        )
    print("OK: manufacturers.border_color")


if __name__ == "__main__":
    main()

