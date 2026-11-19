import uuid
from decimal import Decimal

import pytest

from app.core.errors import BudgetExhaustedError, RateLimitError
from app.core.limits import InMemoryRedis, LimitManager


@pytest.mark.asyncio
async def test_in_memory_redis_basics() -> None:
    store = InMemoryRedis()
    await store.set("foo", "bar", ex=10)
    assert await store.get("foo") == "bar"
    assert await store.ttl("foo") <= 10

    # Test incr
    assert await store.incr("counter") == 1
    assert await store.incr("counter") == 2

    # Test incrbyfloat
    assert await store.incrbyfloat("spend", 1.25) == 1.25
    assert await store.incrbyfloat("spend", 0.75) == 2.0


@pytest.mark.asyncio
async def test_rate_limiter_allows_and_blocks() -> None:
    redis_mock = InMemoryRedis()
    mgr = LimitManager(redis_client=redis_mock)
    key_id = uuid.uuid4()

    # Limit = 2 per minute
    await mgr.check_rate_limit(key_id, limit_per_min=2)
    await mgr.check_rate_limit(key_id, limit_per_min=2)

    # 3rd request must raise RateLimitError with Retry-After
    with pytest.raises(RateLimitError) as exc_info:
        await mgr.check_rate_limit(key_id, limit_per_min=2)

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers
    assert int(exc_info.value.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_budget_manager_enforces_limit() -> None:
    redis_mock = InMemoryRedis()
    mgr = LimitManager(redis_client=redis_mock)
    key_id = uuid.uuid4()

    # Seed spend at $9.50, budget $10.00
    await mgr.record_spend(key_id, Decimal("9.50"))

    # Mock DB session won't be called if spend key exists in Redis
    class DummyDB:
        pass

    # $9.50 < $10.00 -> should pass
    await mgr.check_budget(key_id, Decimal("10.00"), db=DummyDB())  # type: ignore[arg-type]

    # Add $0.60 -> spend is now $10.10 >= $10.00
    await mgr.record_spend(key_id, Decimal("0.60"))

    # Must raise BudgetExhaustedError (402)
    with pytest.raises(BudgetExhaustedError) as exc_info:
        await mgr.check_budget(key_id, Decimal("10.00"), db=DummyDB())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 402
