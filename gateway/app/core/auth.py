import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from decimal import Decimal

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError
from app.db.models import APIKey
from app.db.session import get_db


@dataclass
class AuthenticatedKey:
    id: uuid.UUID
    name: str
    key_prefix: str
    monthly_budget_usd: Decimal
    rate_limit_per_min: int
    redaction_enabled: bool
    active: bool


def hash_key(raw_key: str) -> str:
    """Computes SHA-256 hex digest of the raw key."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = "mg_live_") -> tuple[str, str, str]:
    """
    Generates a secure random API key.
    Returns: (raw_key, key_prefix, key_hash)
    """
    random_part = secrets.token_urlsafe(32)
    raw_key = f"{prefix}{random_part}"
    key_prefix = raw_key[:8]
    key_hash = hash_key(raw_key)
    return raw_key, key_prefix, key_hash


def constant_time_compare(val1: str, val2: str) -> bool:
    return hmac.compare_digest(val1.encode("utf-8"), val2.encode("utf-8"))


async def authenticate_bearer_key(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedKey:
    if not authorization:
        raise AuthenticationError("Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthenticationError("Invalid Authorization header format. Expected 'Bearer <key>'")

    raw_key = parts[1]
    calculated_hash = hash_key(raw_key)

    stmt = select(APIKey).where(APIKey.key_hash == calculated_hash)
    result = await db.execute(stmt)
    key_record = result.scalars().first()

    if not key_record or not key_record.active:
        raise AuthenticationError("Invalid or inactive API key")

    return AuthenticatedKey(
        id=key_record.id,
        name=key_record.name,
        key_prefix=key_record.key_prefix,
        monthly_budget_usd=key_record.monthly_budget_usd,
        rate_limit_per_min=key_record.rate_limit_per_min,
        redaction_enabled=key_record.redaction_enabled,
        active=key_record.active,
    )
