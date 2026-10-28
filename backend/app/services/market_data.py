import logging
import math
import os
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"

ALLOWED_INTERVALS = {
    "1min",
    "5min",
    "15min",
    "30min",
    "45min",
    "1h",
    "2h",
    "4h",
    "1day",
    "1week",
    "1month",
}


class MarketDataError(Exception):
    """Raised when market data cannot be retrieved."""


def normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise MarketDataError("Symbol must be text.")

    symbol = symbol.strip().upper().replace("-", "/").replace("_", "/")

    if not symbol:
        raise MarketDataError("A symbol is required.")

    if "/" not in symbol and len(symbol) == 6 and symbol.isalpha():
        symbol = f"{symbol[:3]}/{symbol[3:]}"

    return symbol


async def fetch_forex_candles(
    symbol: str,
    interval: str = "1h",
    outputsize: int = 100,
) -> list[dict[str, Any]]:
    """Fetch validated OHLC candles in chronological order."""

    api_key = os.getenv("TWELVEDATA_API_KEY")

    if not api_key or not api_key.strip():
        raise MarketDataError("Market data API key is not configured.")

    normalized_symbol = normalize_symbol(symbol)

    if interval not in ALLOWED_INTERVALS:
        raise MarketDataError(f"Unsupported interval: {interval}")

    if isinstance(outputsize, bool) or not isinstance(outputsize, int):
        raise MarketDataError("Output size must be an integer.")

    if not 60 <= outputsize <= 5000:
        raise MarketDataError("Output size must be between 60 and 5000.")

    params = {
        "symbol": normalized_symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key.strip(),
        "format": "JSON",
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(TWELVE_DATA_URL, params=params)
            response.raise_for_status()
            data = response.json()

    except httpx.TimeoutException as exc:
        raise MarketDataError("Market-data provider timed out.") from exc

    except httpx.HTTPStatusError as exc:
        raise MarketDataError(
            f"Market-data provider returned HTTP {exc.response.status_code}."
        ) from exc

    except httpx.RequestError as exc:
        logger.warning("Twelve Data connection failed: %s", type(exc).__name__)
        raise MarketDataError("Unable to connect to market-data provider.") from exc

    except ValueError as exc:
        raise MarketDataError("Market-data provider returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise MarketDataError("Unexpected provider response.")

    if data.get("status") == "error" or "values" not in data:
        message = str(data.get("message", "No candle data returned."))
        raise MarketDataError(f"Twelve Data error: {message}")

    raw_values = data.get("values")

    if not isinstance(raw_values, list):
        raise MarketDataError("Provider returned an invalid candle list.")

    candles: list[dict[str, Any]] = []

    # Twelve Data normally returns newest candles first.
    for item in reversed(raw_values):
        if not isinstance(item, dict):
            continue

        try:
            timestamp = str(item["datetime"])

            # Check the timestamp format without changing the original value.
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

            candle = {
                "timestamp": timestamp,
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            }
        except (KeyError, TypeError, ValueError):
            continue

        prices = [
            candle["open"],
            candle["high"],
            candle["low"],
            candle["close"],
        ]

        if not all(math.isfinite(price) and price > 0 for price in prices):
            continue

        if candle["high"] < max(candle["open"], candle["close"]):
            continue

        if candle["low"] > min(candle["open"], candle["close"]):
            continue

        if candle["high"] < candle["low"]:
            continue

        candles.append(candle)

    if not candles:
        raise MarketDataError("Provider returned no valid candles.")

    logger.info(
        "Retrieved %d candles for %s at %s.",
        len(candles),
        normalized_symbol,
        interval,
    )

    return candles
