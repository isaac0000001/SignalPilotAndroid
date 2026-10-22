from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from app.config import get_settings


settings = get_settings()

ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")


class RiskValidationError(ValueError):
    """Raised when a risk calculation fails validation."""


@dataclass(frozen=True)
class RiskCalculation:
    risk_amount: Decimal
    stop_distance: Decimal
    estimated_loss_per_unit: Decimal
    suggested_quantity: Decimal
    estimated_total_risk: Decimal
    actual_risk_percent: Decimal


def calculate_position_size(
    account_balance: Decimal,
    risk_percent: Decimal,
    entry_price: Decimal,
    stop_loss: Decimal,
    value_per_price_unit: Decimal,
    quantity_step: Decimal = Decimal("0.01"),
    minimum_quantity: Decimal = Decimal("0.01"),
    maximum_quantity: Decimal = Decimal("1000000"),
) -> RiskCalculation:
    """
    Calculate a theoretical position size.

    value_per_price_unit must represent the account-currency loss
    for one quantity unit per one full price unit of movement.

    Instrument contract specifications and conversion rates must be
    verified before using this calculation for live trading.
    """

    values = {
        "account_balance": account_balance,
        "risk_percent": risk_percent,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "value_per_price_unit": value_per_price_unit,
        "quantity_step": quantity_step,
        "minimum_quantity": minimum_quantity,
        "maximum_quantity": maximum_quantity,
    }

    if any(not value.is_finite() for value in values.values()):
        raise RiskValidationError("All inputs must be finite numbers.")

    if account_balance <= ZERO:
        raise RiskValidationError("Account balance must be positive.")

    if risk_percent <= ZERO or risk_percent > Decimal("1"):
        raise RiskValidationError(
            "Risk percentage must be greater than 0 and at most 1%."
        )

    configured_max = Decimal(
        str(settings.MAX_RISK_PER_TRADE_PERCENT)
    )

    if risk_percent > configured_max:
        raise RiskValidationError(
            f"Risk exceeds the configured limit of {configured_max}%."
        )

    if entry_price <= ZERO or stop_loss <= ZERO:
        raise RiskValidationError("Prices must be positive.")

    if entry_price == stop_loss:
        raise RiskValidationError(
            "Entry and stop-loss prices must differ."
        )

    if value_per_price_unit <= ZERO:
        raise RiskValidationError(
            "Value per price unit must be positive."
        )

    if quantity_step <= ZERO:
        raise RiskValidationError(
            "Quantity step must be positive."
        )

    if minimum_quantity <= ZERO or maximum_quantity < minimum_quantity:
        raise RiskValidationError("Quantity limits are invalid.")

    stop_distance = abs(entry_price - stop_loss)

    estimated_loss_per_unit = (
        stop_distance * value_per_price_unit
    )

    risk_amount = (
        account_balance * risk_percent / ONE_HUNDRED
    )

    raw_quantity = risk_amount / estimated_loss_per_unit

    # Round down to a valid quantity increment.
    increments = (
        raw_quantity / quantity_step
    ).to_integral_value(rounding=ROUND_FLOOR)

    suggested_quantity = increments * quantity_step

    # Never increase a position to meet the minimum if that would
    # exceed the requested risk budget.
    if suggested_quantity < minimum_quantity:
        suggested_quantity = ZERO

    suggested_quantity = min(
        suggested_quantity,
        maximum_quantity,
    )

    estimated_total_risk = (
        suggested_quantity * estimated_loss_per_unit
    )

    actual_risk_percent = (
        estimated_total_risk / account_balance * ONE_HUNDRED
    )

    if estimated_total_risk > risk_amount:
        raise RiskValidationError(
            "Calculated position exceeds the risk budget."
        )

    return RiskCalculation(
        risk_amount=risk_amount,
        stop_distance=stop_distance,
        estimated_loss_per_unit=estimated_loss_per_unit,
        suggested_quantity=suggested_quantity,
        estimated_total_risk=estimated_total_risk,
        actual_risk_percent=actual_risk_percent,
    )
