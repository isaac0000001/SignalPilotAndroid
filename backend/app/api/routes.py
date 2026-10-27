from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentAccount
from app.risk import RiskValidationError, calculate_position_size
from app.schemas import (
    AccountResponse,
    OrderCreateRequest,
    OrderResponse,
    RiskCalculationRequest,
    RiskCalculationResponse,
)
from app.services.market_data import (
    MarketDataError,
    fetch_forex_candles,
)
from app.services.orders import (
    DuplicateOrderConflict,
    OrderService,
    OrderServiceError,
)
from app.signals import Candle, analyze_market


router = APIRouter()

LIVE_MARKET_DATA_ENABLED = False
LIVE_EXECUTION_ENABLED = False


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "application": "SignalPilot Pro",
        "live_market_data": LIVE_MARKET_DATA_ENABLED,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


# --------------------------------------------------
# ACCOUNT
# --------------------------------------------------

@router.get("/account", response_model=AccountResponse)
async def get_account(
    account: CurrentAccount,
):
    return account


# --------------------------------------------------
# RISK CALCULATION
# --------------------------------------------------

@router.post(
    "/risk/calculate",
    response_model=RiskCalculationResponse,
)
async def calculate_risk(
    request: RiskCalculationRequest,
):
    try:
        result = calculate_position_size(
            account_balance=request.account_balance,
            risk_percent=request.risk_percent,
            entry_price=request.entry_price,
            stop_loss=request.stop_loss,
            value_per_price_unit=request.value_per_price_unit,
        )

        return result

    except RiskValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Unable to calculate position size from the supplied values.",
        ) from exc


# --------------------------------------------------
# SIMULATED ORDER CREATION
# --------------------------------------------------

@router.post(
    "/orders",
    response_model=OrderResponse,
)
async def create_order(
    request: OrderCreateRequest,
    account: CurrentAccount,
    db: AsyncSession = Depends(get_db),
):
    """
    Creates a simulated order only.
    This endpoint does not send orders to LiteFinance.
    """

    try:
        async with db.begin():
            order = await OrderService.create_simulated_order(
                db=db,
                account_id=account.id,
                request=request,
            )

        return order

    except DuplicateOrderConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except OrderServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


# --------------------------------------------------
# SIGNAL ANALYSIS REQUEST
# --------------------------------------------------

class SignalAnalysisRequest(BaseModel):
    symbol: str = Field(
        min_length=3,
        max_length=32,
    )

    candles: list[Candle] = Field(
        min_length=60,
        max_length=5000,
    )

    account_balance: Decimal = Field(
        gt=0,
    )

    risk_percent: Decimal = Field(
        gt=0,
        le=5,
    )

    value_per_price_unit: Decimal = Field(
        gt=0,
    )


# --------------------------------------------------
# ANALYZE SUPPLIED MARKET CANDLES
# --------------------------------------------------

@router.post("/signals/analyze")
async def analyze_signal(
    request: SignalAnalysisRequest,
):
    """
    Analyzes candle data supplied by the client.

    This endpoint generates analysis only.
    It does not execute a trade.
    """

    symbol = request.symbol.strip().upper().replace("-", "/")

    if not symbol:
        raise HTTPException(
            status_code=400,
            detail="A valid trading symbol is required.",
        )

    try:
        result = analyze_market(
            candles=request.candles,
            account_balance=request.account_balance,
            risk_percent=request.risk_percent,
            value_per_price_unit=request.value_per_price_unit,
        )

        return {
            "symbol": symbol,
            "signal": result["signal"],
            "score": result["score"],
            "entry": result["entry"],
            "stop_loss": result["stop_loss"],
            "take_profit": result["take_profit"],
            "quantity": result["quantity"],
            "risk_amount": result["risk_amount"],
            "reasons": result["reasons"],
            "live_market_data": LIVE_MARKET_DATA_ENABLED,
            "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        }

    except RiskValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Signal analysis failed because of invalid input data.",
        ) from exc


# --------------------------------------------------
# MARKET DATA
# --------------------------------------------------

@router.get("/market-data/{symbol}")
async def get_market_data(
    symbol: str,
    interval: Literal[
        "1min",
        "5min",
        "15min",
        "30min",
        "1h",
        "4h",
        "1day",
    ] = Query(default="1h"),
    outputsize: int = Query(
        default=100,
        ge=60,
        le=5000,
    ),
):
    """
    Retrieves historical candle data from the configured
    market-data provider.

    TWELVEDATA_API_KEY must be configured on the server.
    """

    normalized_symbol = symbol.strip().upper().replace("-", "/")

    if not normalized_symbol:
        raise HTTPException(
            status_code=400,
            detail="A valid trading symbol is required.",
        )

    try:
        candles = await fetch_forex_candles(
            symbol=normalized_symbol,
            interval=interval,
            outputsize=outputsize,
        )

        # market_data.py returns dictionaries, not Candle objects.
        formatted_candles = [
            {
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
            }
            for candle in candles
        ]

        return {
            "symbol": normalized_symbol,
            "interval": interval,
            "count": len(formatted_candles),
            "candles": formatted_candles,
            "live_market_data": True,
            "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        }

    except MarketDataError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="The market-data provider returned an invalid candle format.",
        ) from exc


# --------------------------------------------------
# LIVE SIGNAL ENDPOINT
# --------------------------------------------------

@router.get("/signals/live/{symbol}")
async def get_live_signal(
    symbol: str,
    interval: Literal[
        "1min",
        "5min",
        "15min",
        "30min",
        "1h",
        "4h",
        "1day",
    ] = Query(default="1h"),
    outputsize: int = Query(
        default=100,
        ge=60,
        le=5000,
    ),
):
    """
    Retrieves market candles.

    Signal generation remains unavailable here until the
    instrument's contract specifications and price-value
    calculations have been validated.
    """

    normalized_symbol = symbol.strip().upper().replace("-", "/")

    if not normalized_symbol:
        raise HTTPException(
            status_code=400,
            detail="A valid trading symbol is required.",
        )

    try:
        candles = await fetch_forex_candles(
            symbol=normalized_symbol,
            interval=interval,
            outputsize=outputsize,
        )

    except MarketDataError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    if len(candles) < 60:
        raise HTTPException(
            status_code=422,
            detail="At least 60 valid candles are required for analysis.",
        )

    raise HTTPException(
        status_code=501,
        detail={
            "message": (
                "Live signal generation is not yet enabled for this endpoint. "
                "Instrument specifications and position-sizing calculations "
                "must be validated first."
            ),
            "symbol": normalized_symbol,
            "candles_received": len(candles),
            "live_execution_enabled": False,
        },
    )
