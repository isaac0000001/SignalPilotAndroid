import os
from datetime import datetime, timezone

import httpx


class MarketDataError(Exception):
    """Raised when market data cannot be retrieved."""


async def fetch_forex_candles(
    symbol: str,
    interval: str = "5min",
    outputsize: int = 100,
):
    """
    Fetch forex candles from Twelve Data.

    Requires the TWELVEDATA_API_KEY environment variable.
    """

    api_key = os.getenv("TWELVEDATA_API_KEY")

    if not api_key:
        raise MarketDataError(
            "Market data API key is not configured."
        )

    symbol = symbol.strip().upper()

    if not symbol:
        raise MarketDataError("A market symbol is required.")

    if not 1 <= outputsize <= 5000:
        raise MarketDataError(
            "Output size must be between 1 and 5000."
        )

    allowed_intervals = {
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

    if interval not in allowed_intervals:
        raise MarketDataError("Unsupported candle interval.")

    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
        "format": "JSON",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

    except (httpx.HTTPError, ValueError) as exc:
        raise MarketDataError(
            "Unable to retrieve market data."
        ) from exc

    if data.get("status") == "error" or "values" not in data:
        raise MarketDataError(
            data.get("message", "Market data provider returned no candles.")
        )

    candles = []

    for item in reversed(data["values"]):
        try:
            candle = {
                "time": item["datetime"],
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": float(item.get("volume") or 0),
            }

            if not all(
                value == value
                and abs(value) != float("inf")
                for key, value in candle.items()
                if key != "time"
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
            "No valid market candles were returned."
        )

    return candles
