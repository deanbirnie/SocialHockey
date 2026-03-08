from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    RESEND_API_KEY: str
    BASE_URL: str = "http://localhost:8000"
    SESSION_EXPIRY_DAYS: int = 30

    model_config = {"env_file": ".env"}


settings = Settings()
