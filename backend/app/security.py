from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.config import get_settings


settings = get_settings()

password_hasher = PasswordHash.recommended()

ALGORITHM = "HS256"


class AuthenticationError(Exception):
    """Raised when authentication fails."""


def hash_password(password: str) -> str:
    """Hash a password before storing it."""

    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")

    if len(password) > 1024:
        raise ValueError("Password is too long.")

    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its stored hash."""

    try:
        return password_hasher.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: UUID | str) -> str:
    """Create a short-lived signed access token."""

    secret = settings.SECRET_KEY.get_secret_value()

    if len(secret) < 32:
        raise RuntimeError(
            "A strong SECRET_KEY must be configured before issuing tokens."
        )

    now = datetime.now(timezone.utc)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": now + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        ),
        "jti": __import__("secrets").token_urlsafe(24),
        "type": "access",
    }

    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> UUID:
    """Validate a token and return its account identifier."""

    secret = settings.SECRET_KEY.get_secret_value()

    if len(secret) < 32:
        raise AuthenticationError("Authentication is not configured.")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={
                "require": ["sub", "iat", "exp", "jti", "type"],
            },
            leeway=0,
        )

        if payload.get("type") != "access":
            raise AuthenticationError("Invalid token type.")

        return UUID(payload["sub"])

    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise AuthenticationError("Invalid or expired access token.") from exc
