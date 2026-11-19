import contextlib
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import BudgetExhaustedError, RateLimitError
from app.db.models import APIKey, RequestRecord


class InMemoryRedis:
    """In-memory Redis-compatible store for tests or when Redis is offline."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expires: dict[str, float] = {}

    def _purge_expired(self, key: str) -> None:
        if key in self._expires and time.time() > self._expires[key]:
            del self._data[key]
            del self._expires[key]

    async def get(self, key: str) -> str | None:
        self._purge_expired(key)
        return self._data.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None, px: int | None = None) -> bool:
        self._data[key] = str(value)
        if ex is not None:
            self._expires[key] = time.time() + ex
        elif px is not None:
            self._expires[key] = time.time() + (px / 1000.0)
        return True

    async def incr(self, key: str) -> int:
        self._purge_expired(key)
        val = int(self._data.get(key, "0")) + 1
        self._data[key] = str(val)
        return val

    async def incrbyfloat(self, key: str, amount: float) -> float:
        self._purge_expired(key)
        val = float(self._data.get(key, "0.0")) + amount
        self._data[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self._data:
            self._expires[key] = time.time() + seconds
            return True
        return False

    async def ttl(self, key: str) -> int:
        if key not in self._data:
            return -2
        if key not in self._expires:
            return -1
        rem = int(self._expires[key] - time.time())
        return max(0, rem)

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                self._expires.pop(k, None)
                count += 1
        return count

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._data.clear()
        self._expires.clear()


_redis_client: Any = None


def get_redis() -> Any:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        try:
            _redis_client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
        except Exception:
            _redis_client = InMemoryRedis()
    return _redis_client


def set_redis(client: Any) -> None:
    global _redis_client
    _redis_client = client


def get_current_month_key(key_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    return f"spend:{key_id}:{now.year}-{now.month:02d}"


def get_rate_limit_key(key_id: uuid.UUID) -> tuple[str, int]:
    current_minute = int(time.time() // 60)
    seconds_remaining = 60 - (int(time.time()) % 60)
    return f"ratelimit:{key_id}:{current_minute}", seconds_remaining


class LimitManager:
    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    @property
    def redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        return get_redis()

    async def check_rate_limit(self, key_id: uuid.UUID, limit_per_min: int) -> None:
        """
        Fixed-window rate limit using Redis INCR + EXPIRE.
        Raises RateLimitError(429) with Retry-After if exceeded.
        """
        rl_key, remaining_secs = get_rate_limit_key(key_id)
        try:
            current_count = await self.redis.incr(rl_key)
            if current_count == 1:
                await self.redis.expire(rl_key, 60)

            if current_count > limit_per_min:
                raise RateLimitError(
                    message=f"Rate limit exceeded: maximum {limit_per_min} requests per minute",
                    retry_after=remaining_secs,
                )
        except RateLimitError:
            raise
        except Exception:
            # Per ADR 1: fail open on Redis errors for rate limiting
            pass

    async def check_budget(
        self,
        key_id: uuid.UUID,
        monthly_budget_usd: Decimal,
        db: AsyncSession,
    ) -> None:
        """
        Checks monthly spend against monthly budget.
        Raises BudgetExhaustedError(402) if monthly budget exceeded.
        """
        spend_key = get_current_month_key(key_id)
        try:
            raw_spend = await self.redis.get(spend_key)
            if raw_spend is None:
                # Reconcile from Postgres
                current_spend = await self.reconcile_key_spend(key_id, db)
            else:
                current_spend = Decimal(str(raw_spend))

            if current_spend >= monthly_budget_usd:
                raise BudgetExhaustedError(
                    f"Monthly budget of ${monthly_budget_usd:.2f} exceeded. "
                    f"Current spend: ${current_spend:.4f}"
                )
        except BudgetExhaustedError:
            raise
        except Exception as e:
            # If Redis connection fails, check directly from DB
            spend_db = await self.query_current_month_spend_from_db(key_id, db)
            if spend_db >= monthly_budget_usd:
                raise BudgetExhaustedError(
                    f"Monthly budget of ${monthly_budget_usd:.2f} exceeded."
                ) from e

    async def record_spend(self, key_id: uuid.UUID, cost_usd: Decimal) -> None:
        """Increments current month spend counter in Redis."""
        if cost_usd <= 0:
            return
        spend_key = get_current_month_key(key_id)
        with contextlib.suppress(Exception):
            await self.redis.incrbyfloat(spend_key, float(cost_usd))
            await self.redis.expire(spend_key, 31 * 86400)

    async def query_current_month_spend_from_db(
        self, key_id: uuid.UUID, db: AsyncSession
    ) -> Decimal:
        now = datetime.now(UTC)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=UTC)
        stmt = select(func.coalesce(func.sum(RequestRecord.cost_usd), Decimal("0.0"))).where(
            RequestRecord.key_id == key_id,
            RequestRecord.created_at >= start_of_month,
        )
        result = await db.execute(stmt)
        return Decimal(str(result.scalar_one()))

    async def reconcile_key_spend(self, key_id: uuid.UUID, db: AsyncSession) -> Decimal:
        spend = await self.query_current_month_spend_from_db(key_id, db)
        spend_key = get_current_month_key(key_id)
        with contextlib.suppress(Exception):
            await self.redis.set(spend_key, str(float(spend)), ex=31 * 86400)
        return spend

    async def reconcile_all_active_keys(self, db: AsyncSession) -> None:
        """Reconciles spend counters from Postgres for all active API keys."""
        stmt = select(APIKey.id).where(APIKey.active.is_(True))
        result = await db.execute(stmt)
        key_ids = result.scalars().all()
        for k_id in key_ids:
            await self.reconcile_key_spend(k_id, db)
