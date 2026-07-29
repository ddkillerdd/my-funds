"""Application settings loaded from .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    DB_HOST: str = "***REMOVED***"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "***REMOVED***"
    DB_NAME: str = "fund_advisor"

    # Application
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
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TO: str = ""

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
