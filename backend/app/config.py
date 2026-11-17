from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    APP_NAME: str = "SignalPilot Pro"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    API_PREFIX: str = "/api/v1"

    LIVE_TRADING_ENABLED: bool = False

    DATABASE_URL: str = "sqlite+aiosqlite:///./signalpilot.db"

    SECRET_KEY: SecretStr = SecretStr(
        "development-only-change-this-key"
    )

    # Dedicated secret for external automatic scan requests.
    AUTOMATION_TOKEN: SecretStr | None = None

    # Automatic scanner configuration.
    AUTOMATION_ENABLED: bool = True
    AUTOMATION_INTERVAL_MINUTES: int = Field(
        default=30,
        ge=30,
        le=1440,
    )

    DEFAULT_ACCOUNT_BALANCE: float = 1000.0
    DEFAULT_RISK_PERCENT: float = 0.5
    DEFAULT_RISK_REWARD_RATIO: float = 2.0
    DEFAULT_MINIMUM_SIGNAL_SCORE: int = 60

    MAX_RISK_PER_TRADE_PERCENT: float = 1.0
    MAX_DAILY_LOSS_PERCENT: float = 3.0
    MAX_DRAWDOWN_PERCENT: float = 10.0
    MAX_OPEN_POSITIONS: int = 5

    # Keep the request concurrency conservative.
    SCAN_CONCURRENCY: int = 1

    # Minimum delay between provider requests.
    MARKET_DATA_REQUEST_DELAY_SECONDS: float = 8.0

    # Market scanning configuration.
    SCAN_SYMBOLS: list[str] = Field(
        default_factory=lambda: [
            "GBP/JPY",
            "CAD/JPY",
            "EUR/JPY",
            "GBP/USD",
            "AUD/JPY",
        ]
    )

    SCAN_TIMEFRAMES: list[str] = Field(
        default_factory=lambda: [
            "4h",
            "1h",
            "15min",
        ]
    )

    ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:8081"
        ]
    )

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
