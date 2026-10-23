import os
from decimal import Decimal
from typing import Any

import httpx

from app.signals import Candle


API_URL = "https://api.twelvedata.com/time_series"

ALLOWED_INTERVALS = {
    "1min",
    "5min",
    "15min",
    "30min",
    "1h",
    "4h",
    "1day",
}


class MarketDataError(Exception):
    """Raised when market data cannot be retrieved or validated."""


async def fetch_forex_candles(
    symbol: str,
    interval: str = "1h",
    outputsize: int = 100,
) -> list[Candle]:
    """
    Fetch historical OHLC candles from Twelve Data.

    Symbols use the format EUR/USD.
    Returned candles are ordered oldest to newest.

    This service retrieves market data only.
    It does not execute trades.
    """

    api_key = os.getenv("TWELVE_DATA_API_KEY")

    if not api_key:
        raise MarketDataError(
            "The TWELVE_DATA_API_KEY environment variable is not configured."
        )

    symbol = symbol.strip().upper()

    if not symbol or len(symbol) > 30:
        raise MarketDataError("A valid market symbol is required.")

    if interval not in ALLOWED_INTERVALS:
        raise MarketDataError("Unsupported candle interval.")

    if not 60 <= outputsize <= 5000:
        raise MarketDataError(
            "Output size must be between 60 and 5000 candles."
        )

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
        "format": "JSON",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(API_URL, params=params)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()

    except httpx.TimeoutException as exc:
        raise MarketDataError(
            "The market-data provider timed out."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise MarketDataError(
            f"Market-data provider returned HTTP {exc.response.status_code}."
        ) from exc

    except httpx.RequestError as exc:
        raise MarketDataError(
            "Unable to connect to the market-data provider."
        ) from exc

    except ValueError as exc:
        raise MarketDataError(
            "The provider returned an invalid response."
        ) from exc

    if payload.get("status") == "error":
        message = str(payload.get("message", "Provider request failed."))
        raise MarketDataError(message[:250])

    values = payload.get("values")

    if not isinstance(values, list):
        raise MarketDataError(
            "The provider response did not contain candle data."
        )

    if len(values) < 60:
        raise MarketDataError(
            "The provider returned fewer than 60 candles."
        )

    candles = []

    try:
        for item in reversed(values):
            candle = Candle(
                open=float(Decimal(str(item["open"]))),
                high=float(Decimal(str(item["high"]))),
                low=float(Decimal(str(item["low"]))),
                close=float(Decimal(str(item["close"]))),
            )

            candles.append(candle)

    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise MarketDataError(
            "The provider returned malformed candle data."
        ) from exc

    for candle in candles:
        prices = (
            candle.open,
            candle.high,
            candle.low,
            candle.close,
        )

        if any(price <= 0 for price in prices):
            raise MarketDataError(
                "The provider returned a non-positive price."
            )

        if candle.high < max(
            candle.open,
            candle.close,
            candle.low,
        ):
            raise MarketDataError(
                "The provider returned an inconsistent candle high."
            )

        if candle.low > min(
            candle.open,
            candle.close,
            candle.high,
        ):
            raise MarketDataError(
                "The provider returned an inconsistent candle low."
            )

    return candles
