from __future__ import annotations

import asyncio
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

router = APIRouter(tags=["SignalPilot Pro"])

LIVE_EXECUTION_ENABLED = False

# Maximum number of simultaneous requests to Twelve Data.
SCAN_CONCURRENCY = 2

# Supported forex scanning instruments.
SUPPORTED_SCAN_SYMBOLS = {
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "USD/CAD",
    "AUD/USD",
    "NZD/USD",
    "EUR/GBP",
    "EUR/JPY",
    "GBP/JPY",
    "EUR/AUD",
    "GBP/AUD",
    "AUD/JPY",
    "GBP/CHF",
    "CAD/JPY",
}


# =====================================================
# REQUEST MODELS
# =====================================================

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


class MarketScanRequest(BaseModel):
    symbols: list[str] = Field(
        default_factory=lambda: [
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "USDCHF",
            "USDCAD",
        ],
        min_length=1,
        max_length=15,
    )

    mode: Literal[
        "day_trading",
        "scalping",
        "smart_adaptive",
    ] = "smart_adaptive"

    account_balance: float = Field(1000.0, gt=0)
    risk_percent: float = Field(0.5, gt=0, le=1)
    value_per_price_unit: float = Field(..., gt=0)
    risk_reward_ratio: float = Field(2.0, ge=1)

    minimum_score: int = Field(
        60,
        ge=60,
        le=100,
    )


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def _normalize_market_symbol(symbol: str) -> str:
    """
    Convert common six-letter forex symbols into
    the slash-separated format expected by Twelve Data.

    EURUSD becomes EUR/USD.
    GBPJPY becomes GBP/JPY.
    EUR/USD remains EUR/USD.
    """

    symbol = symbol.strip().upper().replace("-", "/")

    if (
        "/" not in symbol
        and len(symbol) == 6
        and symbol.isalpha()
    ):
        symbol = f"{symbol[:3]}/{symbol[3:]}"

    return symbol


def _to_candles(
    rows: list[dict[str, Any]],
) -> list[Candle]:

    candles: list[Candle] = []

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
                detail=(
                    "Invalid candle returned "
                    "by market-data provider."
                ),
            ) from exc

    return candles


async def _fetch(
    symbol: str,
    interval: str,
) -> list[dict[str, Any]]:

    normalized_symbol = _normalize_market_symbol(symbol)

    try:
        rows = await fetch_forex_candles(
            symbol=normalized_symbol,
            interval=interval,
            outputsize=120,
        )

    except MarketDataError as exc:
        logger.warning(
            "Market data unavailable for %s (%s): %s",
            normalized_symbol,
            interval,
            exc,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                f"Market data unavailable for "
                f"{normalized_symbol} ({interval})."
            ),
        ) from exc

    if len(rows) < 60:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Insufficient candle history for "
                f"{normalized_symbol} ({interval})."
            ),
        )

    return rows


def _timeframes_for_mode(
    mode: str,
) -> dict[str, str]:

    if mode == "day_trading":
        return {
            "4h": "4h",
            "1h": "1h",
            "15min": "15min",
        }

    if mode == "scalping":
        return {
            "1h": "1h",
            "15min": "15min",
            "5min": "5min",
        }

    return {
        "4h": "4h",
        "1h": "1h",
        "15min": "15min",
        "5min": "5min",
    }


# =====================================================
# HEALTH CHECK
# =====================================================

@router.get(
    "/health",
    summary="Health Check",
)
async def health():

    return {
        "status": "ok",
        "service": "SignalPilot Pro",
        "live_market_analysis": True,
        "multi_market_scanner": True,
        "live_execution_enabled": False,
    }


# =====================================================
# MARKET DATA
# =====================================================

@router.get(
    "/market-data/{symbol}",
    summary="Get Market Data",
)
async def get_market_data(
    symbol: str,
    interval: str = Query("1h"),
    outputsize: int = Query(
        120,
        ge=60,
        le=5000,
    ),
):

    normalized_symbol = _normalize_market_symbol(symbol)

    try:
        rows = await fetch_forex_candles(
            symbol=normalized_symbol,
            interval=interval,
            outputsize=outputsize,
        )

    except MarketDataError as exc:
        logger.warning(
            "Market data request failed for %s: %s",
            normalized_symbol,
            exc,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Market-data provider could not "
                "supply the requested data."
            ),
        ) from exc

    return {
        "symbol": normalized_symbol,
        "interval": interval,
        "count": len(rows),
        "candles": rows,
        "market_data_available": True,
        "live_execution_enabled": False,
    }


# =====================================================
# SINGLE TIMEFRAME ANALYSIS
# =====================================================

@router.post(
    "/signals/analyze",
    summary="Analyze Single Timeframe Signal",
)
async def analyze_single_timeframe(
    request: SignalAnalysisRequest,
):

    candles = _to_candles(request.candles)

    try:
        result = analyze_market(
            candles=candles,
            account_balance=request.account_balance,
            risk_percent=request.risk_percent,
            value_per_price_unit=request.value_per_price_unit,
            risk_reward_ratio=request.risk_reward_ratio,
            symbol=request.symbol.upper(),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "symbol": request.symbol.upper(),
        "signal": result_to_dict(result),
        "live_execution_enabled": False,
        "execution_note": (
            "Analysis only. No broker orders are placed."
        ),
    }


# =====================================================
# MULTI-TIMEFRAME ANALYSIS
# =====================================================

@router.post(
    "/signals/analyze-multi-timeframe",
    summary="Analyze Multi-Timeframe Signal",
    description=(
        "Analyzes multiple market timeframes using "
        "Day Trading, Scalping or Smart Adaptive mode."
    ),
)
async def analyze_multi_timeframe_signal(
    request: MultiTimeframeSignalRequest,
):

    symbol = _normalize_market_symbol(request.symbol)

    intervals = _timeframes_for_mode(request.mode)

    market_data: dict[str, list[Candle]] = {}
    counts: dict[str, int] = {}

    for timeframe, interval in intervals.items():

        rows = await _fetch(
            symbol,
            interval,
        )

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
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "application": "SignalPilot Pro",
        "symbol": symbol,
        "requested_mode": request.mode,
        "signal": result_to_dict(result),
        "market_data": {
            "status": "received",
            "candles_per_timeframe": counts,
        },
        "market_data_available": True,
        "live_execution_enabled": False,
        "execution_note": (
            "Technical analysis only. "
            "No broker orders are placed. "
            "Position sizing is an estimate pending "
            "verification of broker specifications."
        ),
    }


# =====================================================
# MULTI-MARKET SCANNER
# =====================================================

@router.post(
    "/signals/scan",
    summary="Scan and Rank Multiple Forex Markets",
    description=(
        "Scans supported forex instruments, "
        "analyzes multiple timeframes and ranks "
        "qualifying trading opportunities."
    ),
)
async def scan_markets(
    request: MarketScanRequest,
):

    # Normalize instruments.
    symbols = [
        _normalize_market_symbol(symbol)
        for symbol in request.symbols
    ]

    # Reject duplicates.
    if len(set(symbols)) != len(symbols):
        raise HTTPException(
            status_code=422,
            detail="Duplicate symbols are not allowed.",
        )

    # Reject unsupported instruments.
    unsupported = [
        symbol
        for symbol in symbols
        if symbol not in SUPPORTED_SCAN_SYMBOLS
    ]

    if unsupported:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Unsupported scanning instruments.",
                "unsupported_symbols": unsupported,
                "supported_symbols": sorted(
                    SUPPORTED_SCAN_SYMBOLS
                ),
            },
        )

    semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)

    intervals = _timeframes_for_mode(request.mode)

    async def scan_one_market(symbol: str):

        market_data: dict[str, list[Candle]] = {}
        counts: dict[str, int] = {}

        try:

            # Retrieve candles for the requested timeframes.
            for timeframe, interval in intervals.items():

                async with semaphore:
                    rows = await _fetch(
                        symbol,
                        interval,
                    )

                candles = _to_candles(rows)

                market_data[timeframe] = candles
                counts[timeframe] = len(candles)

            # Run the existing analysis engine.
            result = analyze_multi_timeframe(
                market_data=market_data,
                mode=request.mode,
                account_balance=request.account_balance,
                risk_percent=request.risk_percent,
                value_per_price_unit=request.value_per_price_unit,
                risk_reward_ratio=request.risk_reward_ratio,
                symbol=symbol,
            )

            result_dict = result_to_dict(result)

            # Apply minimum-score filter.
            if (
                result_dict["signal"] != "NO_TRADE"
                and result_dict["score"] < request.minimum_score
            ):

                result_dict["signal"] = "NO_TRADE"
                result_dict["position_size"] = 0
                result_dict["risk_amount"] = 0

                result_dict["stop_loss"] = (
                    result_dict["entry_price"]
                )

                result_dict["take_profit"] = (
                    result_dict["entry_price"]
                )

                result_dict["reasons"].append(
                    "Signal rejected by scanner minimum-score filter."
                )

            return {
                "symbol": symbol,
                "status": "analyzed",
                "signal": result_dict,
                "candles_per_timeframe": counts,
            }

        except (HTTPException, ValueError) as exc:

            logger.warning(
                "Scanner could not analyze %s: %s",
                symbol,
                str(exc),
            )

            return {
                "symbol": symbol,
                "status": "failed",
                "error": (
                    exc.detail
                    if isinstance(exc, HTTPException)
                    else str(exc)
                ),
            }

        except Exception:

            logger.exception(
                "Unexpected scanner error for %s",
                symbol,
            )

            return {
                "symbol": symbol,
                "status": "failed",
                "error": "Unexpected analysis error.",
            }

    # Run market scans concurrently.
    results = await asyncio.gather(
        *[
            scan_one_market(symbol)
            for symbol in symbols
        ]
    )

    # Separate successful analyses.
    analyzed = [
        item
        for item in results
        if item["status"] == "analyzed"
    ]

    # Select BUY and SELL opportunities.
    opportunities = [
        item
        for item in analyzed
        if item["signal"]["signal"] in ("BUY", "SELL")
    ]

    # Select NO_TRADE markets.
    rejected = [
        item
        for item in analyzed
        if item["signal"]["signal"] == "NO_TRADE"
    ]

    # Select failed markets.
    failed = [
        item
        for item in results
        if item["status"] == "failed"
    ]

    # Rank strongest signals first.
    opportunities.sort(
        key=lambda item: item["signal"]["score"],
        reverse=True,
    )

    ranked_opportunities = [
        {
            "rank": index + 1,
            **item,
        }
        for index, item in enumerate(opportunities)
    ]

    return {
        "application": "SignalPilot Pro",
        "scanner": "multi_market",
        "requested_mode": request.mode,

        "markets_requested": len(symbols),
        "markets_analyzed": len(analyzed),
        "opportunities_found": len(opportunities),
        "markets_rejected": len(rejected),
        "markets_failed": len(failed),

        "minimum_score": request.minimum_score,

        "ranked_opportunities": ranked_opportunities,

        "no_trade_markets": rejected,

        "failed_markets": failed,

        "market_data_available": len(analyzed) > 0,

        "live_execution_enabled": False,

        "note": (
            "Technical analysis only. No broker orders "
            "are placed. Scores are not probabilities "
            "of winning. Position sizing is provisional "
            "and requires verified broker specifications."
        ),
    }


# =====================================================
# LIVE SIGNAL STATUS
# =====================================================

@router.get(
    "/signals/live/{symbol}",
    summary="Get Live Signal Status",
)
async def live_signal_status(
    symbol: str,
):

    return {
        "symbol": _normalize_market_symbol(symbol),
        "status": "analysis_endpoint_required",
        "message": (
            "Use POST /signals/analyze-multi-timeframe "
            "or POST /signals/scan to request analysis."
        ),
        "live_execution_enabled": False,
    }


# =====================================================
# ACCOUNT INFORMATION
# =====================================================

@router.get(
    "/account",
    summary="Get Account Information",
)
async def account_status():

    return {
        "account_balance": 1000.0,
        "currency": "USD",
        "mode": "analysis_only",
        "live_execution_enabled": False,
    }


# =====================================================
# RISK MANAGEMENT
# =====================================================

@router.post(
    "/risk/calculate",
    summary="Calculate Trading Risk",
)
async def calculate_risk(
    account_balance: float = Query(..., gt=0),

    risk_percent: float = Query(
        0.5,
        gt=0,
        le=1,
    ),

    stop_distance: float = Query(..., gt=0),

    value_per_price_unit: float = Query(..., gt=0),
):

    risk_amount = (
        account_balance * risk_percent / 100
    )

    position_size = risk_amount / (
        stop_distance * value_per_price_unit
    )

    return {
        "account_balance": account_balance,
        "risk_percent": risk_percent,
        "risk_amount": round(risk_amount, 2),
        "stop_distance": stop_distance,
        "estimated_position_size": round(
            position_size,
            4,
        ),
        "live_execution_enabled": False,
        "warning": (
            "Estimate only. Confirm contract size, "
            "tick value, account currency, spread, "
            "commission and broker lot limits."
        ),
    }


# =====================================================
# ORDER EXECUTION - DISABLED
# =====================================================

@router.post(
    "/orders",
    summary="Create Order",
)
async def simulated_order_status():

    raise HTTPException(
        status_code=403,
        detail="Live order submission is disabled.",
    )
