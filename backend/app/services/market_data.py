import os

import httpx


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
            "TWELVEDATA_API_KEY is not configured."
        )

    symbol = symbol.strip().upper()

    if not symbol:
        raise MarketDataError("A symbol is required.")

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

    if not 1 <= outputsize <= 5000:
        raise MarketDataError("Invalid output size.")

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
        "format": "JSON",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                "https://api.twelvedata.com/time_series",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

    except (httpx.HTTPError, ValueError) as exc:
        raise MarketDataError(
            "Unable to retrieve market data."
        ) from exc

    if data.get("status") == "error" or "values" not in data:
        raise MarketDataError(
            data.get("message", "No market candles were returned.")
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
                value > 0 and value < float("inf")
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
