from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentAccount
from app.risk import (
    RiskValidationError,
    calculate_position_size,
)
from app.schemas import (
    AccountResponse,
    OrderCreateRequest,
    OrderResponse,
    RiskCalculationRequest,
    RiskCalculationResponse,
)
from app.services.orders import (
    DuplicateOrderConflict,
    OrderService,
    OrderServiceError,
)
from app.services.market_data import (
    MarketDataError,
    fetch_forex_candles,
)
from app.signals import Candle, analyze_market


router = APIRouter()


# =========================================================
# 1. HEALTH CHECK
# =========================================================

@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "application": "SignalPilot Pro",
        "live_market_data": False,
        "live_execution_enabled": False,
    }


# =========================================================
# 2. ACCOUNT INFORMATION
# =========================================================

@router.get(
    "/account",
    response_model=AccountResponse,
)
async def get_account(account: CurrentAccount):
    return account


# =========================================================
# 3. POSITION SIZE AND RISK CALCULATION
# =========================================================

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
            quantity_step=request.quantity_step,
            minimum_quantity=request.minimum_quantity,
            maximum_quantity=request.maximum_quantity,
        )

    except RiskValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return RiskCalculationResponse(
        risk_amount=result.risk_amount,
        stop_distance=result.stop_distance,
        estimated_loss_per_unit=result.estimated_loss_per_unit,
        suggested_quantity=result.suggested_quantity,
        estimated_total_risk=result.estimated_total_risk,
        actual_risk_percent=result.actual_risk_percent,
    )


# =========================================================
# 4. SIMULATED ORDER CREATION
# =========================================================

@router.post(
    "/orders",
    response_model=OrderResponse,
)
async def create_order(
    request: OrderCreateRequest,
    account: CurrentAccount,
    db: AsyncSession = Depends(get_db),
):
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


# =========================================================
# 5. SIGNAL ANALYSIS REQUEST
# =========================================================

class SignalAnalysisRequest(BaseModel):
    symbol: str = Field(
        min_length=3,
        max_length=30,
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
        le=Decimal("1"),
    )

    value_per_price_unit: Decimal = Field(
        gt=0,
    )


# =========================================================
# 6. ANALYZE A MARKET AND GENERATE A SIGNAL
# =========================================================

@router.post("/signals/analyze")
async def analyze_signal(
    request: SignalAnalysisRequest,
):
    try:
        result = analyze_market(
            symbol=request.symbol,
            candles=request.candles,
            account_balance=request.account_balance,
            risk_percent=request.risk_percent,
            value_per_price_unit=request.value_per_price_unit,
        )

    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "symbol": result.symbol,
        "signal": result.signal,
        "score": result.score,
        "entry": result.entry,
        "stop_loss": result.stop_loss,
        "take_profit": result.take_profit,
        "quantity": str(result.quantity),
        "risk_amount": str(result.risk_amount),
        "reasons": list(result.reasons),
        "live_market_data": False,
        "live_execution_enabled": False,
    }


# =========================================================
# 7. FETCH FOREX MARKET DATA FROM TWELVE DATA
# =========================================================

@router.get("/market-data/{symbol}")
async def get_market_data(
    symbol: str,
    interval: str = Query(
        default="1h",
        pattern=r"^(1min|5min|15min|30min|1h|4h|1day)$",
    ),
    outputsize: int = Query(
        default=100,
        ge=60,
        le=5000,
    ),
):
    normalized_symbol = symbol.upper().replace("-", "/")

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

    return {
        "symbol": normalized_symbol,
        "interval": interval,
        "candle_count": len(candles),
        "candles": [
            {
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
            }
            for candle in candles
        ],
        "source": "Twelve Data",
        "live_execution_enabled": False,
    }


# =========================================================
# 8. FETCH MARKET DATA AND ANALYZE IT IN ONE REQUEST
# =========================================================

@router.get("/signals/live/{symbol}")
async def analyze_live_market(
    symbol: str,
    account_balance: Decimal = Query(
        gt=0,
    ),
    risk_percent: Decimal = Query(
        default=Decimal("0.5"),
        gt=0,
        le=Decimal("1"),
    ),
    interval: str = Query(
        default="1h",
        pattern=r"^(1min|5min|15min|30min|1h|4h|1day)$",
    ),
):
    normalized_symbol = symbol.upper().replace("-", "/")

    try:
        candles = await fetch_forex_candles(
            symbol=normalized_symbol,
            interval=interval,
            outputsize=100,
        )

    except MarketDataError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    # Price-unit valuation is instrument-specific.
    # Do not guess it for a real-money position.
    # The signal calculation requires a validated value.
    raise HTTPException(
        status_code=501,
        detail=(
            "Market data retrieval is implemented, but automatic "
            "signal generation requires a verified value_per_price_unit "
            "for this instrument. Use POST /signals/analyze with a "
            "validated value until instrument specifications are configured."
        ),
    )
