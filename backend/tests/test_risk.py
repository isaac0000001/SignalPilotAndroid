from decimal import Decimal

import pytest

from app.risk import RiskValidationError, calculate_position_size


def test_calculates_position_size_correctly():
    result = calculate_position_size(
        account_balance=Decimal("1000"),
        risk_percent=Decimal("1"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0900"),
        value_per_price_unit=Decimal("100000"),
        quantity_step=Decimal("0.01"),
        minimum_quantity=Decimal("0.01"),
        maximum_quantity=Decimal("100"),
    )

    assert result.risk_amount == Decimal("10")
    assert result.stop_distance == Decimal("0.0100")
    assert result.suggested_quantity == Decimal("0.01")
    assert result.estimated_total_risk <= result.risk_amount


def test_rejects_zero_account_balance():
    with pytest.raises(RiskValidationError):
        calculate_position_size(
            account_balance=Decimal("0"),
            risk_percent=Decimal("1"),
            entry_price=Decimal("1.1000"),
            stop_loss=Decimal("1.0900"),
            value_per_price_unit=Decimal("100000"),
            quantity_step=Decimal("0.01"),
            minimum_quantity=Decimal("0.01"),
            maximum_quantity=Decimal("100"),
        )


def test_rejects_stop_loss_equal_to_entry():
    with pytest.raises(RiskValidationError):
        calculate_position_size(
            account_balance=Decimal("1000"),
            risk_percent=Decimal("1"),
            entry_price=Decimal("1.1000"),
            stop_loss=Decimal("1.1000"),
            value_per_price_unit=Decimal("100000"),
            quantity_step=Decimal("0.01"),
            minimum_quantity=Decimal("0.01"),
            maximum_quantity=Decimal("100"),
        )
