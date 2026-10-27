import logging
import math
import os

import httpx

logger = logging.getLogger(__name__)


class MarketDataError(Exception):
    """Raised when market data cannot be retrieved."""


async def fetch_forex_candles(
    symbol: str,
    interval: str = "1h",
    outputsize: int = 100,
) -> list[dict]:
    """Fetch OHLC candles from Twelve Data in chronological order."""

    api_key = os.getenv("TWELVEDATA_API_KEY")

    if not api_key:
        raise MarketDataError(
            "TWELVEDATA_API_KEY is not configured on the server."
        )

    symbol = symbol.strip().upper()

    if not symbol:
        raise MarketDataError("A symbol is required.")

    allowed_intervals = {
        "1min", "5min", "15min", "30min", "45min",
        "1h", "2h", "4h", "1day", "1week", "1month",
    }

    if interval not in allowed_intervals:
        raise MarketDataError("Unsupported candle interval.")

    if not 60 <= outputsize <= 5000:
        raise MarketDataError(
            "Output size must be between 60 and 5000."
        )

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
        "format": "JSON",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://api.twelvedata.com/time_series",
                params=params,
            )

            response.raise_for_status()
            data = response.json()

    except httpx.TimeoutException as exc:
        logger.error("Twelve Data request timed out.")
        raise MarketDataError(
            "Twelve Data request timed out. Please try again."
        ) from exc

    except httpx.HTTPStatusError as exc:
        logger.error(
            "Twelve Data HTTP error: status=%s",
            exc.response.status_code,
        )
        raise MarketDataError(
            f"Twelve Data returned HTTP {exc.response.status_code}."
        ) from exc

    except httpx.RequestError as exc:
        logger.error(
            "Twelve Data connection error: %s",
            type(exc).__name__,
        )
        raise MarketDataError(
            "Could not connect to Twelve Data."
        ) from exc

    except ValueError as exc:
        logger.error("Twelve Data returned invalid JSON.")
        raise MarketDataError(
            "Twelve Data returned an invalid response."
        ) from exc

    if not isinstance(data, dict):
        raise MarketDataError(
            "Twelve Data returned an unexpected response."
        )

    if data.get("status") == "error" or "values" not in data:
        # Log the provider's message, but never log the API key.
        provider_message = str(
            data.get("message", "No candle data returned.")
        )

        logger.error(
            "Twelve Data rejected the request: %s",
            provider_message,
        )

        raise MarketDataError(
            f"Twelve Data error: {provider_message}"
        )

    candles = []

    for item in reversed(data["values"]):
        try:
            candle = {
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            }

            values = list(candle.values())

            if not all(
                math.isfinite(value) and value > 0
                for value in values
            ):
                continue

            if (
                candle["high"] < candle["low"]
                or candle["high"] < max(
                    candle["open"], candle["close"]
                )
                or candle["low"] > min(
                    candle["open"], candle["close"]
                )
            ):
                continue

            candles.append(candle)

        except (KeyError, TypeError, ValueError):
            continue

    if not candles:
        raise MarketDataError(
            "The provider returned no valid candles."
        )

    return candles
