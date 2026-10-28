from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Sequence
import math


Mode = Literal["day_trading", "scalping", "smart_adaptive"]


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float


@dataclass
class SignalResult:
    symbol: str
    mode: str
    signal: str
    score: int
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    position_size: float
    risk_amount: float
    market_regime: str
    timeframe_alignment: dict[str, str]
    reasons: list[str]


def _validate_candles(candles: Sequence[Candle]) -> None:
    if len(candles) < 60:
        raise ValueError("At least 60 candles are required.")

    for candle in candles:
        values = [
            candle.open,
            candle.high,
            candle.low,
            candle.close,
        ]

        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Candles must contain finite numeric values.")

        if candle.high < candle.low:
            raise ValueError("Candle high cannot be below its low.")

        if candle.high < max(candle.open, candle.close):
            raise ValueError("Candle high is inconsistent with OHLC values.")

        if candle.low > min(candle.open, candle.close):
            raise ValueError("Candle low is inconsistent with OHLC values.")

        if candle.low <= 0:
            raise ValueError("Candle prices must be positive.")


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("EMA period must be positive.")

    if len(values) < period:
        return []

    result = [float("nan")] * (period - 1)
    initial = sum(values[:period]) / period
    result.append(initial)

    multiplier = 2.0 / (period + 1)
    previous = initial

    for value in values[period:]:
        previous = (value - previous) * multiplier + previous
        result.append(previous)

    return result


def _rsi(values: Sequence[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for index in range(period, len(gains)):
        average_gain = (
            average_gain * (period - 1) + gains[index]
        ) / period

        average_loss = (
            average_loss * (period - 1) + losses[index]
        ) / period

    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0

    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _atr(candles: Sequence[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        raise ValueError("Not enough candles to calculate ATR.")

    true_ranges = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]

        true_range = max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )

        true_ranges.append(true_range)

    value = sum(true_ranges[:period]) / period

    for current_range in true_ranges[period:]:
        value = (
            value * (period - 1) + current_range
        ) / period

    return value


def _indicators(candles: Sequence[Candle]) -> dict[str, float]:
    closes = [c.close for c in candles]

    ema20_series = _ema_series(closes, 20)
    ema50_series = _ema_series(closes, 50)
    ema12_series = _ema_series(closes, 12)
    ema26_series = _ema_series(closes, 26)

    macd_values = [
        fast - slow
        for fast, slow in zip(ema12_series, ema26_series)
        if math.isfinite(fast) and math.isfinite(slow)
    ]

    macd_signal_series = _ema_series(macd_values, 9)

    if not macd_values or not macd_signal_series:
        raise ValueError("Not enough data to calculate MACD.")

    return {
        "close": closes[-1],
        "ema20": ema20_series[-1],
        "ema50": ema50_series[-1],
        "rsi": _rsi(closes, 14),
        "atr": _atr(candles, 14),
        "macd": macd_values[-1],
        "macd_signal": macd_signal_series[-1],
    }


def _direction(indicators: dict[str, float]) -> str:
    if (
        indicators["ema20"] > indicators["ema50"]
        and indicators["close"] > indicators["ema20"]
        and indicators["macd"] > indicators["macd_signal"]
    ):
        return "BUY"

    if (
        indicators["ema20"] < indicators["ema50"]
        and indicators["close"] < indicators["ema20"]
        and indicators["macd"] < indicators["macd_signal"]
    ):
        return "SELL"

    return "NO_TRADE"


def _market_regime(indicators: dict[str, float]) -> str:
    close = indicators["close"]
    atr = indicators["atr"]

    if close <= 0 or atr <= 0:
        return "UNSUITABLE"

    volatility = atr / close

    if volatility > 0.03:
        return "HIGH_VOLATILITY"

    if (
        abs(indicators["ema20"] - indicators["ema50"])
        / close
        < 0.0005
    ):
        return "RANGING"

    return "TRENDING"


def _score(
    indicators: dict[str, float],
    direction: str,
) -> int:
    if direction == "NO_TRADE":
        return 0

    score = 50

    if direction == "BUY":
        if indicators["ema20"] > indicators["ema50"]:
            score += 10

        if indicators["macd"] > indicators["macd_signal"]:
            score += 10

        if 50 <= indicators["rsi"] <= 68:
            score += 10
        elif indicators["rsi"] > 75:
            score -= 15

    else:
        if indicators["ema20"] < indicators["ema50"]:
            score += 10

        if indicators["macd"] < indicators["macd_signal"]:
            score += 10

        if 32 <= indicators["rsi"] <= 50:
            score += 10
        elif indicators["rsi"] < 25:
            score -= 15

    if _market_regime(indicators) == "HIGH_VOLATILITY":
        score -= 15

    return max(0, min(100, score))


def _build_result(
    symbol: str,
    mode: str,
    candles: Sequence[Candle],
    indicators: dict[str, float],
    direction: str,
    score: int,
    account_balance: float,
    risk_percent: float,
    value_per_price_unit: float,
    risk_reward_ratio: float,
    timeframe_alignment: dict[str, str],
    reasons: list[str],
    minimum_score: int = 60,
) -> SignalResult:
    entry = indicators["close"]
    atr = indicators["atr"]

    if direction == "NO_TRADE":
        reasons.append("Indicators do not agree on direction.")

    if score < minimum_score:
        reasons.append(
            f"Signal score is below the minimum of {minimum_score}."
        )
        direction = "NO_TRADE"

    if _market_regime(indicators) == "HIGH_VOLATILITY":
        reasons.append("Volatility is elevated; avoid entering blindly.")
        direction = "NO_TRADE"

    if account_balance <= 0:
        raise ValueError("Account balance must be positive.")

    if not 0 < risk_percent <= 1:
        raise ValueError("Risk percentage must be above 0 and at most 1.")

    if value_per_price_unit <= 0:
        raise ValueError("Value per price unit must be positive.")

    if risk_reward_ratio < 1:
        raise ValueError("Risk-reward ratio must be at least 1:1.")

    risk_amount = account_balance * risk_percent / 100.0

    if direction == "BUY":
        stop_loss = entry - 1.5 * atr
        take_profit = entry + 1.5 * atr * risk_reward_ratio
    elif direction == "SELL":
        stop_loss = entry + 1.5 * atr
        take_profit = entry - 1.5 * atr * risk_reward_ratio
    else:
        stop_loss = entry
        take_profit = entry
        risk_amount = 0.0

    stop_distance = abs(entry - stop_loss)

    position_size = 0.0

    if direction != "NO_TRADE" and stop_distance > 0:
        position_size = risk_amount / (
            stop_distance * value_per_price_unit
        )

        estimated_risk = (
            position_size * stop_distance * value_per_price_unit
        )

        if estimated_risk > risk_amount + 1e-8:
            direction = "NO_TRADE"
            position_size = 0.0
            risk_amount = 0.0
            stop_loss = entry
            take_profit = entry
            reasons.append("Position sizing exceeds the risk budget.")

    reasons.append(
        "The score is a rule-based indicator score, not a win probability."
    )
    reasons.append(
        "Position size is an estimate; verify broker contract specifications, "
        "pip/tick value, account currency conversion, spread and commission."
    )

    return SignalResult(
        symbol=symbol.upper(),
        mode=mode,
        signal=direction,
        score=score,
        entry_price=round(entry, 8),
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8),
        risk_reward_ratio=risk_reward_ratio,
        position_size=round(position_size, 4),
        risk_amount=round(risk_amount, 2),
        market_regime=_market_regime(indicators),
        timeframe_alignment=timeframe_alignment,
        reasons=reasons,
    )


def analyze_market(
    candles: Sequence[Candle],
    account_balance: float = 1000.0,
    risk_percent: float = 0.5,
    value_per_price_unit: float = 1.0,
    risk_reward_ratio: float = 2.0,
    symbol: str = "UNKNOWN",
) -> SignalResult:
    """Analyze a single timeframe. Not a guarantee of profitability."""

    _validate_candles(candles)
    indicators = _indicators(candles)
    direction = _direction(indicators)
    score = _score(indicators, direction)

    return _build_result(
        symbol=symbol,
        mode="single_timeframe",
        candles=candles,
        indicators=indicators,
        direction=direction,
        score=score,
        account_balance=account_balance,
        risk_percent=risk_percent,
        value_per_price_unit=value_per_price_unit,
        risk_reward_ratio=risk_reward_ratio,
        timeframe_alignment={},
        reasons=["Single-timeframe technical analysis."],
    )


def analyze_multi_timeframe(
    market_data: dict[str, Sequence[Candle]],
    mode: Mode = "smart_adaptive",
    account_balance: float = 1000.0,
    risk_percent: float = 0.5,
    value_per_price_unit: float = 1.0,
    risk_reward_ratio: float = 2.0,
    symbol: str = "UNKNOWN",
) -> SignalResult:
    """Analyze supplied timeframes and return a conservative signal."""

    if mode not in ("day_trading", "scalping", "smart_adaptive"):
        raise ValueError("Unsupported trading mode.")

    for timeframe, candles in market_data.items():
        _validate_candles(candles)

    if mode == "day_trading":
        required = ("4h", "1h", "15min")
    elif mode == "scalping":
        required = ("1h", "15min", "5min")
    else:
        required = ("4h", "1h", "15min", "5min")

    missing = [tf for tf in required if tf not in market_data]

    if missing:
        raise ValueError(
            "Missing required timeframes: " + ", ".join(missing)
        )

    indicators_by_tf = {
        tf: _indicators(market_data[tf])
        for tf in required
    }

    directions = {
        tf: _direction(indicators)
        for tf, indicators in indicators_by_tf.items()
    }

    selected_mode = mode

    if mode == "smart_adaptive":
        higher_buy = (
            directions["4h"] == "BUY"
            and directions["1h"] == "BUY"
        )
        higher_sell = (
            directions["4h"] == "SELL"
            and directions["1h"] == "SELL"
        )

        if higher_buy or higher_sell:
            selected_mode = "day_trading"
            entry_tf = "15min"
            required_for_alignment = ("4h", "1h", "15min")
        else:
            selected_mode = "scalping"
            entry_tf = "5min"
            required_for_alignment = ("1h", "15min", "5min")

            if (
                directions["1h"] not in ("BUY", "SELL")
                or directions["1h"] != directions["15min"]
            ):
                return _build_result(
                    symbol=symbol,
                    mode="smart_adaptive",
                    candles=market_data["5min"],
                    indicators=indicators_by_tf["5min"],
                    direction="NO_TRADE",
                    score=0,
                    account_balance=account_balance,
                    risk_percent=risk_percent,
                    value_per_price_unit=value_per_price_unit,
                    risk_reward_ratio=risk_reward_ratio,
                    timeframe_alignment=directions,
                    reasons=[
                        "No clear alignment for adaptive strategy selection."
                    ],
                )

    elif selected_mode == "day_trading":
        entry_tf = "15min"
        required_for_alignment = ("4h", "1h", "15min")
    else:
        entry_tf = "5min"
        required_for_alignment = ("1h", "15min", "5min")

    alignment_directions = [
        directions[tf] for tf in required_for_alignment
    ]

    if (
        alignment_directions[0] not in ("BUY", "SELL")
        or len(set(alignment_directions)) != 1
    ):
        return _build_result(
            symbol=symbol,
            mode=selected_mode,
            candles=market_data[entry_tf],
            indicators=indicators_by_tf[entry_tf],
            direction="NO_TRADE",
            score=0,
            account_balance=account_balance,
            risk_percent=risk_percent,
            value_per_price_unit=value_per_price_unit,
            risk_reward_ratio=risk_reward_ratio,
            timeframe_alignment=directions,
            reasons=[
                "Timeframes are not fully aligned; no trade is recommended."
            ],
        )

    direction = alignment_directions[0]
    entry_indicators = indicators_by_tf[entry_tf]
    score = min(
        _score(indicators_by_tf[tf], direction)
        for tf in required_for_alignment
    )

    return _build_result(
        symbol=symbol,
        mode=selected_mode,
        candles=market_data[entry_tf],
        indicators=entry_indicators,
        direction=direction,
        score=score,
        account_balance=account_balance,
        risk_percent=risk_percent,
        value_per_price_unit=value_per_price_unit,
        risk_reward_ratio=risk_reward_ratio,
        timeframe_alignment=directions,
        reasons=[
            f"Selected strategy: {selected_mode}.",
            "All required timeframes agree on direction.",
        ],
    )


def result_to_dict(result: SignalResult) -> dict[str, Any]:
    """Convert a SignalResult to a JSON-serializable dictionary."""

    return asdict(result)
