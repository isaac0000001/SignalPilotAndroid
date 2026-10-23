from decimal import Decimal

import pytest

from app.signals import Candle, analyze_market


def make_candles(count=100, rising=True):
    candles = []

    for i in range(count):
        if rising:
            close = 1.1000 + i * 0.0005
        else:
            close = 1.1500 - i * 0.0005

        candles.append(
            Candle(
                open=close - 0.0001,
                high=close + 0.0003,
                low=close - 0.0003,
                close=close,
            )
        )

    return candles


def test_rejects_insufficient_candles():
    with pytest.raises(ValueError):
        analyze_market(
            symbol="EURUSD",
            candles=make_candles(30),
            account_balance=Decimal("1000"),
            value_per_price_unit=Decimal("100000"),
        )


def test_rejects_invalid_account_balance():
    with pytest.raises(ValueError):
        analyze_market(
            symbol="EURUSD",
            candles=make_candles(),
            account_balance=Decimal("0"),
            value_per_price_unit=Decimal("100000"),
        )


def test_risk_percentage_cannot_exceed_one_percent():
    with pytest.raises(ValueError):
        analyze_market(
            symbol="EURUSD",
            candles=make_candles(),
            account_balance=Decimal("1000"),
            risk_percent=Decimal("2"),
            value_per_price_unit=Decimal("100000"),
        )


def test_generated_trade_has_valid_risk_levels():
    result = analyze_market(
        symbol="EURUSD",
        candles=make_candles(),
        account_balance=Decimal("1000"),
        risk_percent=Decimal("0.5"),
        value_per_price_unit=Decimal("100000"),
    )

    if result.signal != "NO TRADE":
        assert result.entry is not None
        assert result.stop_loss is not None
        assert result.take_profit is not None
        assert result.quantity > 0
        assert result.risk_amount <= Decimal("5")
