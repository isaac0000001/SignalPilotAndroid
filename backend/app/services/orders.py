import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AuditEvent, Order, Position
from app.schemas import OrderCreateRequest


class OrderServiceError(Exception):
    """Base exception for order service errors."""


class DuplicateOrderConflict(OrderServiceError):
    """Raised when a client order ID has already been used."""


class OrderService:
    """Simulation-only order service."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_order(
        self,
        account_id: UUID,
        request: OrderCreateRequest,
    ) -> Order:
        """Create a simulated order without broker execution."""

        try:
            account_uuid = UUID(str(account_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise OrderServiceError("Invalid account ID.") from exc

        if not isinstance(request, OrderCreateRequest):
            raise OrderServiceError(
                "An OrderCreateRequest object is required."
            )

        quantity = request.quantity
        requested_price = request.requested_price

        if not quantity.is_finite() or quantity <= 0:
            raise OrderServiceError("Quantity must be positive and finite.")

        if requested_price is not None:
            if not requested_price.is_finite() or requested_price <= 0:
                raise OrderServiceError(
                    "Requested price must be positive and finite."
                )

        # Confirm that the account exists and is active.
        result = await self.db.execute(
            select(Account)
            .where(Account.id == account_uuid)
            .with_for_update()
        )
        account = result.scalar_one_or_none()

        if account is None:
            raise OrderServiceError("Account not found.")

        if not account.is_active:
            raise OrderServiceError("Account is inactive.")

        # Check idempotency before inserting the order.
        result = await self.db.execute(
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
            quantity=quantity,
            requested_price=requested_price,
            filled_price=None,
            status="PENDING",
            execution_mode="SIMULATED",
        )

        self.db.add(order)

        # Keep risk parameters in the audit record. They are not
        # executed or applied to a live position.
        self.db.add(
            AuditEvent(
                event_type="SIMULATED_ORDER_CREATED",
                actor="system",
                resource_id=request.client_order_id,
                details=json.dumps(
                    {
                        "account_id": str(account_uuid),
                        "symbol": request.symbol.upper(),
                        "side": request.side,
                        "order_type": request.order_type,
                        "quantity": str(quantity),
                        "requested_price": (
                            str(requested_price)
                            if requested_price is not None
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
                    }
                ),
            )
        )

        try:
            await self.db.commit()
            await self.db.refresh(order)

        except IntegrityError as exc:
            await self.db.rollback()
            raise DuplicateOrderConflict(
                "Order creation conflicted with an existing database record."
            ) from exc

        except Exception:
            await self.db.rollback()
            raise

        return order
