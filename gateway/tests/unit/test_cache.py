import pytest

from app.core.cache import ResponseCache, build_cache_key, should_cache
from app.core.limits import InMemoryRedis


def test_build_cache_key_deterministic_order() -> None:
    msgs1 = [{"role": "user", "content": "hi", "name": None}]
    msgs2 = [{"name": None, "content": "hi", "role": "user"}]

    key1 = build_cache_key(model="gpt-4o", messages=msgs1, temperature=0.0)
    key2 = build_cache_key(model="gpt-4o", messages=msgs2, temperature=0.0)
    assert key1 == key2
    assert key1.startswith("cache:")


def test_build_cache_key_different_content() -> None:
    key1 = build_cache_key(model="gpt-4o", messages=[{"role": "user", "content": "hello"}])
    key2 = build_cache_key(model="gpt-4o", messages=[{"role": "user", "content": "world"}])
    assert key1 != key2


def test_should_cache() -> None:
    assert should_cache(None) is True
    assert should_cache(0.0) is True
    assert should_cache(0.7) is False
    assert should_cache(1.0) is False


@pytest.mark.asyncio
async def test_response_cache_get_set() -> None:
    redis_mock = InMemoryRedis()
    cache = ResponseCache(redis_client=redis_mock)

    assert await cache.get("cache:dummy") is None
    await cache.set("cache:dummy", {"response": "test_ok"}, ttl_seconds=60)
    cached = await cache.get("cache:dummy")
    assert cached is not None
    assert cached["response"] == "test_ok"
