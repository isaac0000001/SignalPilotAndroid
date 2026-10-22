from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentAccount
from app.models import Order
from app.risk import RiskValidationError, calculate_position_size
from app.schemas import (
    AccountResponse,
    HealthResponse,
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


router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    return HealthResponse(
        status="ok",
        application="SignalPilot Pro",
        version="1.0.0",
        database="connected",
    )


@router.get("/account", response_model=AccountResponse, tags=["Account"])
async def get_account(account: CurrentAccount):
    return account


@router.post(
    "/risk/calculate",
    response_model=RiskCalculationResponse,
    tags=["Risk"],
)
async def calculate_risk(request: RiskCalculationRequest):
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Orders"],
)
async def create_simulated_order(
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
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except OrderServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
