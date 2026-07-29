"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DB_HOST: str = "***REMOVED***"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "***REMOVED***"
    DB_NAME: str = "fund_advisor"

    # App
    APP_ENV: str = "development"
    APP_PORT: int = 8200

    # NAV Fetch
    NAV_FETCH_CONCURRENCY: int = 5
    NAV_FETCH_INTERVAL: float = 0.5

    # NewAPI (LLM Gateway)
    NEWAPI_BASE_URL: str = ""
    NEWAPI_API_KEY: str = ""

    # SMTP (Email)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        return self.DATABASE_URL

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
