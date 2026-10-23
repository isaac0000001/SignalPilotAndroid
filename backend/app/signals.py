from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Literal, Sequence
import math


Signal = Literal["BUY", "SELL", "NO TRADE"]


@dataclass(frozen=True)
class Candle:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class SignalResult:
    symbol: str
    signal: Signal
    score: int
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    quantity: Decimal
    risk_amount: Decimal
    reasons: tuple[str, ...]


def _validate_candles(candles: Sequence[Candle]) -> None:
    if len(candles) < 60:
        raise ValueError("At least 60 candles are required.")

    for candle in candles:
        values = (candle.open, candle.high, candle.low, candle.close)

        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("Candle prices must be finite and positive.")

        if candle.high < max(candle.open, candle.close, candle.low):
            raise ValueError("Candle high is inconsistent.")

        if candle.low > min(candle.open, candle.close, candle.high):
            raise ValueError("Candle low is inconsistent.")


def _ema(values: Sequence[float], period: int) -> float:
    if len(values) < period:
        raise ValueError("Insufficient data for EMA.")

    alpha = 2.0 / (period + 1)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result

    return result


def _rsi(values: Sequence[float], period: int = 14) -> float:
    if len(values) <= period:
        raise ValueError("Insufficient data for RSI.")

    changes = [
        values[index] - values[index - 1]
        for index in range(1, len(values))
    ]

    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = (
            average_gain * (period - 1) + gain
        ) / period
        average_loss = (
            average_loss * (period - 1) + loss
        ) / period

    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0

    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _atr(candles: Sequence[Candle], period: int = 14) -> float:
    true_ranges = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous_close = candles[index - 1].close

        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous_close),
                abs(current.low - previous_close),
            )
        )

    if len(true_ranges) < period:
        raise ValueError("Insufficient data for ATR.")

    result = sum(true_ranges[:period]) / period

    for value in true_ranges[period:]:
        result = ((result * (period - 1)) + value) / period

    return result


def analyze_market(
    *,
    symbol: str,
    candles: Sequence[Candle],
    account_balance: Decimal,
    risk_percent: Decimal = Decimal("0.5"),
    reward_risk_ratio: Decimal = Decimal("2"),
    value_per_price_unit: Decimal,
    quantity_step: Decimal = Decimal("0.01"),
    minimum_quantity: Decimal = Decimal("0.01"),
    maximum_quantity: Decimal = Decimal("100"),
) -> SignalResult:
    """
    Analyze chronological OHLC candles.

    Candle data must be ordered oldest to newest.
    value_per_price_unit must represent the monetary value of a
    1.0 price move for one unit of quantity in the account currency.

    This is a research signal, not a broker execution instruction.
    """

    _validate_candles(candles)

    if not symbol.strip():
        raise ValueError("Symbol is required.")

    if not account_balance.is_finite() or account_balance <= 0:
        raise ValueError("Account balance must be positive.")

    if not risk_percent.is_finite() or not (
        Decimal("0") < risk_percent <= Decimal("1")
    ):
        raise ValueError("Risk percentage must be greater than 0 and at most 1%.")

    if not reward_risk_ratio.is_finite() or reward_risk_ratio <= 0:
        raise ValueError("Reward/risk ratio must be positive.")

    if not value_per_price_unit.is_finite() or value_per_price_unit <= 0:
        raise ValueError("Price-unit value must be positive.")

    if not quantity_step.is_finite() or quantity_step <= 0:
        raise ValueError("Quantity step must be positive.")

    if not minimum_quantity.is_finite() or minimum_quantity <= 0:
        raise ValueError("Minimum quantity must be positive.")

    if not maximum_quantity.is_finite() or maximum_quantity < minimum_quantity:
        raise ValueError("Maximum quantity must be at least the minimum quantity.")

    closes = [candle.close for candle in candles]
    latest = candles[-1]
    reasons: list[str] = []

    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    rsi = _rsi(closes)
    atr = _atr(candles)

    if atr <= 0 or not math.isfinite(atr):
        raise ValueError("Market volatility is not suitable for calculation.")

    macd_line = _ema(closes, 12) - _ema(closes, 26)

    # A conservative directional score. This is not a probability.
    buy_score = 0
    sell_score = 0

    if latest.close > ema20 > ema50:
        buy_score += 2
        reasons.append("Bullish EMA trend.")
    elif latest.close < ema20 < ema50:
        sell_score += 2
        reasons.append("Bearish EMA trend.")

    if rsi >= 50 and rsi < 70:
        buy_score += 1
        reasons.append("Positive RSI momentum.")
    elif rsi <= 50 and rsi > 30:
        sell_score += 1
        reasons.append("Negative RSI momentum.")

    if macd_line > 0:
        buy_score += 1
        reasons.append("Positive MACD line.")
    elif macd_line < 0:
        sell_score += 1
        reasons.append("Negative MACD line.")

    if rsi >= 70:
        reasons.append("RSI is overbought; avoid chasing.")
    elif rsi <= 30:
        reasons.append("RSI is oversold; reversal risk is elevated.")

    if buy_score >= 3 and buy_score > sell_score:
        direction: Signal = "BUY"
    elif sell_score >= 3 and sell_score > buy_score:
        direction = "SELL"
    else:
        direction = "NO TRADE"
        reasons.append("Directional evidence is insufficient.")

    score = max(buy_score, sell_score)

    if direction == "NO TRADE":
        return SignalResult(
            symbol=symbol.upper(),
            signal=direction,
            score=score,
            entry=None,
            stop_loss=None,
            take_profit=None,
            quantity=Decimal("0"),
            risk_amount=Decimal("0"),
            reasons=tuple(reasons),
        )

    entry = latest.close
    stop_distance = atr * 1.5

    if direction == "BUY":
        stop_loss = entry - stop_distance
        take_profit = entry + (
            stop_distance * float(reward_risk_ratio)
        )
    else:
        stop_loss = entry + stop_distance
        take_profit = entry - (
            stop_distance * float(reward_risk_ratio)
        )

    if stop_loss <= 0 or take_profit <= 0:
        raise ValueError("Calculated price levels are invalid.")

    risk_amount = (
        account_balance * risk_percent / Decimal("100")
    )

    distance_decimal = Decimal(str(abs(entry - stop_loss)))
    loss_per_unit = distance_decimal * value_per_price_unit

    if loss_per_unit <= 0:
        raise ValueError("Invalid estimated loss per unit.")

    raw_quantity = risk_amount / loss_per_unit

    quantity = (
        (raw_quantity / quantity_step).to_integral_value(
            rounding=ROUND_DOWN
        )
        * quantity_step
    )

    # Never round up to the broker minimum if that would exceed risk.
    if quantity < minimum_quantity:
        reasons.append("NO TRADE: minimum quantity exceeds calculated risk.")
        return SignalResult(
            symbol=symbol.upper(),
            signal="NO TRADE",
            score=score,
            entry=None,
            stop_loss=None,
            take_profit=None,
            quantity=Decimal("0"),
            risk_amount=Decimal("0"),
            reasons=tuple(reasons),
        )

    quantity = min(quantity, maximum_quantity)
    estimated_risk = quantity * loss_per_unit

    # Maximum quantity is applied before the risk check.
    if estimated_risk > risk_amount:
        reasons.append("NO TRADE: calculated risk exceeds the risk budget.")
        return SignalResult(
            symbol=symbol.upper(),
            signal="NO TRADE",
            score=score,
            entry=None,
            stop_loss=None,
            take_profit=None,
            quantity=Decimal("0"),
            risk_amount=Decimal("0"),
            reasons=tuple(reasons),
        )

    return SignalResult(
        symbol=symbol.upper(),
        signal=direction,
        score=score,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        quantity=quantity,
        risk_amount=estimated_risk,
        reasons=tuple(reasons),
    )
