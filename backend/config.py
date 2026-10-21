from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "SignalPilot Pro"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    # Keep live trading disabled during development.
    LIVE_TRADING_ENABLED: bool = False

    # API security
    API_PREFIX: str = "/api/v1"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:8081"]
    )

    # Database: use an environment variable for production.
    DATABASE_URL: str = "sqlite:///./signalpilot.db"

    # Authentication: MUST be set securely before deployment.
    SECRET_KEY: str = "development-only-change-this-key"

    # Trading risk limits
    DEFAULT_ACCOUNT_BALANCE: float = 1000.0
    MAX_RISK_PER_TRADE_PERCENT: float = 1.0
    MAX_DAILY_LOSS_PERCENT: float = 3.0
    MAX_DRAWDOWN_PERCENT: float = 10.0
    MAX_OPEN_POSITIONS: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
