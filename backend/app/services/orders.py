import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AuditEvent, Order
from app.schemas import OrderCreateRequest


class OrderServiceError(Exception):
    """Base exception for order service errors."""


class DuplicateOrderConflict(OrderServiceError):
    """Raised when a duplicate client order ID is detected."""


class OrderService:
    """Handles simulated orders for SignalPilot."""

    @staticmethod
    async def create_simulated_order(
        db: AsyncSession,
        account_id: UUID,
        request: OrderCreateRequest,
    ) -> Order:
        """Create a pending simulated order without broker execution."""

        try:
            account_uuid = UUID(str(account_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise OrderServiceError("Invalid account ID.") from exc

        if not isinstance(request, OrderCreateRequest):
            raise OrderServiceError("Invalid order request.")

        result = await db.execute(
            select(Account)
            .where(Account.id == account_uuid)
            .with_for_update()
        )
        account = result.scalar_one_or_none()

        if account is None:
            raise OrderServiceError("Account not found.")

        if not account.is_active:
            raise OrderServiceError("Account is inactive.")

        result = await db.execute(
            select(Order).where(
                Order.account_id == account_uuid,
                Order.client_order_id == request.client_order_id,
            )
        )

        if result.scalar_one_or_none() is not None:
            raise DuplicateOrderConflict(
                "This client order ID already exists."
            )

        order = Order(
            account_id=account_uuid,
            client_order_id=request.client_order_id,
            symbol=request.symbol.upper(),
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            requested_price=request.requested_price,
            filled_price=None,
            status="PENDING",
            execution_mode="SIMULATED",
        )

        db.add(order)

        audit_event = AuditEvent(
            event_type="SIMULATED_ORDER_CREATED",
            actor="system",
            resource_id=request.client_order_id,
            details=json.dumps({
                "account_id": str(account_uuid),
                "symbol": request.symbol.upper(),
                "side": request.side,
                "order_type": request.order_type,
                "quantity": str(request.quantity),
                "requested_price": (
                    str(request.requested_price)
                    if request.requested_price is not None
                    else None
                ),
                "stop_loss": (
                    str(request.stop_loss)
                    if request.stop_loss is not None
                    else None
                ),
                "take_profit": (
                    str(request.take_profit)
                    if request.take_profit is not None
                    else None
                ),
                "execution_mode": "SIMULATED",
            }),
        )
        db.add(audit_event)

        try:
            await db.flush()
            await db.refresh(order)

        except IntegrityError as exc:
            raise DuplicateOrderConflict(
                "Order conflicts with an existing database record."
            ) from exc

        return order
