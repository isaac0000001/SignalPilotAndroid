from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AuditEvent, Order
from app.schemas import OrderCreateRequest


class OrderServiceError(Exception):
    """Base exception for order-service errors."""


class DuplicateOrderConflict(OrderServiceError):
    """Raised when an order ID is reused with different parameters."""


class OrderService:
    """Transactional simulated-order management."""

    @staticmethod
    async def create_simulated_order(
        db: AsyncSession,
        account_id: UUID,
        request: OrderCreateRequest,
    ) -> Order:
        """
        Persist a simulated order.

        The caller must run this function inside a database transaction.
        This service never sends an order to a broker or liquidity provider.
        """

        async with db.begin_nested():
            account_result = await db.execute(
                select(Account)
                .where(
                    Account.id == account_id,
                    Account.is_active.is_(True),
                )
                .with_for_update()
            )
            account = account_result.scalar_one_or_none()

            if account is None:
                raise OrderServiceError("Active account not found.")

            existing_result = await db.execute(
                select(Order).where(
                    Order.account_id == account_id,
                    Order.client_order_id == request.client_order_id,
                )
            )
            existing_order = existing_result.scalar_one_or_none()

            if existing_order is not None:
                same_request = (
                    existing_order.symbol == request.symbol
                    and existing_order.side == request.side
                    and existing_order.order_type == request.order_type
                    and existing_order.quantity == request.quantity
                    and existing_order.requested_price
                    == request.requested_price
                )

                if not same_request:
                    raise DuplicateOrderConflict(
                        "Client order ID was already used for a different order."
                    )

                return existing_order

            order = Order(
                account_id=account_id,
                client_order_id=request.client_order_id,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                requested_price=request.requested_price,
                filled_price=None,
                status="ACCEPTED",
                execution_mode="SIMULATED",
            )

            db.add(order)
            await db.flush()

            db.add(
                AuditEvent(
                    event_type="SIMULATED_ORDER_CREATED",
                    actor=str(account_id),
                    resource_id=str(order.id),
                    details=(
                        f"symbol={request.symbol};"
                        f"side={request.side};"
                        f"quantity={request.quantity}"
                    ),
                )
            )

            await db.flush()

            return order
