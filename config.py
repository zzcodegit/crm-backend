from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/crm"
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 365  # 1 year
    firebase_credentials_file: str = "/home/crm-backend/firebase-service-account.json"
    firebase_credentials_json: str | None = None
    firebase_project_id: str | None = None
    webpush_vapid_public_key: str | None = None
    webpush_vapid_private_key: str | None = None
    webpush_vapid_subject: str = "mailto:admin@mosoptika-study.ru"

    # Either provide a ready Bearer token (rare)...
    gigachat_bearer_token: str | None = None
    # ...or provide auth key for OAuth token exchange (preferred).
    gigachat_auth_key: str | None = None
    gigachat_oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_api_url: str = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    gigachat_model: str = "GigaChat"
    gigachat_verify_ssl: bool = True
    gigachat_ca_bundle: str | None = None

    db_pool_size: int = 15
    db_pool_max_overflow: int = 25
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    class Config:
        env_file = ".env"


settings = Settings()
