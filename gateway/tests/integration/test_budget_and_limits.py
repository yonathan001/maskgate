from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limits import InMemoryRedis, LimitManager, set_redis
from app.db.models import APIKey, RequestRecord
from app.providers.mock import MockProvider
from app.providers.registry import ModelConfig, PricePer1K, ProviderRoute, get_model_registry


@pytest.fixture(autouse=True)
def reset_redis_store() -> None:
    """Ensure a fresh in-memory Redis instance for each test."""
    store = InMemoryRedis()
    set_redis(store)


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Create key with limit = 2 per minute
    raw_key = "mg_live_rate_limit_test"
    from app.core.auth import hash_key

    key = APIKey(
        name="rate-limit-test",
        key_prefix="mg_live_",
        key_hash=hash_key(raw_key),
        monthly_budget_usd=Decimal("100.00"),
        rate_limit_per_min=2,
        redaction_enabled=False,
        active=True,
    )
    db_session.add(key)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {"model": "mock-fast", "messages": [{"role": "user", "content": "hi"}]}

    # 1st request -> 200 OK
    resp1 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp1.status_code == 200

    # 2nd request -> 200 OK
    resp2 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp2.status_code == 200

    # 3rd request -> 429 Too Many Requests
    resp3 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp3.status_code == 429
    assert "Retry-After" in resp3.headers
    assert int(resp3.headers["Retry-After"]) > 0
    data = resp3.json()
    assert data["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_budget_exhausted_returns_402(client: AsyncClient, db_session: AsyncSession) -> None:
    raw_key = "mg_live_budget_test"
    from app.core.auth import hash_key

    # Tiny budget of $0.0005
    key = APIKey(
        name="budget-test",
        key_prefix="mg_live_",
        key_hash=hash_key(raw_key),
        monthly_budget_usd=Decimal("0.0005"),
        rate_limit_per_min=100,
        redaction_enabled=False,
        active=True,
    )
    db_session.add(key)
    await db_session.commit()

    # Configure priced model: $0.001 per 1k input tokens
    registry = get_model_registry()
    registry.register_provider("mock", MockProvider())
    registry.models["priced-model"] = ModelConfig(
        name="priced-model",
        providers=[ProviderRoute(provider="mock", upstream_model="mock-fast")],
        price_per_1k=PricePer1K(input=Decimal("0.001"), output=Decimal("0.001")),
    )

    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "model": "priced-model",
        "messages": [{"role": "user", "content": "Hello budget tracking!"}],
    }

    # 1st request costs ~ $0.000007, passes
    resp1 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp1.status_code == 200

    # Simulate heavy spend directly in redis / limit manager to exceed $0.0005
    mgr = LimitManager()
    await mgr.record_spend(key.id, Decimal("0.0010"))

    # Next request must be rejected with 402
    resp2 = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp2.status_code == 402
    data = resp2.json()
    assert data["error"]["code"] == "budget_exceeded"


@pytest.mark.asyncio
async def test_counter_reconciliation_from_postgres(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    raw_key = "mg_live_reconcile_test"
    from app.core.auth import hash_key

    # Budget of $5.00
    key = APIKey(
        name="reconcile-test",
        key_prefix="mg_live_",
        key_hash=hash_key(raw_key),
        monthly_budget_usd=Decimal("5.00"),
        rate_limit_per_min=100,
        redaction_enabled=False,
        active=True,
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)

    # Insert historical request with $6.00 spend directly into Postgres
    import uuid

    record = RequestRecord(
        id=uuid.uuid4(),
        key_id=key.id,
        model="mock-fast",
        provider_used="mock",
        fallback_used=False,
        cache_hit=False,
        streamed=False,
        status_code=200,
        latency_ms=10,
        gateway_overhead_ms=2,
        input_tokens=100,
        output_tokens=100,
        cost_usd=Decimal("6.000000"),
        pii_count=0,
        pii_types=[],
        trace_id=None,
    )
    db_session.add(record)
    await db_session.commit()

    # Reset Redis to empty (simulating gateway restart / cold cache)
    fresh_redis = InMemoryRedis()
    set_redis(fresh_redis)

    # Trigger reconciliation
    mgr = LimitManager()
    await mgr.reconcile_all_active_keys(db_session)

    # Now request should immediately receive 402 because Postgres had $6.00 > $5.00
    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {"model": "mock-fast", "messages": [{"role": "user", "content": "test"}]}
    resp = await client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "budget_exceeded"
