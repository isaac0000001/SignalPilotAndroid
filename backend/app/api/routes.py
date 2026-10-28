from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.signals import (
    Candle,
    analyze_market,
    analyze_multi_timeframe,
    result_to_dict,
)
from app.services.market_data import (
    MarketDataError,
    fetch_forex_candles,
)

logger = logging.getLogger(__name__)
router = APIRouter()

LIVE_EXECUTION_ENABLED = False


class SignalAnalysisRequest(BaseModel):
    symbol: str = Field(..., min_length=3, max_length=20)
    candles: list[dict[str, Any]]
    account_balance: float = Field(1000.0, gt=0)
    risk_percent: float = Field(0.5, gt=0, le=1)
    value_per_price_unit: float = Field(..., gt=0)
    risk_reward_ratio: float = Field(2.0, ge=1)


class MultiTimeframeSignalRequest(BaseModel):
    symbol: str = Field(..., min_length=3, max_length=20)
    mode: Literal[
        "day_trading",
        "scalping",
        "smart_adaptive",
    ] = "smart_adaptive"
    account_balance: float = Field(1000.0, gt=0)
    risk_percent: float = Field(0.5, gt=0, le=1)
    value_per_price_unit: float = Field(..., gt=0)
    risk_reward_ratio: float = Field(2.0, ge=1)


def _to_candles(rows: list[dict[str, Any]]) -> list[Candle]:
    candles = []

    for row in rows:
        try:
            candles.append(
                Candle(
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail="Invalid candle returned by market-data provider.",
            ) from exc

    return candles


async def _fetch(
    symbol: str,
    interval: str,
) -> list[dict[str, Any]]:
    try:
        rows = await fetch_forex_candles(
            symbol=symbol,
            interval=interval,
            outputsize=120,
        )
    except MarketDataError as exc:
        logger.warning("Market-data request failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Market data unavailable for {symbol} ({interval}).",
        ) from exc

    if len(rows) < 60:
        raise HTTPException(
            status_code=502,
            detail=f"Insufficient candle history for {symbol} ({interval}).",
        )

    return rows


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "SignalPilot Pro",
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


@router.get("/market-data/{symbol}")
async def get_market_data(
    symbol: str,
    interval: str = Query("1h"),
    outputsize: int = Query(120, ge=60, le=5000),
) -> dict[str, Any]:
    try:
        rows = await fetch_forex_candles(
            symbol=symbol,
            interval=interval,
            outputsize=outputsize,
        )
    except MarketDataError as exc:
        logger.warning("Market-data request failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Market-data provider could not supply the requested data.",
        ) from exc

    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "count": len(rows),
        "candles": rows,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


@router.post("/signals/analyze")
async def analyze_single_timeframe(
    request: SignalAnalysisRequest,
) -> dict[str, Any]:
    candles = _to_candles(request.candles)

    try:
        result = analyze_market(
            candles=candles,
            account_balance=request.account_balance,
            risk_percent=request.risk_percent,
            value_per_price_unit=request.value_per_price_unit,
            risk_reward_ratio=request.risk_reward_ratio,
            symbol=request.symbol,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "signal": result_to_dict(result),
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "execution_note": "Analysis only. No orders are placed.",
    }


@router.post("/signals/analyze-multi-timeframe")
async def analyze_multi_timeframe_signal(
    request: MultiTimeframeSignalRequest,
) -> dict[str, Any]:
    symbol = request.symbol.upper()

    if request.mode == "day_trading":
        intervals = {"4h": "4h", "1h": "1h", "15min": "15min"}
    elif request.mode == "scalping":
        intervals = {"1h": "1h", "15min": "15min", "5min": "5min"}
    else:
        intervals = {
            "4h": "4h",
            "1h": "1h",
            "15min": "15min",
            "5min": "5min",
        }

    market_data: dict[str, list[Candle]] = {}
    counts: dict[str, int] = {}

    for timeframe, interval in intervals.items():
        rows = await _fetch(symbol, interval)
        market_data[timeframe] = _to_candles(rows)
        counts[timeframe] = len(rows)

    try:
        result = analyze_multi_timeframe(
            market_data=market_data,
            mode=request.mode,
            account_balance=request.account_balance,
            risk_percent=request.risk_percent,
            value_per_price_unit=request.value_per_price_unit,
            risk_reward_ratio=request.risk_reward_ratio,
            symbol=symbol,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "symbol": symbol,
        "requested_mode": request.mode,
        "signal": result_to_dict(result),
        "market_data": {
            "status": "received",
            "candles_per_timeframe": counts,
        },
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "execution_note": (
            "Analysis only. No broker orders are placed. "
            "Position sizing is an estimate pending verification of broker specifications."
        ),
    }


@router.get("/signals/live/{symbol}")
async def live_signal_status(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "status": "analysis_endpoint_required",
        "message": (
            "Use POST /signals/analyze-multi-timeframe "
            "to request technical analysis."
        ),
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


@router.get("/account")
async def account_status() -> dict[str, Any]:
    return {
        "account_balance": 1000.0,
        "currency": "USD",
        "mode": "analysis_only",
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


@router.post("/risk/calculate")
async def calculate_risk(
    account_balance: float = Query(..., gt=0),
    risk_percent: float = Query(0.5, gt=0, le=1),
    stop_distance: float = Query(..., gt=0),
    value_per_price_unit: float = Query(..., gt=0),
) -> dict[str, Any]:
    risk_amount = account_balance * risk_percent / 100.0
    position_size = risk_amount / (
        stop_distance * value_per_price_unit
    )

    return {
        "account_balance": account_balance,
        "risk_percent": risk_percent,
        "risk_amount": round(risk_amount, 2),
        "stop_distance": stop_distance,
        "estimated_position_size": round(position_size, 4),
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "warning": (
            "Estimate only. Confirm contract size, tick value, "
            "account currency, spread, commission, and broker lot limits."
        ),
    }


@router.post("/orders")
async def simulated_order_status() -> dict[str, Any]:
    raise HTTPException(
        status_code=403,
        detail="Order submission is disabled.",
    )
