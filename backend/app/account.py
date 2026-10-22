from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Account


settings = get_settings()


class AccountServiceError(Exception):
    """Base exception for account-service errors."""


class AccountNotFoundError(AccountServiceError):
    """Raised when an account cannot be found."""


class AccountService:
    """Operations for a single owner's trading account."""

    @staticmethod
    async def create_personal_account(
        db: AsyncSession,
        *,
        name: str = "SignalPilot Pro Personal Account",
        currency: str = "USD",
        initial_balance: Decimal | None = None,
    ) -> Account:
        """
        Create an account once.

        This method does not commit the transaction; the caller owns
        transaction management.
        """

        result = await db.execute(
            select(Account.id).limit(1)
        )

        if result.scalar_one_or_none() is not None:
            raise AccountServiceError(
                "An account already exists. "
                "Use the existing account instead of creating another."
            )

        balance = (
            initial_balance
            if initial_balance is not None
            else Decimal(str(settings.DEFAULT_ACCOUNT_BALANCE))
        )

        if not balance.is_finite() or balance <= Decimal("0"):
            raise ValueError(
                "Initial balance must be a finite positive amount."
            )

        normalized_currency = currency.upper()

        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise ValueError("Currency must be a three-letter code.")

        account = Account(
            name=name,
            currency=normalized_currency,
            initial_balance=balance,
            balance=balance,
            equity=balance,
            is_active=True,
        )

        db.add(account)
        await db.flush()

        return account

    @staticmethod
    async def get_account(
        db: AsyncSession,
        account_id: UUID,
        *,
        lock: bool = False,
    ) -> Account:
        """Retrieve an account, optionally acquiring a row lock."""

        statement = select(Account).where(
            Account.id == account_id
        )

        if lock:
            statement = statement.with_for_update()

        result = await db.execute(statement)
        account = result.scalar_one_or_none()

        if account is None:
            raise AccountNotFoundError("Account not found.")

        return account
