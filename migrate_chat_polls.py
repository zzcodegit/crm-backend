"""Таблицы опросов в чате."""
from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_polls (
                  id SERIAL PRIMARY KEY,
                  message_id INTEGER NOT NULL UNIQUE REFERENCES chat_messages(id) ON DELETE CASCADE,
                  question VARCHAR(512) NOT NULL,
                  allows_multiple BOOLEAN NOT NULL DEFAULT FALSE,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_poll_options (
                  id SERIAL PRIMARY KEY,
                  poll_id INTEGER NOT NULL REFERENCES chat_polls(id) ON DELETE CASCADE,
                  text VARCHAR(256) NOT NULL,
                  position INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_poll_votes (
                  id SERIAL PRIMARY KEY,
                  poll_id INTEGER NOT NULL REFERENCES chat_polls(id) ON DELETE CASCADE,
                  option_id INTEGER NOT NULL REFERENCES chat_poll_options(id) ON DELETE CASCADE,
                  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  voted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_poll_options_poll_id ON chat_poll_options(poll_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_poll_votes_poll_id ON chat_poll_votes(poll_id)"))
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE indexname = 'idx_chat_poll_vote_user_option'
                  ) THEN
                    CREATE UNIQUE INDEX idx_chat_poll_vote_user_option
                      ON chat_poll_votes(poll_id, user_id, option_id);
                  END IF;
                END
                $$;
                """
            )
        )
    print("OK: chat_polls, chat_poll_options, chat_poll_votes")


if __name__ == "__main__":
    main()
