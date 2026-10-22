from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Account
from app.security import AuthenticationError, decode_access_token


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="SignalPilotAccessToken",
)


async def get_current_account(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Account:
    """Authenticate a request and return its active account."""

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        account_id: UUID = decode_access_token(credentials.credentials)
    except AuthenticationError:
        raise unauthorized

    result = await db.execute(
        select(Account).where(
            Account.id == account_id,
            Account.is_active.is_(True),
        )
    )

    account = result.scalar_one_or_none()

    if account is None:
        raise unauthorized

    return account


CurrentAccount = Annotated[
    Account,
    Depends(get_current_account),
]
