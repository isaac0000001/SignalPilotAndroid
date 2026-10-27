import logging
import math
import os
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
    """Normalize common forex symbols for Twelve Data."""

    if not isinstance(symbol, str):
        raise MarketDataError("Symbol must be text.")

    symbol = symbol.strip().upper().replace("-", "/").replace("_", "/")

    if not symbol:
        raise MarketDataError("A symbol is required.")

    # Convert EURUSD to EUR/USD.
    if "/" not in symbol and len(symbol) == 6 and symbol.isalpha():
        symbol = f"{symbol[:3]}/{symbol[3:]}"

    return symbol


async def fetch_forex_candles(
    symbol: str,
    interval: str = "1h",
    outputsize: int = 100,
) -> list[dict[str, Any]]:
    """
    Retrieve historical OHLC candles from Twelve Data.

    Returns candles in chronological order, oldest first.
    The API key must be configured as TWELVEDATA_API_KEY
    in the server environment.
    """

    api_key = os.getenv("TWELVEDATA_API_KEY")

    if not api_key or not api_key.strip():
        raise MarketDataError(
            "Market data is not configured: API key is missing."
        )

    normalized_symbol = normalize_symbol(symbol)

    if interval not in ALLOWED_INTERVALS:
        raise MarketDataError(
            f"Unsupported interval: {interval}."
        )

    if isinstance(outputsize, bool) or not isinstance(outputsize, int):
        raise MarketDataError("Output size must be an integer.")

    if not 60 <= outputsize <= 5000:
        raise MarketDataError(
            "Output size must be between 60 and 5000."
        )

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
            response = await client.get(
                TWELVE_DATA_URL,
                params=params,
            )

            response.raise_for_status()

            data = response.json()

    except httpx.TimeoutException as exc:
        logger.warning("Twelve Data request timed out.")
        raise MarketDataError(
            "The market-data provider timed out. Please retry."
        ) from exc

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code

        logger.error(
            "Twelve Data returned HTTP status %s.",
            status_code,
        )

        raise MarketDataError(
            f"The market-data provider returned HTTP {status_code}."
        ) from exc

    except httpx.RequestError as exc:
        logger.error(
            "Twelve Data connection failed: %s",
            type(exc).__name__,
        )

        raise MarketDataError(
            "Unable to connect to the market-data provider."
        ) from exc

    except ValueError as exc:
        logger.error("Twelve Data returned invalid JSON.")
        raise MarketDataError(
            "The market-data provider returned invalid JSON."
        ) from exc

    if not isinstance(data, dict):
        raise MarketDataError(
            "Unexpected response from the market-data provider."
        )

    # Twelve Data may return an error in JSON even with HTTP 200.
    if data.get("status") == "error" or "values" not in data:
        provider_message = str(
            data.get("message", "No candle data was returned.")
        )

        # Do not log the request URL or API key.
        logger.warning(
            "Twelve Data rejected the market-data request: %s",
            provider_message,
        )

        raise MarketDataError(
            f"Twelve Data error: {provider_message}"
        )

    raw_values = data.get("values")

    if not isinstance(raw_values, list):
        raise MarketDataError(
            "The provider returned an invalid candle list."
        )

    candles: list[dict[str, Any]] = []

    # Twelve Data normally returns newest candles first.
    for item in reversed(raw_values):
        if not isinstance(item, dict):
            continue

        try:
            candle = {
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            }
        except (KeyError, TypeError, ValueError):
            continue

        prices = list(candle.values())

        if not all(
            math.isfinite(price) and price > 0
            for price in prices
        ):
            continue

        if candle["high"] < candle["low"]:
            continue

        if candle["high"] < max(
            candle["open"],
            candle["close"],
        ):
            continue

        if candle["low"] > min(
            candle["open"],
            candle["close"],
        ):
            continue

        candles.append(candle)

    if not candles:
        logger.warning(
            "No valid candles received for symbol %s.",
            normalized_symbol,
        )

        raise MarketDataError(
            "The provider returned no valid candles for this symbol."
        )

    logger.info(
        "Retrieved %s candles for %s at interval %s.",
        len(candles),
        normalized_symbol,
        interval,
    )

    return candles
