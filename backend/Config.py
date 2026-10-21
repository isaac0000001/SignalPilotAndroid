from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "SignalPilot Pro"
    APP_VERSION: str = "1.0.0"

    ENVIRONMENT: Literal["development", "testing", "production"] = (
        "development"
    )

    API_PREFIX: str = "/api/v1"

    # Trading safety
    LIVE_TRADING_ENABLED: bool = False

    DEFAULT_ACCOUNT_BALANCE: float = Field(default=1000.0, gt=0)
    MAX_RISK_PER_TRADE_PERCENT: float = Field(default=1.0, gt=0, le=1.0)
    MAX_DAILY_LOSS_PERCENT: float = Field(default=3.0, gt=0, le=100)
    MAX_DRAWDOWN_PERCENT: float = Field(default=10.0, gt=0, le=100)
    MAX_OPEN_POSITIONS: int = Field(default=5, ge=1, le=100)

    # Database
    DATABASE_URL: SecretStr = SecretStr(
        "postgresql+asyncpg://signalpilot:development-only@localhost:5432/signalpilot"
    )

    # Must be supplied securely outside source control.
    SECRET_KEY: SecretStr = SecretStr("")

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=15, ge=1, le=60
    )

    # Set this to the actual mobile/API origins when applicable.
    ALLOWED_ORIGINS: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.ENVIRONMENT == "production":
            secret = self.SECRET_KEY.get_secret_value()

            if len(secret) < 32:
                raise ValueError(
                    "Production SECRET_KEY must contain at least 32 characters."
                )

            database_url = self.DATABASE_URL.get_secret_value()

            if "development-only" in database_url:
                raise ValueError(
                    "Configure a real production DATABASE_URL."
                )

            if self.LIVE_TRADING_ENABLED:
                raise ValueError(
                    "Live trading cannot be enabled until execution "
                    "safeguards and provider integrations are independently "
                    "validated."
                )

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
