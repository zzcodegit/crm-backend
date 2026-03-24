from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/crm"
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours
    firebase_credentials_file: str = "/home/crm-backend/firebase-service-account.json"
    firebase_credentials_json: str | None = None
    firebase_project_id: str | None = None

    class Config:
        env_file = ".env"


settings = Settings()
