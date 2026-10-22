from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class StrictSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class AccountResponse(StrictSchema):
    id: UUID
    name: str
    currency: str
    initial_balance: Decimal
    balance: Decimal
    equity: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RiskCalculationRequest(StrictSchema):
    account_balance: Decimal = Field(gt=0, le=Decimal("1000000000000"))
    risk_percent: Decimal = Field(gt=0, le=Decimal("1"))
    entry_price: Decimal = Field(gt=0)
    stop_loss: Decimal = Field(gt=0)
    value_per_price_unit: Decimal = Field(gt=0)
    quantity_step: Decimal = Field(default=Decimal("0.01"), gt=0)
    minimum_quantity: Decimal = Field(default=Decimal("0.01"), gt=0)
    maximum_quantity: Decimal = Field(default=Decimal("1000000"), gt=0)

    @model_validator(mode="after")
    def validate_prices_and_quantity(self):
        if self.entry_price == self.stop_loss:
            raise ValueError("Entry price and stop-loss must differ.")

        if self.minimum_quantity > self.maximum_quantity:
            raise ValueError("Minimum quantity exceeds maximum quantity.")

        return self


class RiskCalculationResponse(StrictSchema):
    risk_amount: Decimal
    stop_distance: Decimal
    estimated_loss_per_unit: Decimal
    suggested_quantity: Decimal
    estimated_total_risk: Decimal
    actual_risk_percent: Decimal


class OrderCreateRequest(StrictSchema):
    client_order_id: str = Field(min_length=8, max_length=100)
    symbol: str = Field(min_length=3, max_length=32)
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "STOP"]
    quantity: Decimal = Field(gt=0, le=Decimal("1000000"))
    stop_loss: Decimal | None = Field(default=None, gt=0)
    take_profit: Decimal | None = Field(default=None, gt=0)
    requested_price: Decimal | None = Field(default=None, gt=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.upper()

        if not all(
            character.isalnum() or character in "_-/."
            for character in normalized
        ):
            raise ValueError("Symbol contains unsupported characters.")

        return normalized

    @model_validator(mode="after")
    def validate_order(self):
        if self.order_type in {"LIMIT", "STOP"} and self.requested_price is None:
            raise ValueError(
                "LIMIT and STOP orders require a requested price."
            )

        if (
            self.stop_loss is not None
            and self.take_profit is not None
            and self.stop_loss == self.take_profit
        ):
            raise ValueError(
                "Stop-loss and take-profit cannot be identical."
            )

        return self


class OrderResponse(StrictSchema):
    id: UUID
    account_id: UUID
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    requested_price: Decimal | None
    filled_price: Decimal | None
    status: str
    execution_mode: str
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class HealthResponse(StrictSchema):
    status: Literal["ok", "degraded"]
    application: str
    version: str
    database: Literal["connected", "disconnected"]
