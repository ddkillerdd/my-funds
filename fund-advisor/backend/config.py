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

    # 决策引擎 (RFC-014): L2 波动率目标 + L3 风控阈值
    # 通过 .env 覆盖, 不改代码即可调参
    TARGET_VOL: float = 0.15          # 目标年化波动率(十进制), 进取0.20/保守0.10
    DD_HARD_STOP_PCT: float = 25.0    # 回撤>25% 清仓 (R1)
    DD_REDUCE_LO_PCT: float = 15.0    # 回撤15-25% 减仓 (R2)
    VOL_HIGH_CAP_PCT: float = 60.0    # 年化vol>60% 压仓 (R3)
    CONC_CAP: float = 0.50            # 单基目标权重上限 (R4)
    BEAR_CAP: float = 0.30            # 熊市防御上限 (R5)
    FRICTION_BAND_PP: float = 5.0     # 换手触发带(百分点, R6)

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
